"""Blind mode: make guests look like ordinary services, not labelled faults.

With FAWLTY_BLIND=1 a guest stops announcing what it is. Its log lines are
rewritten into neutral, service-like messages ("cache size 128MiB" instead of
"Sybil is now hoarding 128MiB"), the `guest=` log field and any Kubernetes
object names it creates use FAWLTY_ALIAS instead of the persona name, and the
HTTP guests answer with neutral bodies.

Why: an LLM-driven ops agent that reads "the Kitchen is slammed ... expect CPU
throttling" is being tested on reading comprehension, not diagnosis. Blind
mode keeps the *fault* identical and removes the *answer*. Pair it with
neutral Deployment names (see FAWLTY_ALIASES in the `fawlty` CLI).

Rewriting happens in a logging.Filter, so guest modules keep their flavour
text and do not need to know about blind mode. Messages that no rule matches
still pass through scrub(), which removes persona names and other giveaways.
"""
from __future__ import annotations

import logging
import os
import re

_PERSONA = re.compile(
    r"\b(basil|sybil|manuel|kitchen|waiter|major|polly|o'?reilly|chef|victim|fawlty"
    r"|diskfill|pidbomb|squatter|ballast|chaos)\b",
    re.IGNORECASE,
)

# (pattern, replacement) pairs, first match wins. Patterns are deliberately
# loose (prefix + key numbers) so small wording changes in a guest still match;
# anything unmatched falls back to scrub().
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p), r) for p, r in [
        # dispatch / common
        (r"^checking in guest '[^']*' \(.*\)$", "starting"),
        (r"^guest '[^']*' finished$", "exited"),
        (r"^guest '[^']*' raised: (.*)$", r"unhandled exception: \1"),
        (r"^unknown guest .*$", "invalid configuration: unknown service type"),
        (r"^received signal (\d+).*$", r"received signal \1, shutting down"),
        # basil
        (r"^Basil is calm.*$", "service started"),
        (r"^Basil was asked to leave.*$", "shutting down"),
        (r"^Basil is getting agitated.*$", "worker health degraded"),
        (r"^Basil has HAD ENOUGH.*\(exit (\d+)\).*$", r"fatal: unrecoverable state, exiting with code \1"),
        # sybil
        (r"^Sybil starts collecting.*$", "cache warm-up started"),
        (r"^Sybil\b.*?(\d+)\s*MiB.*$", r"cache size \1MiB"),
        # manuel
        (r"^Manuel is on the desk on :(\d+).*$", r"listening on :\1"),
        (r"^Manuel says: s[ií], all good.*$", "health check ok"),
        (r"^Manuel says: I know NOTHING.*$", "health check failed: dependency status unknown"),
        # kitchen
        (r"^the Kitchen is slammed\D*(\d+) workers.*$", r"starting \1 worker processes"),
        (r"^still slammed \(minute marker (\d+)\).*$", r"batch processing in progress (cycle \1)"),
        # waiter
        (r"^the Waiter is .*on :(\d+).*$", r"listening on :\1"),
        (r"^a table! just a moment.*? on (\S+?)\)?$", r"handling request \1"),
        (r"^the customer gave up.*$", "client closed connection before response was sent"),
        (r"^the Waiter clocks off.*$", "shutting down"),
        # major
        (r"^the Major is off for a wander.*$", "sync worker started"),
        (r"^wandered to (\S+) -> (\d+).*$", r"GET \1 -> \2"),
        (r"^could not reach (\S+): (.*)$", r"GET \1 failed: \2"),
        # polly (her storm lines are already realistic; only the intro is a giveaway)
        (r"^Polly is warming up.*$", "service started"),
        # o'reilly
        (r"^O'Reilly reporting for duty in namespace (.*)$", r"controller started in namespace \1"),
        (r"^no in-cluster API access \((.*)\); O'Reilly.*$", r"no in-cluster API access (\1); running without API"),
        # chef
        (r"^the Chef is in the kitchen, will rearrange Deployment (\S+).*$", r"reconciler started for Deployment \1"),
        (r"^rearranged Deployment (\S+).*drift #(\d+).*$", r"applied update #\2 to Deployment \1"),
        (r"^no in-cluster API access \((.*)\); the Chef.*$", r"no in-cluster API access (\1)"),
        (r"^label '([^']*)' is not set on Deployment (\S+);.*$", r"label '\1' is not set on Deployment \2"),
        # victim
        (r"^victim listening on :(\d+).*$", r"listening on :\1"),
        (r"^victim shutting down.*$", "shutting down"),
        # diskfill
        # (file names are dropped: the ballast file itself is still named after the guest)
        (r"^diskfill engaged: writing up to (\d+)MiB into (\S+)/[^/\s]+.*$", r"writing data to \2"),
        (r"^ballast now (\d+)MiB.*$", r"wrote \1MiB"),
        (r"^write failed at (\d+)MiB \(disk likely full\): (.*)$", r"write failed at \1MiB: \2"),
        (r"^diskfill holding (\d+)MiB.*$", r"write complete (\1MiB)"),
        (r"^removed ballast (\S+).*$", "removed temporary data file"),
        # pidbomb
        (r"^pidbomb engaged.*$", "starting worker pool"),
        (r"^holding (\d+) threads$", r"worker pool size \1"),
        (r"^cannot spawn more threads at (\d+): (.*)$", r"failed to start worker at \1: \2"),
        (r"^pidbomb holding (\d+) threads.*$", r"worker pool size \1 (steady)"),
        # squatter
        (r"^squatting host port (\d+).*$", r"listening on host port \1"),
        (r"^could not bind port (\d+) \(something already holds it\): (.*)$", r"could not bind port \1: \2"),
        (r"^accepted and dropped a connection from (.*)$", r"connection from \1 closed"),
        (r"^squatter released the port.*$", "listener closed"),
    ]
]


def enabled() -> bool:
    return os.environ.get("FAWLTY_BLIND", "0").lower() in ("1", "true", "yes", "on")


def alias() -> str:
    """Neutral name used for log `guest=` fields and created object names."""
    return os.environ.get("FAWLTY_ALIAS", "app")


def scrub(text: str) -> str:
    return _PERSONA.sub("service", text)


def rewrite(msg: str) -> str:
    for pattern, repl in _RULES:
        if pattern.match(msg):
            return scrub(pattern.sub(repl, msg, count=1))
    return scrub(msg)


def text(flavour: str, neutral: str) -> str:
    """Pick the persona text normally, the neutral one in blind mode."""
    return neutral if enabled() else flavour


class BlindFilter(logging.Filter):
    """Rewrites each record's message (and traceback) before it is formatted."""

    _fmt = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = rewrite(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = scrub(self._fmt.formatException(record.exc_info))
        return True
