"""Shared helpers for every Fawlty Towers guest.

A "guest" is one fault persona. They all run from the same image; the
FAWLTY_GUEST env var picks which one runs (see dispatch.py). This module holds
the few things every guest needs: a noisy-but-structured logger, a graceful
SIGTERM path so `kubectl delete pod` / scale-down is clean, the egress
allowlist the Major is restricted to, and a couple of small helpers (namespace
detection and a threaded HTTP server) shared by more than one guest.
"""
from __future__ import annotations

import http.server
import logging
import os
import signal
import socketserver
import sys
import threading

from fawlty import blind

# A hard allowlist of safe, well-known, read-only endpoints. The Major only
# ever issues GETs against these. This is deliberately NOT configurable from
# the environment: a chaos workload that can be pointed at an arbitrary host
# is a half-built SSRF gadget, and the whole point here is to be annoying, not
# dangerous. Add hosts here in code, in a reviewed change, or not at all.
SAFE_SITES: tuple[str, ...] = (
    "https://example.com",
    "https://www.example.org",
    "http://neverssl.com",  # plain HTTP by design: neverssl does not serve HTTPS
    "https://httpbingo.org/get",
    "https://www.wikipedia.org",
    "https://www.cloudflare.com",
    "https://postman-echo.com/get",
)

# Set once a SIGTERM/SIGINT arrives so run-loops can exit between iterations.
_stop = threading.Event()


def guest_name() -> str:
    return os.environ.get("FAWLTY_GUEST", "unknown")


def get_logger() -> logging.Logger:
    """A logger that writes single-line, parseable records to stdout.

    Format is deliberately ops-dashboard-shaped (level + logger + message) so
    the noise a guest makes looks like a real service misbehaving, not like
    print() debugging.

    In blind mode (FAWLTY_BLIND=1) the logger is named after FAWLTY_ALIAS and
    every record is rewritten into neutral text; see fawlty.blind.
    """
    logger = logging.getLogger(blind.alias() if blind.enabled() else guest_name())
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    if blind.enabled():
        handler.addFilter(blind.BlindFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s level=%(levelname)s guest=%(name)s pid=%(process)d msg=%(message)s"
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger


def install_signal_handlers() -> threading.Event:
    """Wire SIGTERM/SIGINT to the shared stop event and return it.

    Guests should loop `while not stop.is_set():` and use `stop.wait(seconds)`
    instead of time.sleep, so a terminating pod exits in milliseconds rather
    than hanging until the kubelet's grace period runs out.
    """

    def _handle(signum, _frame):
        get_logger().info(f"received signal {signum}, shutting down the guest")
        _stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    return _stop


def stop_event() -> threading.Event:
    return _stop


def namespace() -> str:
    """The pod's own namespace.

    Reads the service-account namespace file the kubelet mounts into every pod,
    falls back to the POD_NAMESPACE env var, then to "fawlty-tower" when running
    outside a cluster. Used by the guests that talk to the Kubernetes API.
    """
    try:
        with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as fh:
            return fh.read().strip()
    except OSError:
        return os.environ.get("POD_NAMESPACE", "fawlty-tower")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """An HTTP server that handles each request on its own daemon thread.

    daemon_threads = True means in-flight requests never hold up shutdown, so a
    terminating pod exits promptly. Shared by the HTTP-serving guests.
    """

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        # socketserver's default prints the traceback straight to stderr,
        # bypassing the logger (and blind mode's filter). Log it instead.
        get_logger().exception(f"error while handling a request from {client_address[0]}")
