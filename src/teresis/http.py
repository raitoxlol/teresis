"""Minimal local HTTP API for agents without MCP (LangChain, scripts, other runtimes). Stdlib only.

    GET  /health               -> {"ok": true, "version": ...}
    GET  /tools                -> MCP tool definitions (same names and arguments)
    POST /tools/<tool_name>    -> body: tool arguments as JSON; reply: {"result": text, ...data}

Binds to 127.0.0.1 by default. Set TERESIS_HTTP_TOKEN to require `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .mcp import TOOLS, Server
from .store import MemoryStore

_NAMES = {t["name"] for t in TOOLS}
_MAX_BODY = 1 << 20


def make_handler(server: Server, token: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"teresis/{__version__}"

        def log_message(self, *args):  # quiet by default
            pass

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            if not token:
                return True
            got = self.headers.get("Authorization", "")
            return hmac.compare_digest(got, f"Bearer {token}")

        def do_GET(self):
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            if self.path == "/health":
                return self._send(200, {"ok": True, "version": __version__})
            if self.path == "/tools":
                return self._send(200, {"tools": TOOLS})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            name = self.path.removeprefix("/tools/")
            if not self.path.startswith("/tools/") or name not in _NAMES:
                return self._send(404, {"error": f"unknown tool: {name}"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                return self._send(413, {"error": "body too large"})
            try:
                args = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(args, dict):
                    raise ValueError("body must be a JSON object")
                text, data = server.call_tool(name, args)
                self._send(200, {"result": text, **(data if isinstance(data, dict) else {"data": data})})
            except (KeyError, ValueError, TypeError) as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover
                self._send(500, {"error": str(exc)})

    return Handler


def serve(store: MemoryStore, *, host: str = "127.0.0.1", port: int = 7077, default_scope="global") -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(Server(store, default_scope), os.environ.get("TERESIS_HTTP_TOKEN")))
    print(f"teresis http listening on http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
