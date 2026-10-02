import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import grade  # noqa: E402

GUESTS = ["basil", "sybil", "manuel", "kitchen", "waiter", "major", "polly",
          "oreilly", "chef", "victim", "diskfill", "pidbomb", "squatter"]


class GradeTests(unittest.TestCase):
    def setUp(self):
        self.sc = grade.load()

    def test_every_guest_has_a_scenario(self):
        self.assertEqual(sorted(self.sc), sorted(GUESTS))

    def test_schema(self):
        for name, s in self.sc.items():
            for key in ("tier", "fault", "root_cause", "required", "misdiagnoses"):
                self.assertIn(key, s, f"{name} missing {key}")
            self.assertTrue(all(isinstance(g, list) and g for g in s["required"]), name)
            self.assertIn(s["tier"], ("default", "node"))

    def test_good_diagnosis_passes(self):
        text = "Pod is in CrashLoopBackOff with a climbing restart count after the process exited."
        self.assertEqual(grade.grade(self.sc["basil"], text)["score"], 1.0)

    def test_oom_vs_node(self):
        text = "Container OOMKilled: memory climbs to the limit, then restarts. Node memory pressure suspected."
        r = grade.grade(self.sc["sybil"], text)
        self.assertEqual(r["score"], 1.0)
        self.assertIn("node memory pressure", r["warnings"])

    def test_negative_control(self):
        self.assertEqual(grade.grade(self.sc["victim"], "Workload looks healthy, nothing wrong.")["score"], 1.0)
        bad = grade.grade(self.sc["victim"], "Service is unhealthy and in CrashLoopBackOff.")
        self.assertTrue(bad["warnings"])

    def test_empty_diagnosis_fails(self):
        for name, s in self.sc.items():
            self.assertEqual(grade.grade(s, "")["score"], 0.0, name)

    def test_cli_exit_codes(self):
        self.assertEqual(grade.main(["--list"]), 0)
        self.assertEqual(grade.main(["nobody", "-"]), 2)


if __name__ == "__main__":
    unittest.main()
