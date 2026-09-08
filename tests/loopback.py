"""In-process synthetic HTTP server bound only to 127.0.0.1."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional


class LoopbackState:
    def __init__(self, mode: str, extra: Optional[Dict[str, Any]] = None) -> None:
        self.mode = mode
        self.extra = extra or {}
        self.lock = threading.Lock()
        self.requests: List[Dict[str, Any]] = []
        self.release = threading.Event()

    def add(self, record: Dict[str, Any]) -> None:
        with self.lock:
            self.requests.append(record)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.requests)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle()

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 0:
            return b""
        return self.rfile.read(length)

    def _record(self, body: bytes) -> None:
        authorization = self.headers.get("Authorization")
        self.server.state.add(
            {
                "method": self.command,
                "path": self.path,
                "authorization": authorization,
                "content_type": self.headers.get("Content-Type"),
                "body": body,
                "header_names": [name.lower() for name in self.headers.keys()],
            }
        )

    def _handle(self) -> None:
        state: LoopbackState = self.server.state
        if state.mode == "disconnect":
            body = self._read_body()
            self._record(body)
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.connection.close()
            except OSError:
                pass
            return

        body = self._read_body()
        self._record(body)

        if state.mode == "hold":
            state.release.wait(timeout=float(state.extra.get("hold_seconds", 30)))
            self._send(200, b'{"status":"late"}')
            return

        if state.mode == "ok_200":
            self._send(200, b'{"status":"accepted","completed":false}')
            return
        if state.mode == "ok_202_done_claim":
            payload = {
                "status": "done",
                "completed": True,
                "message": "finished",
            }
            self._send(202, json.dumps(payload).encode("utf-8"))
            return
        if state.mode == "http_401":
            self._send(401, b'{"error":"unauthorized"}')
            return
        if state.mode == "http_500_reflect":
            reflected = {
                "error": "boom",
                "authorization": self.headers.get("Authorization"),
            }
            self._send(500, json.dumps(reflected).encode("utf-8"))
            return
        if state.mode in ("redirect_302", "redirect_307"):
            code = 302 if state.mode == "redirect_302" else 307
            location = state.extra.get("location")
            self.send_response(code)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        self._send(500, b'{"error":"unknown-mode"}')

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


class LoopbackServer:
    def __init__(self, mode: str, extra: Optional[Dict[str, Any]] = None) -> None:
        self.state = LoopbackState(mode, extra)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.state = self.state  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    @property
    def origin(self) -> str:
        return "http://127.0.0.1:%d" % self.port

    def start(self) -> "LoopbackServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.state.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def __enter__(self) -> "LoopbackServer":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
