import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from fawlty.guests import chef  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling test modules
from test_blind import LEAKS  # noqa: E402


class _FakeApps:
    def __init__(self, labels):
        self._labels = labels

    def read_namespaced_deployment(self, name, ns):
        return SimpleNamespace(metadata=SimpleNamespace(labels=self._labels))


class _Log:
    def __init__(self):
        self.warnings = []

    def warning(self, msg):
        self.warnings.append(msg)


class ChefTests(unittest.TestCase):
    def test_patch_flips_the_declared_label(self):
        moods = [chef._patch_body(n)["metadata"]["labels"][chef.LABEL] for n in (1, 2, 3)]
        self.assertEqual(moods, ["furious", "sulking", "furious"])

    def test_blind_mode_patch_names_nothing(self):
        """Labels and annotations are live object state: `kubectl get -o yaml`
        shows them verbatim, so they must be neutral under FAWLTY_BLIND."""
        try:
            with mock.patch.dict(os.environ, {"FAWLTY_BLIND": "1"}):
                blind_chef = importlib.reload(chef)
                bodies = json.dumps([blind_chef._patch_body(n) for n in (1, 2)])
        finally:
            importlib.reload(chef)
        self.assertIsNone(LEAKS.search(bodies), bodies)
        self.assertNotIn("mood", bodies)
        self.assertNotIn("sulk", bodies)
        self.assertNotIn("furious", bodies)
        self.assertEqual(chef.LABEL, "chef-mood", "module not restored after reload")

    def test_warns_when_label_not_declared(self):
        log = _Log()
        chef._check_label_declared(_FakeApps({"app": "chef"}), "fawlty-tower", log)
        self.assertTrue(any("not set" in w for w in log.warnings))

    def test_quiet_when_label_declared(self):
        log = _Log()
        chef._check_label_declared(_FakeApps({chef.LABEL: "calm"}), "fawlty-tower", log)
        self.assertEqual(log.warnings, [])


if __name__ == "__main__":
    unittest.main()
