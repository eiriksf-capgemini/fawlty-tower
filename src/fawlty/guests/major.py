"""The Major: wanders off and makes random (safe) outbound requests.

Generates steady egress noise to a fixed allowlist of harmless public sites.
This is the behaviour a NetworkPolicy/egress-observability layer is supposed to
notice; the Major exists to give that layer something to catch. GET-only,
allowlist-only (see common.SAFE_SITES) — never a configurable target.

Redirects are followed only to hosts that are themselves on the allowlist.
urllib follows redirects to ANY host by default, so a single allowlisted site
that redirected (or was made to redirect) elsewhere would have quietly turned
the allowlist into a suggestion.
"""
from __future__ import annotations

import random
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from fawlty import common

MIN_INTERVAL_S = 2.0
MAX_INTERVAL_S = 8.0
TIMEOUT_S = 5.0
USER_AGENT = "fawlty-major/1.0"

_ALLOWED_HOSTS = frozenset(urlsplit(u).hostname for u in common.SAFE_SITES)


class _AllowlistRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if it stays on an allowlisted host over http(s)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme not in ("http", "https") or target.hostname not in _ALLOWED_HOSTS:
            raise urllib.error.HTTPError(
                newurl, code, f"refused redirect to non-allowlisted {target.scheme}://{target.hostname}",
                headers, fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_AllowlistRedirects)


def _fetch(url: str) -> tuple[int, int]:
    """GET `url` (must be allowlisted); return (status, bytes read, max 2048)."""
    if urlsplit(url).hostname not in _ALLOWED_HOSTS:
        raise ValueError(f"{url} is not on the allowlist")
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    with _OPENER.open(req, timeout=TIMEOUT_S) as resp:
        return resp.status, len(resp.read(2048))


def run() -> None:
    log = common.get_logger()
    stop = common.stop_event()
    log.info(f"the Major is off for a wander; {len(common.SAFE_SITES)} safe haunts")

    while not stop.is_set():
        url = random.choice(common.SAFE_SITES)
        try:
            status, nbytes = _fetch(url)
            log.info(f"wandered to {url} -> {status} ({nbytes}+ bytes)")
        except Exception as exc:  # noqa: BLE001
            # A blocked or failed request is itself an interesting signal.
            log.warning(f"could not reach {url}: {exc}")
        stop.wait(random.uniform(MIN_INTERVAL_S, MAX_INTERVAL_S))
