"""Blind mode must not leak the persona or the fault in logs or HTTP bodies.

Runs every guest for real (briefly, with tiny limits, no cluster) under
FAWLTY_BLIND=1 and scans everything it prints. New log lines added to a guest
are covered automatically: if a rewrite rule is missing, scrub() still has to
keep the persona names out, and this test fails if it does not.
"""
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from fawlty import blind  # noqa: E402
from fawlty.dispatch import GUESTS  # noqa: E402

# Words that give the game away. Persona names, plus fault vocabulary that a
# real service would not print about itself.
LEAKS = re.compile(
    r"basil|sybil|manuel|kitchen|waiter|\bmajor\b|polly|o'?reilly|\bchef\b|victim|fawlty|"
    r"diskfill|pidbomb|squatter|ballast|hoard|slammed|throttl|storm|drift|chaos|"
    r"pure noise|agitated|squat|wander|know nothing|disk likely full",
    re.IGNORECASE,
)

PORTS = {"manuel": 18081, "waiter": 18082, "victim": 18083, "squatter": 18084}


def _env(guest, tmp):
    env = dict(os.environ, PYTHONPATH=str(SRC), FAWLTY_GUEST=guest, FAWLTY_BLIND="1",
               FAWLTY_ALIAS="svc-a7f3", FAWLTY_MIN_UPTIME_S="0.1", FAWLTY_MAX_UPTIME_S="0.2",
               FAWLTY_LEAK_INTERVAL_S="0.2", FAWLTY_CPU_WORKERS="1", FAWLTY_MIN_DELAY_S="0.05",
               FAWLTY_MAX_DELAY_S="0.1", FAWLTY_FILL_DIR=tmp, FAWLTY_FILL_MB="32",
               FAWLTY_PID_MAX="150", FAWLTY_HEALTHY_S="0.3", FAWLTY_UNHEALTHY_S="0.3")
    if guest in PORTS:
        env["FAWLTY_PORT"] = env["FAWLTY_SQUAT_PORT"] = str(PORTS[guest])
    return env


class BlindModeTests(unittest.TestCase):
    def test_rewrite_rules_are_clean(self):
        for pattern, repl in blind._RULES:
            self.assertIsNone(LEAKS.search(repl), f"rule {pattern.pattern!r} leaks: {repl!r}")

    def test_scrub_fallback(self):
        self.assertEqual(blind.rewrite("Sybil did something new"), "service did something new")

    def test_text_helper(self):
        os.environ["FAWLTY_BLIND"] = "1"
        try:
            self.assertEqual(blind.text("flavour", "neutral"), "neutral")
        finally:
            del os.environ["FAWLTY_BLIND"]
        self.assertEqual(blind.text("flavour", "neutral"), "flavour")

    def test_every_guest_runs_blind_without_leaking(self):
        with tempfile.TemporaryDirectory() as tmp:
            procs = {}
            for guest in GUESTS:
                procs[guest] = subprocess.Popen(
                    [sys.executable, "-m", "fawlty.dispatch"], env=_env(guest, tmp),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
            time.sleep(2.5)
            bodies = {}
            for guest in ("manuel", "waiter", "victim"):
                for path in ("/", "/healthz"):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{PORTS[guest]}{path}", timeout=3) as r:
                            bodies[f"{guest}{path}"] = r.read().decode()
                    except urllib.error.HTTPError as e:
                        bodies[f"{guest}{path}"] = e.read().decode()
            for p in procs.values():
                if p.poll() is None:
                    p.send_signal(signal.SIGTERM)
            outputs = {g: p.communicate(timeout=10)[0] for g, p in procs.items()}

        for guest, out in outputs.items():
            self.assertTrue(out.strip(), f"{guest} printed nothing")
            self.assertNotIn(f"guest={guest} ", out)
            self.assertIn("guest=svc-a7f3 ", out)
            m = LEAKS.search(out)
            self.assertIsNone(m, f"{guest} leaked {m and m.group(0)!r}:\n{out}")
        for where, body in bodies.items():
            self.assertIsNone(LEAKS.search(body), f"{where} body leaks: {body!r}")


if __name__ == "__main__":
    unittest.main()
