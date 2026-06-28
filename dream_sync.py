"""
Dream Journal Sync — keeps the dream/vision journal in step across two chibi
instances over the LAN (the Pi in the bedroom and the PC in the living room).

Design: peer-to-peer union-merge.
  • Each instance runs a tiny HTTP server exposing its own dream entries.
  • Each instance periodically pulls the *peer's* entries and merges them in.

Dream entries are append-only and never trimmed, and every entry carries a
high-resolution `created_at` timestamp, so the union of both lists is the
correct, conflict-free result. Merging is idempotent and order-independent,
so the two journals converge no matter which machine happens to be online
when a dream is recorded — whoever comes online later just pulls the rest.

Stdlib only (http.server + urllib) — no extra dependencies, runs fine on a Pi.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class DreamSync:
    """Bidirectional LAN sync for the dream journal between two chibi instances."""

    def __init__(self, memory, config):
        self.memory = memory
        self.peer_host = getattr(config, "dream_sync_peer_host", "").strip()
        self.port = int(getattr(config, "dream_sync_port", 8077))
        self.token = getattr(config, "dream_sync_token", "")
        self.interval = int(getattr(config, "dream_sync_interval", 300))
        self.timeout = float(getattr(config, "dream_sync_timeout", 8.0))
        self._server = None
        self._stop = threading.Event()

    # ─── Server side: expose our journal to the peer ──────────────────────

    def start_server(self):
        memory = self.memory
        token = self.token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # silence stderr access logging
                pass

            def _auth_ok(self):
                return not token or self.headers.get("X-Sync-Token") == token

            def do_GET(self):
                if self.path.rstrip("/") != "/dreams":
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._auth_ok():
                    self.send_response(403)
                    self.end_headers()
                    return
                body = json.dumps(memory.get_dream_entries()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError as e:
            print(f"[DreamSync] Could not bind port {self.port}: {e}")
            return
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        print(f"[DreamSync] Serving dream journal on :{self.port}")

    # ─── Client side: pull the peer's journal and merge ───────────────────

    def sync_once(self) -> int:
        """Pull the peer's dream entries and merge new ones in. Returns count added."""
        if not self.peer_host:
            return 0
        url = f"http://{self.peer_host}:{self.port}/dreams"
        req = urllib.request.Request(url)
        if self.token:
            req.add_header("X-Sync-Token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                remote = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"[DreamSync] Peer {self.peer_host} unreachable: {e}")
            return 0
        added = self.memory.merge_dream_entries(remote)
        if added:
            noun = "entry" if added == 1 else "entries"
            print(f"[DreamSync] Pulled {added} new dream {noun} from {self.peer_host}")
        return added

    def _loop(self):
        # Brief delay so the peer's server has a chance to come up too.
        self._stop.wait(5)
        while not self._stop.is_set():
            self.sync_once()
            self._stop.wait(self.interval)

    def start(self):
        """Start the server and the periodic pull loop (both as daemon threads)."""
        self.start_server()
        threading.Thread(target=self._loop, daemon=True).start()

    def sync_soon(self):
        """Kick a one-off pull off the main thread (e.g. just after recording a dream)."""
        threading.Thread(target=self.sync_once, daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._server:
            self._server.shutdown()
