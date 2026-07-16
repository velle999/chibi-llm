"""
LLM Client — connects to Ollama, llama.cpp, or SynapseOS synapd.
Supports streaming responses for real-time avatar reactions.

Backends (config.llm_backend):
  "ollama"    — Ollama HTTP server (default)
  "llamacpp"  — llama.cpp HTTP /completion server
  "synapd"    — SynapseOS's kernel-native AI daemon. Reached over its unix
                socket when chibi runs on the SynapseOS box itself, or over TCP
                (config.synapd_host/synapd_port) when it runs somewhere else,
                e.g. the Pi. Lets chibi "talk through" the OS's own synapd brain
                instead of a separate model server. Optional — only used when set.

                The TCP path expects synapd-bridge.socket on the SynapseOS host,
                which fronts the unix socket on 11435. synapd's protocol has no
                authentication, so that port is pinned to one source IP by
                /etc/nftables.d/synapd-bridge.nft — point this at a host you
                control, never at an untrusted network.
"""

import json
import os
import socket
import struct
import threading
import time
import urllib.request
import urllib.error
import http.client
from config import Config

# ── synapd wire protocol (see SYNAPSE/synapd/include/synapd.h) ──────────────
# Packed header: magic, version, msg_type, flags, payload_len, request_id,
# client_pid, timestamp_ns.  "<IBBHIIIQ" == 28 bytes, little-endian, no padding.
_SYNAPD_HDR = struct.Struct("<IBBHIIIQ")
_SYNAPD_MAGIC = 0x53594E41          # "SYNA"
_SYNAPD_VER = 1
_SYNAPD_MSG_QUERY = 0x01
_SYNAPD_MSG_ERROR = 0xFF


