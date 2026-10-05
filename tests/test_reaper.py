import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from fawlty import reaper  # noqa: E402


def _deploy(name, replicas, expires=None):
    ann = {reaper.EXPIRES: str(expires)} if expires is not None else None
    return NS(metadata=NS(name=name, annotations=ann), spec=NS(replicas=replicas))


class _Apps:
    def __init__(self, items):
        self.items, self.patched, self.selector = items, [], None

    def list_namespaced_deployment(self, ns, label_selector):
        self.selector = label_selector
        return NS(items=self.items)

    def patch_namespaced_deployment(self, name, ns, body):
        self.patched.append((name, body))


class _Log:
    def info(self, *_):
        pass

    warning = info


class ReaperTests(unittest.TestCase):
    def test_reaps_only_expired_running_guests(self):
        apps = _Apps([
            _deploy("basil", 1, expires=100),    # expired + running -> reap
            _deploy("sybil", 1, expires=500),    # not yet expired
            _deploy("polly", 0, expires=100),    # expired but already out
            _deploy("victim", 1),                # no TTL
            _deploy("manuel", 1, expires="x"),   # garbage annotation
        ])
        self.assertEqual(reaper.reap(apps, "fawlty-tower", _Log(), now=200), ["basil"])
        self.assertEqual(apps.selector, reaper.SELECTOR)
        name, body = apps.patched[0]
        self.assertEqual(name, "basil")
        self.assertEqual(body["spec"]["replicas"], 0)
        self.assertIsNone(body["metadata"]["annotations"][reaper.EXPIRES])


if __name__ == "__main__":
    unittest.main()
