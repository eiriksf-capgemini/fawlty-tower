"""The victim: a perfectly innocent little web server.

Does nothing wrong on its own. It exists to be a target — a stable HTTP
endpoint for Chaos Mesh (or any fault injector) to kill, stress, delay, or cut
off, and a thing behind an Ingress to actually look at. Serves a tiny status
page and a /healthz the readiness probe can hit.
"""
from __future__ import annotations

import http.server
import os
import threading

from fawlty import blind, common

PORT = int(os.environ.get("FAWLTY_PORT", "8080"))


class _Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, body: str) -> None:
        payload = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        if self.path == "/healthz":
            self._send(200, "ok\n")
        else:
            self._send(
                200,
                blind.text(
                    "Fawlty Towers reception. The victim is in and feeling fine.\n"
                    "Check in a guest to ruin its day.\n",
                    "ok\n",
                ),
            )

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib hook
        common.get_logger().info("request " + (fmt % args))


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    server = common.ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    log.info(f"victim listening on :{PORT}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stop.wait()
    log.info("victim shutting down")
    server.shutdown()
