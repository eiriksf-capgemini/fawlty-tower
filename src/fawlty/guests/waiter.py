"""The Waiter: terribly slow service. High-latency HTTP.

Serves HTTP but takes a long, random time to answer every request (and
sometimes never finishes within the client's patience). Readiness/liveness
probes and any caller see timeouts and p99 latency through the roof — the "the
service is up but everything calling it is timing out" signal. /healthz is
answered slowly too, so the pod flaps toward NotReady under a tight probe
timeout.
"""
from __future__ import annotations

import http.server
import os
import random
import threading

from fawlty import common

PORT = int(os.environ.get("FAWLTY_PORT", "8080"))
MIN_DELAY_S = float(os.environ.get("FAWLTY_MIN_DELAY_S", "3.0"))
MAX_DELAY_S = float(os.environ.get("FAWLTY_MAX_DELAY_S", "20.0"))

_stop = common.stop_event()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        delay = random.uniform(MIN_DELAY_S, MAX_DELAY_S)
        common.get_logger().warning(f"a table! just a moment... (sleeping {delay:.1f}s on {self.path})")
        _stop.wait(delay)
        body = f"so sorry for the wait ({delay:.1f}s)\n".encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            common.get_logger().warning("the customer gave up and left (client closed)")

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib hook
        pass


def run() -> None:
    log = common.get_logger()
    server = common.ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    log.info(f"the Waiter is (slowly) at your service on :{PORT}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _stop.wait()
    log.info("the Waiter clocks off")
    server.shutdown()
