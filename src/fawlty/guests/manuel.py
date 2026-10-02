"""Manuel: "I know nothing." Flapping readiness.

Serves /healthz, but the answer flips between healthy (200) and "I know
nothing!" (503) on a cycle. Against a normal readiness probe this makes the pod
flap Ready -> NotReady -> Ready, which pulls its endpoint in and out of the
Service and produces the maddening intermittent-availability signal where a
service is "up" but only sometimes.
"""
from __future__ import annotations

import http.server
import os
import threading
import time

from fawlty import common

PORT = int(os.environ.get("FAWLTY_PORT", "8080"))
# Seconds healthy, then seconds unhealthy, repeating.
HEALTHY_S = float(os.environ.get("FAWLTY_HEALTHY_S", "20.0"))
UNHEALTHY_S = float(os.environ.get("FAWLTY_UNHEALTHY_S", "20.0"))

_start = time.monotonic()


def _is_healthy() -> bool:
    phase = (time.monotonic() - _start) % (HEALTHY_S + UNHEALTHY_S)
    return phase < HEALTHY_S


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        healthy = _is_healthy()
        if self.path == "/healthz":
            code, msg = (200, "sí, all good\n") if healthy else (503, "I know nothing!\n")
        else:
            code, msg = (200, "Manuel at your service\n") if healthy else (503, "Qué?\n")
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib hook
        pass


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    server = common.ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    log.info(f"Manuel is on the desk on :{PORT} (healthy {HEALTHY_S}s / confused {UNHEALTHY_S}s)")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    while not stop.is_set():
        log.warning("Manuel says: " + ("sí, all good" if _is_healthy() else "I know NOTHING"))
        stop.wait(10.0)
    server.shutdown()
