"""Sanity checks for the reference manifests under examples/ (needs PyYAML)."""
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples" / "kustomize"
sys.path.insert(0, str(ROOT / "src"))
from fawlty import dispatch  # noqa: E402


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


@unittest.skipIf(yaml is None, "PyYAML not installed")
class ExampleManifestTests(unittest.TestCase):
    def _deployments(self):
        out = {}
        for path in sorted(EX.rglob("*.yaml")):
            for d in _docs(path):
                if d.get("kind") == "Deployment":
                    out[d["metadata"]["name"]] = (path, d)
        return out

    def test_kustomizations_reference_existing_files(self):
        for k in EX.rglob("kustomization.yaml"):
            for res in yaml.safe_load(k.read_text())["resources"]:
                self.assertTrue((k.parent / res).exists(), f"{k}: missing {res}")

    def test_every_kustomization_with_deployments_rewrites_the_image(self):
        for k in EX.rglob("kustomization.yaml"):
            kz = yaml.safe_load(k.read_text())
            local = [r for r in kz["resources"] if not r.startswith("..")]
            uses_image = any(
                "image: fawlty-tower" in (k.parent / r).read_text() for r in local
            )
            if uses_image:
                names = [i["name"] for i in kz.get("images", [])]
                self.assertIn("fawlty-tower", names, f"{k}: missing images: rewrite")

    def test_one_deployment_per_guest(self):
        self.assertEqual(sorted(self._deployments()), sorted(dispatch.GUESTS))

    def test_deployments_are_safe_by_default(self):
        for name, (path, d) in self._deployments().items():
            spec = d["spec"]
            self.assertEqual(spec["replicas"], 0, f"{path}: must ship at replicas 0")
            pod = spec["template"]
            self.assertEqual(spec["selector"]["matchLabels"]["app.kubernetes.io/name"],
                             pod["metadata"]["labels"]["app.kubernetes.io/name"], path)
            (c,) = pod["spec"]["containers"]
            env = {e["name"]: e.get("value") for e in c["env"]}
            self.assertEqual(env["FAWLTY_GUEST"], name, path)
            self.assertIn("limits", c["resources"], f"{path}: every guest needs limits")
            self.assertFalse(c["securityContext"]["allowPrivilegeEscalation"], path)

    def test_default_tier_is_psa_restricted_shaped(self):
        for path in (EX / "base").glob("*.yaml"):
            for d in _docs(path):
                if d.get("kind") != "Deployment":
                    continue
                pod = d["spec"]["template"]["spec"]
                self.assertTrue(pod["securityContext"]["runAsNonRoot"], path)
                self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault", path)
                self.assertNotIn("hostNetwork", pod, path)
                self.assertEqual(pod["containers"][0]["securityContext"]["capabilities"]["drop"], ["ALL"], path)

    def test_no_liveness_probe_on_probe_faults(self):
        # A liveness probe would turn Manuel's/the Waiter's fault into a crash loop.
        for name in ("manuel", "waiter"):
            _, d = self._deployments()[name]
            self.assertNotIn("livenessProbe", d["spec"]["template"]["spec"]["containers"][0], name)

    def test_chef_declares_his_drift_label(self):
        _, d = self._deployments()["chef"]
        self.assertIn("chef-mood", d["metadata"]["labels"])


if __name__ == "__main__":
    unittest.main()
