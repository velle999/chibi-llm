"""
LLM Client — connects to Ollama or llama.cpp server on your PC.
Supports streaming responses for real-time avatar reactions.
"""

import json
import threading
import time
import urllib.request
import urllib.error
import http.client
from config import Config


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

    def _check_connection(self):
        try:
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

        if self.config.llm_backend == "ollama":
            yield from self._stream_ollama(messages, extra_system, num_predict)
        else:
            yield from self._stream_llamacpp(messages, extra_system, num_predict)

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
