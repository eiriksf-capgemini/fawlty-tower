"""The guest list lives in several places; keep them in lock-step.

dispatch.GUESTS (what the image can run), the `fawlty` CLI's tier arrays
(what you can check in), scenarios.json (what can be graded), the guest
modules themselves, blind.py's persona scrubber and test_blind's leak oracle.
Adding a guest to one and forgetting another used to fail silently: an
ungradable guest, one the CLI refuses to check in, or a persona name that
walks straight through blind mode.
"""
import importlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from fawlty import blind, dispatch  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling test modules
from test_blind import LEAKS  # noqa: E402


def _cli_array(name):
    text = (ROOT / "fawlty").read_text(encoding="utf-8")
    m = re.search(rf"^{name}=\(([^)]*)\)", text, re.MULTILINE)
    assert m, f"{name}=(...) not found in ./fawlty"
    return m.group(1).split()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.default = _cli_array("DEFAULT_GUESTS")
        self.node = _cli_array("NODE_GUESTS")
        with (ROOT / "scenarios" / "scenarios.json").open(encoding="utf-8") as fh:
            self.scenarios = json.load(fh)["guests"]

    def test_cli_matches_dispatch(self):
        self.assertEqual(sorted(self.default + self.node), sorted(dispatch.GUESTS))
        self.assertFalse(set(self.default) & set(self.node), "guest in both tiers")

    def test_scenarios_match_dispatch(self):
        self.assertEqual(sorted(self.scenarios), sorted(dispatch.GUESTS))

    def test_tiers_agree(self):
        for g in self.default:
            self.assertEqual(self.scenarios[g]["tier"], "default", g)
        for g in self.node:
            self.assertEqual(self.scenarios[g]["tier"], "node", g)

    def test_blind_scrubber_and_leak_oracle_know_every_guest(self):
        for g in dispatch.GUESTS:
            self.assertEqual(blind.scrub(f"hello {g} here"), "hello service here", g)
            self.assertIsNotNone(LEAKS.search(g), f"test_blind.LEAKS does not match {g!r}")

    def test_every_guest_module_exposes_run(self):
        for name, path in dispatch.GUESTS.items():
            self.assertEqual(path, f"fawlty.guests.{name}")
            module = importlib.import_module(path)
            self.assertTrue(callable(getattr(module, "run", None)), f"{path}.run missing")


class DispatchTests(unittest.TestCase):
    def test_unknown_guest_exits_2(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"FAWLTY_GUEST": "nobody"}), \
             mock.patch.object(dispatch.common, "install_signal_handlers"):
            self.assertEqual(dispatch.main(), 2)

    def test_guest_exception_exits_1(self):
        import os
        import types
        from unittest import mock
        boom = types.ModuleType("boom")

        def run():
            raise RuntimeError("kaboom")

        boom.run = run
        with mock.patch.dict(os.environ, {"FAWLTY_GUEST": "basil"}), \
             mock.patch.object(dispatch.common, "install_signal_handlers"), \
             mock.patch.object(dispatch.importlib, "import_module", return_value=boom):
            self.assertEqual(dispatch.main(), 1)


if __name__ == "__main__":
    unittest.main()
