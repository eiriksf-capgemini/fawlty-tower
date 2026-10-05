import os
import socket
import subprocess
import sys
import tempfile
import time
import signal
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _env(**kw):
    return dict(os.environ, PYTHONPATH=str(SRC), **kw)


class NodeTierTests(unittest.TestCase):
    def test_squatter_exits_nonzero_when_port_is_taken(self):
        holder = socket.socket()
        holder.bind(("0.0.0.0", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        try:
            out = subprocess.run(
                [sys.executable, "-m", "fawlty.dispatch"],
                env=_env(FAWLTY_GUEST="squatter", FAWLTY_SQUAT_PORT=str(port)),
                capture_output=True, text=True, timeout=10,
            )
        finally:
            holder.close()
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("could not bind port", out.stdout)

    def test_diskfill_ballast_is_incompressible_undedupable_and_cleaned_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.Popen(
                [sys.executable, "-m", "fawlty.dispatch"],
                env=_env(FAWLTY_GUEST="diskfill", FAWLTY_FILL_DIR=tmp, FAWLTY_FILL_MB="32"),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            ballast = Path(tmp) / "fawlty-ballast.bin"
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not (ballast.exists() and ballast.stat().st_size >= 32 << 20):
                time.sleep(0.1)
            data = ballast.read_bytes()
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
            head = data[: 1 << 20]
            self.assertGreater(len(set(head)), 200, "ballast looks compressible (mostly one byte value)")
            # Two 16MiB chunks; a repeated chunk would dedup to one on btrfs/ZFS.
            self.assertNotEqual(data[: 16 << 20], data[16 << 20: 32 << 20], "ballast repeats the same chunk")
            self.assertFalse(ballast.exists(), "ballast not removed on graceful stop")


if __name__ == "__main__":
    unittest.main()
