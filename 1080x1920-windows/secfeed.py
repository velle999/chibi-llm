"""
Secfeed — subscriber for synguard's security-verdict broadcast feed.

synguard (the SynapseOS security monitor) publishes one fixed-size record to
every subscriber whenever it takes a window-relevant verdict on a process:

    /run/synguard.sock — AF_UNIX SOCK_STREAM, mode 0666 so unprivileged
    clients (the compositor, and now Chibi) can subscribe without being root.

Wire format is a packed 152-byte struct (sg_secfeed_msg_t in synguard.h) with a
FIXED layout — it must stay in lockstep with that header:

    uint32 magic ("SGFV") | uint32 version | uint32 pid | uint32 uid
    int32  verdict        | int32  threat  | char[16] comm | char[112] reason

This module is stdlib-only on purpose: it is imported by Chibi's security aspect
and has to keep working inside the ISO's bundled runtime.

Chibi is a READ-ONLY subscriber. She observes and narrates verdicts; she never
sends anything back, and cannot allow, deny, or quarantine anything. synguard
remains the sole authority — see docs/security-overview.md.
"""

import os
import socket
import struct
import subprocess
import threading
import time
from collections import Counter, deque

SOCKET_PATH = "/run/synguard.sock"

SECFEED_MAGIC = 0x53474656   # "SGFV"
SECFEED_VERSION = 1

# Must match sg_secfeed_msg_t exactly: little-endian, no padding, 152 bytes.
RECORD_FMT = "<IIIIii16s112s"
RECORD_SIZE = struct.calcsize(RECORD_FMT)
assert RECORD_SIZE == 152, f"secfeed record must be 152 bytes, got {RECORD_SIZE}"

VERDICTS = {
    0: "allow",
    1: "log",
    2: "alert",
    3: "escalate",
    4: "deny",
    5: "quarantine",
}
THREATS = {
    0: "none",
    1: "low",
    2: "medium",
    3: "high",
    4: "critical",
}

VERDICT_ALERT = 2
THREAT_MEDIUM = 2


def _cstr(raw: bytes) -> str:
    """Decode a fixed-width NUL-padded C string field."""
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


class SecEvent:
    __slots__ = ("pid", "uid", "verdict", "threat", "comm", "reason", "when")

    def __init__(self, pid, uid, verdict, threat, comm, reason):
        self.pid = pid
        self.uid = uid
        self.verdict = verdict
        self.threat = threat
        self.comm = comm
        self.reason = reason
        self.when = time.time()

    @property
    def verdict_name(self) -> str:
        return VERDICTS.get(self.verdict, f"verdict-{self.verdict}")

    @property
    def threat_name(self) -> str:
        return THREATS.get(self.threat, f"threat-{self.threat}")

    @property
    def notable(self) -> bool:
        """Worth interrupting a human for. Plain allow/log traffic is not."""
        return self.verdict >= VERDICT_ALERT or self.threat >= THREAT_MEDIUM

    def describe(self) -> str:
        s = f"{self.verdict_name} {self.comm} (pid {self.pid}"
        if self.threat:
            s += f", {self.threat_name} threat"
        s += ")"
        if self.reason:
            s += f": {self.reason}"
        return s


