"""The Kitchen must burn more than one core when given more than one worker.

Regression test for the GIL bug: busy *threads* only ever used ~1 core, so a
CPU limit above 1 was never reached and no CFS throttling appeared.
"""
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


@unittest.skipUnless(hasattr(os, "wait4"), "needs os.wait4 (Linux/macOS)")
@unittest.skipUnless((os.cpu_count() or 1) >= 2, "needs at least 2 CPUs")
class KitchenTests(unittest.TestCase):
    def test_uses_more_than_one_core_and_stops_on_sigterm(self):
        env = dict(os.environ, FAWLTY_GUEST="kitchen", FAWLTY_CPU_WORKERS="2", PYTHONPATH=str(SRC))
        proc = subprocess.Popen(
            [sys.executable, "-m", "fawlty.dispatch"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        start = time.monotonic()
        time.sleep(3.0)
        proc.send_signal(signal.SIGTERM)
        # wait4 reports CPU of the guest *and* the workers it joined.
        _, status, usage = os.wait4(proc.pid, 0)
        wall = time.monotonic() - start
        proc.returncode = os.waitstatus_to_exitcode(status)

        self.assertEqual(proc.returncode, 0)
        self.assertLess(wall, 3.0 + 5.0, "kitchen did not stop promptly on SIGTERM")
        cores = (usage.ru_utime + usage.ru_stime) / wall
        self.assertGreater(cores, 1.3, f"kitchen only used {cores:.2f} cores with 2 workers")

    def test_workers_do_not_outlive_a_sigkilled_parent(self):
        """No PID namespace here, exactly like hostPID or --grace-period=0: a hard
        kill of the parent must not leave busy-loops behind for init to inherit."""
        env = dict(os.environ, FAWLTY_GUEST="kitchen", FAWLTY_CPU_WORKERS="2", PYTHONPATH=str(SRC))
        proc = subprocess.Popen(
            [sys.executable, "-m", "fawlty.dispatch"], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        time.sleep(2.0)  # let the workers start
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)  # workers inherited the parent's process group
            except ProcessLookupError:
                return
            time.sleep(0.1)
        os.killpg(proc.pid, signal.SIGKILL)
        self.fail("kitchen workers survived SIGKILL of their parent")


if __name__ == "__main__":
    unittest.main()
