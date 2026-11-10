"""The pip-runner service (docs/DESIGN-modules.md, "The sandbox"): `python -m app.runner_service`.

It runs in its own container with no network at all, read-only and unprivileged, answering on a Unix socket in a volume it shares with
the engine (RUNNER_SOCKET), or on a TCP port for development (RUNNER_PORT). It does one thing: POST /run with
{"source", "hook", "ctx"} runs that hook in a fresh, limited subprocess (sandbox.py) and answers with its JSON. GET /healthz says it's up.
Stdlib only, so the runner needs nothing the engine doesn't.
"""
import asyncio
import json
import os
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import sandbox

REQUEST_MAX = sandbox.SOURCE_MAX + 200_000            # source plus a generous ctx


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"ok": True}) if self.path == "/healthz" else self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, {"error": "not found"})
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 < size <= REQUEST_MAX:
            return self._send(413, {"ok": False, "error": "request too large"})
        try:
            req = json.loads(self.rfile.read(size))
            source, hook, ctx = req["source"], req["hook"], req["ctx"]
            if not isinstance(source, str) or not isinstance(hook, str) or not hook.startswith("on_") or not isinstance(ctx, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self._send(400, {"ok": False, "error": "expected {source, hook, ctx}"})
        self._send(200, asyncio.run(sandbox.run(source, hook, ctx)))

    def log_message(self, *args):                       # quiet: the engine keeps the record of every call
        pass


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve_socket(path: str) -> UnixServer:
    """A server on a Unix socket anyone sharing the volume may connect to (the engine runs as another user)."""
    if os.path.exists(path):
        os.unlink(path)
    srv = UnixServer(path, Handler)
    os.chmod(path, 0o666)
    return srv


def main() -> None:
    path = os.environ.get("RUNNER_SOCKET")
    srv = serve_socket(path) if path else ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("RUNNER_PORT") or 8100)), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
