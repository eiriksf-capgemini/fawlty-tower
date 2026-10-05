"""O'Reilly's Jobs must be PSA-restricted compliant and Events must point at the real pod.

The kubernetes client is not a test dependency, so a tiny stand-in module
records the keyword arguments each model class was built with.
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class _Model:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_kubernetes():
    client = types.ModuleType("kubernetes.client")
    for name in ("CoreV1Event", "V1ObjectMeta", "V1ObjectReference", "V1Job", "V1JobSpec",
                 "V1PodTemplateSpec", "V1PodSpec", "V1Container", "V1ResourceRequirements",
                 "V1PodSecurityContext", "V1SecurityContext", "V1Capabilities", "V1SeccompProfile"):
        setattr(client, name, type(name, (_Model,), {}))
    pkg = types.ModuleType("kubernetes")
    pkg.client = client
    pkg.config = types.ModuleType("kubernetes.config")
    return {"kubernetes": pkg, "kubernetes.client": client, "kubernetes.config": pkg.config}


class _Recorder:
    def __init__(self):
        self.created = []

    def create_namespaced_job(self, ns, body):
        self.created.append(body)

    def create_namespaced_event(self, ns, body):
        self.created.append(body)


class _Log:
    def warning(self, *_):
        pass

    error = warning


class OReillyTests(unittest.TestCase):
    def setUp(self):
        self.modules = mock.patch.dict(sys.modules, _fake_kubernetes())
        self.modules.start()
        from fawlty.guests import oreilly
        self.oreilly = oreilly

    def tearDown(self):
        self.modules.stop()

    def test_job_is_psa_restricted(self):
        rec = _Recorder()
        self.oreilly._spawn_job(rec, "fawlty-tower", _Log())
        pod = rec.created[0].spec.template.spec
        self.assertFalse(pod.automount_service_account_token)
        self.assertTrue(pod.security_context.run_as_non_root)
        self.assertNotEqual(pod.security_context.run_as_user, 0)
        self.assertEqual(pod.security_context.seccomp_profile.type, "RuntimeDefault")
        c = pod.containers[0]
        self.assertFalse(c.security_context.allow_privilege_escalation)
        self.assertEqual(c.security_context.capabilities.drop, ["ALL"])

    def test_job_image_is_configurable(self):
        with mock.patch.object(self.oreilly, "JOB_IMAGE", "registry.local/busybox:1.36"):
            rec = _Recorder()
            self.oreilly._spawn_job(rec, "fawlty-tower", _Log())
        self.assertEqual(rec.created[0].spec.template.spec.containers[0].image, "registry.local/busybox:1.36")

    def test_event_points_at_real_pod(self):
        rec = _Recorder()
        with mock.patch.dict(os.environ, {"POD_NAME": "oreilly-7d9f-abcde", "POD_UID": "1234"}):
            self.oreilly._emit_event(rec, "fawlty-tower", "Oops", _Log())
        ref = rec.created[0].involved_object
        self.assertEqual((ref.name, ref.uid), ("oreilly-7d9f-abcde", "1234"))

    def test_event_falls_back_to_hostname(self):
        rec = _Recorder()
        env = {k: v for k, v in os.environ.items() if k not in ("POD_NAME", "POD_UID")}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(self.oreilly.socket, "gethostname", return_value="oreilly-xyz"):
            self.oreilly._emit_event(rec, "fawlty-tower", "Oops", _Log())
        self.assertEqual(rec.created[0].involved_object.name, "oreilly-xyz")
        self.assertIsNone(rec.created[0].involved_object.uid)


if __name__ == "__main__":
    unittest.main()