class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.connected = False
        self._check_connection()

    def start_health_check(self, interval: float = 30.0):
        """Ping the server periodically (daemon thread) so `connected` stays
        honest between messages — otherwise the status dot shows a green light
        for hours after the server goes down."""
        def _loop():
            while True:
                time.sleep(interval)
                self._check_connection()
        threading.Thread(target=_loop, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://{self.config.llm_host}:{self.config.llm_port}"

    @property
    def synapd_socket(self) -> str:
        return getattr(self.config, "synapd_socket", "/run/synapd/synapd.sock")

    @property
    def synapd_host(self) -> str:
        """Empty means local: use the unix socket. Set it to reach the bridge."""
        return getattr(self.config, "synapd_host", "") or ""

    @property
    def synapd_port(self) -> int:
        return int(getattr(self.config, "synapd_port", 11435))

    @property
    def synapd_target(self) -> str:
        """How we describe the endpoint in errors, so a failure says which of
        the two transports it was actually trying."""
        if self.synapd_host:
            return f"{self.synapd_host}:{self.synapd_port}"
        return self.synapd_socket

    def _synapd_connect(self, timeout: float):
        """Connect to synapd over TCP if a host is configured, else the unix
        socket. Both transports carry the identical binary protocol — the bridge
        is a byte proxy, not a translator — so every caller can share this."""
        if self.synapd_host:
            sock = socket.create_connection(
                (self.synapd_host, self.synapd_port), timeout=timeout)
            # The reply can be seconds of generation; don't let Nagle sit on the
            # request half of a single small write.
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(self.synapd_socket)
        return sock

    def _check_connection(self):
        try:
            if self.config.llm_backend == "synapd":
                # A successful connect is enough of a ping.
                with self._synapd_connect(5):
                    pass
                self.connected = True
                return
            url = self.base_url
            if self.config.llm_backend == "ollama":
                url += "/api/tags"
            else:
                url += "/health"
            req = urllib.request.Request(url, method="GET")
            req.add_header("Connection", "close")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.connected = resp.status == 200
        except Exception:
            self.connected = False

    def stream_chat(self, messages: list[dict], extra_system: str = "",
                    num_predict: int | None = None):
        """Generator that yields text chunks from the LLM.

        num_predict caps the reply length (Ollama). None falls back to the
        configured llm_num_predict; callers pass a larger value for modes
        that legitimately need a longer answer (e.g. the Thoth scribe).
        """
        max_msgs = self.config.max_conversation_history
        if len(messages) > max_msgs:
            messages = messages[-max_msgs:]

        if num_predict is None:
            num_predict = getattr(self.config, "llm_num_predict", 110)

        # Dispatch explicitly. A bare `else: llamacpp` used to catch unknown
        # backends too, so a typo — or a config that names a backend this copy
        # of the file has not got — silently spoke llama.cpp's protocol at
        # whatever was listening, instead of saying so. Fail loudly.
        backend = self.config.llm_backend
        if backend == "synapd":
            yield from self._stream_synapd(messages, extra_system, num_predict)
        elif backend == "ollama":
            yield from self._stream_ollama(messages, extra_system, num_predict)
        elif backend == "llamacpp":
            yield from self._stream_llamacpp(messages, extra_system, num_predict)
        else:
            raise ValueError(
                f"llm_backend={backend!r} is not one of "
                "'ollama', 'llamacpp', 'synapd'")

    def _stream_synapd(self, messages: list[dict], extra_system: str = "",
                       num_predict: int = 110):
        """Query SynapseOS's synapd over its unix socket, or the TCP bridge.

        synapd is a single-shot request/response daemon (no token streaming),
        so we send one QUERY and yield the reply in word-sized chunks — enough
        for the avatar's bubble/voice to animate as if streamed. The daemon
        prepends its own system prompt; chibi's persona is folded into the
        prompt text so the reply still sounds like chibi.
        """
        system_prompt = self.config.llm_system_prompt + extra_system
        prompt = system_prompt + "\n\n"
        for msg in messages:
            role = msg.get("role", "user").capitalize()
            prompt += f"{role}: {msg.get('content', '')}\n"
        prompt += "Assistant:"

        # Null-terminate so synapd reads a clean C string, mirroring how it
        # frames its own responses (strlen + 1).
        payload = prompt.encode("utf-8") + b"\x00"
        header = _SYNAPD_HDR.pack(
            _SYNAPD_MAGIC, _SYNAPD_VER, _SYNAPD_MSG_QUERY, 0,
            len(payload), 1, os.getpid(), 0,
        )

        sock = None
        try:
            sock = self._synapd_connect(120)
            sock.sendall(header + payload)
            self.connected = True

            resp_hdr = self._recv_exact(sock, _SYNAPD_HDR.size)
            (magic, _ver, msg_type, _flags,
             plen, _rid, _pid, _ts) = _SYNAPD_HDR.unpack(resp_hdr)
            if magic != _SYNAPD_MAGIC:
                raise ConnectionError("synapd: bad response magic")

            body = self._recv_exact(sock, plen) if plen else b""
            text = body.split(b"\x00", 1)[0].decode("utf-8", "replace")

            if msg_type == _SYNAPD_MSG_ERROR:
                raise ConnectionError(f"synapd error: {text}")

            # Fake streaming: hand back word by word so the UI stays lively.
            words = text.split(" ")
            for i, w in enumerate(words):
                if w:
                    yield w if i == len(words) - 1 else w + " "

        except (ConnectionError, OSError) as e:
            self.connected = False
            raise ConnectionError(f"Cannot reach synapd at {self.synapd_target}: {e}")
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    @staticmethod
    def _recv_exact(sock, n: int) -> bytes:
        """Read exactly n bytes or raise — a recv can always come up short, and
        over TCP it routinely does once a reply spans segments, so loop until
        satisfied."""
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("synapd: connection closed mid-message")
            buf.extend(chunk)
        return bytes(buf)

    def _stream_ollama(self, messages: list[dict], extra_system: str = "",
                       num_predict: int = 110):
        """Stream from Ollama /api/chat — line-buffered for reliability."""
        url = f"{self.base_url}/api/chat"

        system_prompt = self.config.llm_system_prompt + extra_system
        full_messages = [
            {"role": "system", "content": system_prompt}
        ] + messages

        payload = json.dumps({
            "model": self.config.llm_model,
            "messages": full_messages,
            "stream": True,
            "options": {
                "num_predict": num_predict,
                "temperature": getattr(self.config, "llm_temperature", 0.7),
            },
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        resp = None
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            self.connected = True

            # Iterate lines — much more reliable than byte-by-byte
            for raw_line in resp:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "message" in data and "content" in data["message"]:
                        text = data["message"]["content"]
                        if text:
                            yield text
                    if data.get("done", False):
                        return
                except json.JSONDecodeError:
                    continue

        except urllib.error.URLError as e:
            self.connected = False
            raise ConnectionError(f"Cannot reach Ollama at {url}: {e}")
        except (http.client.RemoteDisconnected, ConnectionResetError) as e:
            self.connected = False
            raise ConnectionError(f"Connection lost: {e}")
        except Exception as e:
            self.connected = False
            raise
        finally:
            if resp:
                try:
                    resp.close()
                except Exception:
                    pass

    def _stream_llamacpp(self, messages: list[dict], extra_system: str = "",
                         num_predict: int = 110):
        """Stream from llama.cpp /completion endpoint."""
        url = f"{self.base_url}/completion"

        system_prompt = self.config.llm_system_prompt + extra_system
        prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        for msg in messages:
            prompt += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"

        payload = json.dumps({
            "prompt": prompt,
            "stream": True,
            "n_predict": num_predict,
            "temperature": getattr(self.config, "llm_temperature", 0.7),
            "stop": ["<|im_end|>", "<|im_start|>"],
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        resp = None
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            self.connected = True

            for raw_line in resp:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith(b"data: "):
                    json_str = line[6:]
                    if json_str == b"[DONE]":
                        return
                    try:
                        data = json.loads(json_str)
                        text = data.get("content", "")
                        if text:
                            yield text
                        if data.get("stop", False):
                            return
                    except json.JSONDecodeError:
                        continue

        except urllib.error.URLError as e:
            self.connected = False
            raise ConnectionError(f"Cannot reach llama.cpp at {url}: {e}")
        except Exception as e:
            self.connected = False
            raise
        finally:
            if resp:
                try:
                    resp.close()
                except Exception:
                    pass
