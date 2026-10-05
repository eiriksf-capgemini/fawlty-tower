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

    def test_word_boundary_unhealthy_is_not_healthy(self):
        r = grade.grade(self.sc["victim"], "The victim is unhealthy and failing.")
        self.assertEqual(r["score"], 0.0)
        self.assertIn("unhealthy", r["warnings"])

    def test_word_boundary_headroom_is_not_oom(self):
        r = grade.grade(self.sc["sybil"], "Plenty of headroom; memory stable, no restart.")
        self.assertIsNone(r["groups"][0]["matched"])

    def test_stems_still_match(self):
        r = grade.grade(self.sc["kitchen"], "CPU is being throttled at its limit.")
        self.assertEqual(r["score"], 1.0)

    def test_negated_misdiagnosis_is_not_a_warning(self):
        text = "Pod is not OOMKilled; it is in CrashLoopBackOff, restarting after the process exits with code 1."
        r = grade.grade(self.sc["basil"], text)
        self.assertEqual(r["score"], 1.0)
        self.assertEqual(r["warnings"], [])
        self.assertIn("oomkilled", r["negated"])

    def test_non_zero_exit_is_not_a_negation(self):
        r = grade.grade(self.sc["basil"], "CrashLoopBackOff: restart after non-zero exit.")
        self.assertEqual(r["score"], 1.0)

    def test_negated_required_phrase_does_not_count(self):
        r = grade.grade(self.sc["victim"], "The victim is not healthy.")
        self.assertEqual(r["score"], 0.0)

    def test_negative_control_fails_without_strict(self):
        r = grade.grade(self.sc["victim"], "Mostly healthy but there was an outage.")
        self.assertEqual(r["score"], 1.0)
        self.assertFalse(grade.passed(r, 0.67, strict=False))
        ok = grade.grade(self.sc["victim"], "Healthy and stable; there was no outage.")
        self.assertTrue(grade.passed(ok, 0.67, strict=False))

    def test_misdiagnosis_only_warns_for_normal_guest(self):
        r = grade.grade(self.sc["sybil"], "OOMKilled, memory at limit, restart loop. Node memory pressure?")
        self.assertTrue(grade.passed(r, 0.67, strict=False))
        self.assertFalse(grade.passed(r, 0.67, strict=True))

    def test_negation_corpus(self):
        """Correct diagnoses that phrase things negatively must still pass."""
        good = {
            "victim": [
                "No evidence of an outage; the victim is healthy.",
                "Nothing is failing, it's healthy.",
                "It isn\u2019t failing and looks healthy.",
                "It hasn't had an outage. Stable.",
                "Healthy: no restarts, CrashLoopBackOff or OOMKilled.",
                "Healthy: no restarts, CrashLoopBackOff, or OOMKilled.",
                "Healthy: no restarts, evictions, CrashLoopBackOff, or OOMKilled.",
                "We excluded an outage; the service is healthy.",
                "I can rule out an outage: healthy.",
                "Nothing to report, the service is healthy.",
                "The workload is healthy and stable, nothing wrong.",
            ],
            "basil": [
                "Not OOMKilled but CrashLoopBackOff: the process exits and restarts climb.",
                "Not OOMKilled, the pod is in CrashLoopBackOff with restarts after each exit.",
            ],
            "sybil": [
                "Memory is never released until OOMKilled; restart loop.",
                "OOMKilled, memory leak, restarts; not node memory pressure.",
            ],
        }
        for guest, texts in good.items():
            for text in texts:
                r = grade.grade(self.sc[guest], text)
                self.assertTrue(grade.passed(r, 0.67), f"{guest}: {text!r} -> {r}")

    def test_negation_reaches_every_item_of_a_list(self):
        for text in ("no restarts, crashloopbackoff, or oomkilled",
                     "no restarts, evictions, crashloopbackoff, or oomkilled",
                     "the cluster is fine, no restarts, crashloopbackoff, or oomkilled"):
            self.assertEqual(grade.find("oomkilled", text), "negated", text)

    def test_a_new_claim_after_a_comma_is_not_negated(self):
        for text in ("not oomkilled, it's crashloopbackoff",
                     "not oomkilled, the pod is in crashloopbackoff"):
            self.assertEqual(grade.find("crashloopbackoff", text), "hit", text)

    def test_excluded_and_rule_out_negate(self):
        for text in ("we excluded oomkilled as a possible cause",
                     "this excludes oomkilled",
                     "we can rule out oomkilled",
                     "having ruled out oomkilled"):
            self.assertEqual(grade.find("oomkilled", text), "negated", text)

    def test_wrong_victim_diagnoses_fail(self):
        for text in ("The victim is unhealthy.", "Service is failing and in CrashLoopBackOff.",
                     "There was an outage.", "Not healthy: failing readiness."):
            r = grade.grade(self.sc["victim"], text)
            self.assertFalse(grade.passed(r, 0.67), f"{text!r} -> {r}")

    def test_two_of_three_meets_default_threshold(self):
        r = grade.grade(self.sc["sybil"], "OOMKilled at its memory limit.")
        self.assertAlmostEqual(r["score"], 2 / 3)
        self.assertTrue(grade.passed(r, 0.67))

    def test_fatal_warning_rule_is_shared(self):
        r = grade.grade(self.sc["sybil"], "OOMKilled, memory at limit, restart loop. Node memory pressure?")
        self.assertFalse(grade.warnings_are_fatal(r))
        self.assertTrue(grade.warnings_are_fatal(r, strict=True))
        self.assertTrue(grade.warnings_are_fatal(grade.grade(self.sc["victim"], "it had an outage")))

    def test_cli_exit_codes(self):
        self.assertEqual(grade.main(["--list"]), 0)
        self.assertEqual(grade.main(["nobody", "-"]), 2)


if __name__ == "__main__":
    unittest.main()
