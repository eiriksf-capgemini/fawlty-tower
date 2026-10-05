"""squatter (NODE TIER, GATED): sits on a host port.

With hostNetwork, binds a port on the node (default 80) and holds it, so it
contends with whatever else wants that port — on this stack, the ingress-nginx
controller. Expect ingress disruption while the squatter is checked in. Gated
off by default; the node-tier Deployment sets hostNetwork and the port.

If the port is already taken, the squatter exits non-zero instead of sitting
there Running and doing nothing. A silent idle pod would make the scenario's
ground truth ("host port conflict") false; a crash-looping pod whose logs say
"Address already in use" is the real, diagnosable symptom of a port conflict.
"""
from __future__ import annotations

import os
import socket
import sys

from fawlty import common

PORT = int(os.environ.get("FAWLTY_SQUAT_PORT", "80"))


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", PORT))
        sock.listen(16)
        log.warning(f"squatting host port {PORT}; ingress on this port will contend with us")
    except OSError as exc:
        log.error(f"could not bind port {PORT} (something already holds it): {exc}")
        sock.close()
        sys.exit(1)

    sock.settimeout(1.0)
    while not stop.is_set():
        try:
            conn, addr = sock.accept()
            log.warning(f"accepted and dropped a connection from {addr}")
            conn.close()
        except socket.timeout:
            continue
        except OSError:
            break
    sock.close()
    log.info("squatter released the port")
