import os
import subprocess
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _run(guest, seconds, **env):
    full = dict(os.environ, PYTHONPATH=str(SRC), FAWLTY_GUEST=guest, **env)
    try:
        out = subprocess.run([sys.executable, "-m", "fawlty.dispatch"], env=full,
                             capture_output=True, text=True, timeout=seconds)
        return out.stdout
    except subprocess.TimeoutExpired as exc:
        return exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")


class SelfBoundTests(unittest.TestCase):
    def test_sybil_stops_at_self_cap(self):
        out = _run("sybil", 3, FAWLTY_LEAK_CHUNK_MB="4", FAWLTY_LEAK_INTERVAL_S="0.05", FAWLTY_MAX_MB="16")
        self.assertIn("self-cap at 16MiB", out)
        self.assertNotIn("hoarding 20MiB", out)

    def test_polly_rate_is_configurable(self):
        slow = _run("polly", 1.5, FAWLTY_LOG_RATE="5").count("[seq=")
        fast = _run("polly", 1.5, FAWLTY_LOG_RATE="200").count("[seq=")
        self.assertLess(slow, 15)
        self.assertGreater(fast, 5 * slow)


if __name__ == "__main__":
    unittest.main()