class SecFeed:
    """Background subscriber to synguard's verdict feed.

    Never raises into the caller and never blocks the render loop: if synguard
    is not running the socket simply does not exist, and the reader thread
    retries with a backoff. `available` reports whether we are currently
    attached, so the aspect can say "the monitor is down" rather than
    pretending the system is clean — an absent feed is not a quiet system.
    """

    def __init__(self, socket_path: str = SOCKET_PATH, history: int = 60):
        self.socket_path = socket_path
        self.events = deque(maxlen=history)
        self.verdict_counts = Counter()
        self.threat_counts = Counter()
        self.available = False
        self.total = 0

        self._lock = threading.Lock()
        self._pending = deque()     # notable events not yet announced aloud
        self._running = False
        self._sock = None
        self._thread = None

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        # Shut the socket down rather than just closing it: the reader thread is
        # parked in a blocking recv() and close() alone would not wake it.
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    # ── reader thread ────────────────────────────────────────────────────
    def _reader(self):
        backoff = 1.0
        while self._running:
            if not os.path.exists(self.socket_path):
                self.available = False
                time.sleep(min(backoff, 15.0))
                backoff = min(backoff * 2, 15.0)
                continue
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self.socket_path)
                self._sock = sock
                self.available = True
                backoff = 1.0
                print("[SecFeed] subscribed to synguard")
                self._consume(sock)
            except OSError as e:
                if self._running:
                    print(f"[SecFeed] connect failed: {e}")
            finally:
                self.available = False
                if self._sock is not None:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None
            if self._running:
                time.sleep(min(backoff, 15.0))
                backoff = min(backoff * 2, 15.0)

    def _consume(self, sock):
        """Read fixed-size records until the feed closes."""
        buf = b""
        while self._running:
            chunk = sock.recv(4096)
            if not chunk:
                print("[SecFeed] synguard closed the feed")
                return
            buf += chunk
            # recv() gives us a byte stream, not message boundaries: a record
            # can arrive split across reads, or several can arrive coalesced.
            while len(buf) >= RECORD_SIZE:
                record, buf = buf[:RECORD_SIZE], buf[RECORD_SIZE:]
                self._ingest(record)

    def _ingest(self, record: bytes):
        try:
            magic, version, pid, uid, verdict, threat, comm, reason = struct.unpack(
                RECORD_FMT, record)
        except struct.error:
            return
        if magic != SECFEED_MAGIC:
            # Framing is lost — a desync would misparse every later record, so
            # say so loudly rather than narrating garbage as security events.
            print(f"[SecFeed] bad magic {magic:#x} — ignoring record")
            return
        if version != SECFEED_VERSION:
            print(f"[SecFeed] unsupported feed version {version} "
                  f"(expected {SECFEED_VERSION}) — synguard/chibi out of step")
            return

        ev = SecEvent(pid, uid, verdict, threat, _cstr(comm), _cstr(reason))
        with self._lock:
            self.events.append(ev)
            self.verdict_counts[ev.verdict_name] += 1
            self.threat_counts[ev.threat_name] += 1
            self.total += 1
            if ev.notable:
                self._pending.append(ev)

    # ── query API ────────────────────────────────────────────────────────
    def drain_notable(self) -> list:
        """Pop notable events that have not been announced yet."""
        with self._lock:
            out = list(self._pending)
            self._pending.clear()
        return out

    def recent(self, n: int = 5) -> list:
        with self._lock:
            return list(self.events)[-n:]

    def service_state(self) -> str:
        """synguard's systemd state — distinguishes 'quiet' from 'not watching'."""
        try:
            r = subprocess.run(["systemctl", "is-active", "synguard"],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    def overview(self) -> str:
        """A plain-language security overview, for speech and prompt context."""
        state = self.service_state()
        if state != "active":
            return (f"synguard is {state} — the system is NOT being monitored. "
                    "No verdicts are being recorded.")

        if not self.available:
            return ("synguard is running, but I am not attached to its feed yet. "
                    "I cannot see live verdicts.")

        with self._lock:
            total = self.total
            verdicts = dict(self.verdict_counts)
            recent = list(self.events)[-5:]
            worst = max((e.threat for e in self.events), default=0)

        if total == 0:
            return ("synguard is active and I am attached to the feed. "
                    "No security verdicts so far this session — the system is quiet.")

        denied = verdicts.get("deny", 0) + verdicts.get("quarantine", 0)
        alerted = verdicts.get("alert", 0) + verdicts.get("escalate", 0)

        parts = [f"synguard is active. {total} verdict"
                 f"{'s' if total != 1 else ''} this session"]
        if denied:
            parts.append(f"{denied} blocked")
        if alerted:
            parts.append(f"{alerted} flagged")
        if not denied and not alerted:
            parts.append("nothing blocked or flagged")
        parts.append(f"highest threat seen: {THREATS.get(worst, 'unknown')}")

        summary = "; ".join(parts) + "."
        if recent:
            summary += " Most recent: " + "; ".join(e.describe() for e in recent) + "."
        return summary
