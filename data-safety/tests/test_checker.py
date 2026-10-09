import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("checker", ROOT / "check_external_data.py")
c = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c
spec.loader.exec_module(c)

class RulesTests(unittest.TestCase):
    def test_t1_boundaries(self):
        self.assertEqual(c.check_stage("t1", 9.5).status, "CLEAR_BY_STAGE_RULE")
        self.assertEqual(c.check_stage("t1", 9.5001).status, "EXCLUDED")
        self.assertEqual(c.check_stage("t1", 13.5).status, "EXCLUDED")
        self.assertEqual(c.check_stage("t1", 13.5001).status, "CLEAR_BY_STAGE_RULE")

    def test_t2_heart_interp_boundaries(self):
        self.assertEqual(c.check_stage("t2-heart", 8.25).status, "CLEAR_BY_STAGE_RULE")
        self.assertEqual(c.check_stage("t2-heart", 8.4).status, "EXCLUDED")
        self.assertEqual(c.check_stage("t2-heart", 8.75).status, "CLEAR_BY_STAGE_RULE")

    def test_t2_embryo_boundaries(self):
        self.assertEqual(c.check_stage("t2-embryo", 7.25).status, "CLEAR_BY_STAGE_RULE")
        self.assertEqual(c.check_stage("t2-embryo", 7.5).status, "EXCLUDED")
        self.assertEqual(c.check_stage("t2-embryo", 8.0).status, "CLEAR_BY_STAGE_RULE")

    def test_ranges_crossing_protected_windows_need_filtering(self):
        self.assertEqual(c.interval_relation("t2-heart", 8.0, 9.0).status, "FILTER_REQUIRED")
        self.assertEqual(c.interval_relation("t1", 9.0, 14.0).status, "FILTER_REQUIRED")
        # Exact released bracketing stages are individually legal, but the open interval
        # between them is protected. These were the edge cases the first implementation missed.
        self.assertEqual(c.interval_relation("t2-heart", 8.25, 8.75).status, "FILTER_REQUIRED")
        self.assertEqual(c.interval_relation("t2-embryo", 7.25, 8.0).status, "FILTER_REQUIRED")
        # Same asymmetry for extrapolation: E9.5 itself is legal while (9.5, 13.5] is not.
        self.assertEqual(c.interval_relation("t1", 9.5, 13.5).status, "FILTER_REQUIRED")

    def test_ranges_fully_inside_protected_windows_are_excluded(self):
        self.assertEqual(c.interval_relation("t2-heart", 8.3, 8.7).status, "EXCLUDED")
        self.assertEqual(c.interval_relation("t2-embryo", 7.3, 7.9).status, "EXCLUDED")
        self.assertEqual(c.interval_relation("t1", 9.5001, 13.5).status, "EXCLUDED")

    def test_ranges_outside_protected_windows_are_clear(self):
        self.assertEqual(c.interval_relation("t2-heart", 8.0, 8.25).status, "CLEAR_BY_STAGE_RULE")
        self.assertEqual(c.interval_relation("t2-heart", 8.75, 9.5).status, "CLEAR_BY_STAGE_RULE")
        self.assertEqual(c.interval_relation("t1", 13.5001, 14.0).status, "CLEAR_BY_STAGE_RULE")

    def test_t2_heart_after_last_released_stage_asks_organizers(self):
        # Section 10 states an E9.5-E13.5 window without naming a task, so the heart
        # stages after E9.5 are referred to the organizers rather than classified here.
        self.assertEqual(c.check_stage("t2-heart", 9.5).status, "CLEAR_BY_STAGE_RULE")
        self.assertEqual(c.check_stage("t2-heart", 10.0).status, "ASK_ORGANIZERS")
        self.assertEqual(c.check_stage("t2-heart", 11.0).status, "ASK_ORGANIZERS")
        self.assertEqual(c.check_stage("t2-heart", 14.0).status, "ASK_ORGANIZERS")

    def test_t2_heart_held_out_late_stages_are_excluded(self):
        # Section 10 names E10.5 and E12.5 as held out in the heart setting, and says
        # "No measured data from a held-out stage or genotype may be used, by any route."
        self.assertEqual(c.check_stage("t2-heart", 10.5).status, "EXCLUDED")
        self.assertEqual(c.check_stage("t2-heart", 12.5).status, "EXCLUDED")
        self.assertEqual(c.check_stage("t2-heart", 8.5).status, "EXCLUDED")

    def test_t2_heart_ranges_past_last_released_stage_ask_organizers(self):
        self.assertEqual(c.interval_relation("t2-heart", 9.5, 10.0).status, "ASK_ORGANIZERS")
        self.assertEqual(c.interval_relation("t2-heart", 9.0, 10.0).status, "ASK_ORGANIZERS")
        self.assertEqual(c.interval_relation("t2-heart", 8.0, 9.5).status, "FILTER_REQUIRED")

    def test_no_invented_heart_extrapolation_window(self):
        windows = c.PROTECTED_WINDOWS["t2-heart"]
        self.assertFalse(any(w.contains(11.0) for w in windows))
        self.assertFalse(any(w.contains(9.6) for w in windows))

    def test_clear_verdicts_state_disclosure_condition(self):
        disclosure = "Every external source must be disclosed with the submission."
        clear_cases = [
            c.check_stage("t1", 9.5),
            c.check_stage("t2-embryo", 8.5),
            c.interval_relation("t2-heart", 8.75, 9.5),
            c.check_t3_gene("mab21l2", 9.5, "same", False),
        ]
        for v in clear_cases:
            self.assertTrue(v.status.startswith("CLEAR"), v.status)
            self.assertIn(disclosure, v.action)

    def test_clear_after_e135_states_explicit_source_condition(self):
        condition = "Anything after E13.5 may be used, provided the source and its stages are stated explicitly with the submission."
        self.assertIn(condition, c.check_stage("t1", 14.0).action)
        self.assertIn(condition, c.interval_relation("t1", 13.5001, 14.0).action)
        self.assertNotIn(condition, c.check_stage("t1", 9.5).action)

    def test_rules_label(self):
        self.assertEqual(
            c.RULES_SNAPSHOT,
            "Rules Section 10, restatement effective 2026-08-26, checked 2026-10-08",
        )

    def test_t3_exact_and_ambiguous(self):
        self.assertEqual(c.check_t3_gene("gata4", 8.75, "same", False).status, "EXCLUDED")
        self.assertEqual(c.check_t3_gene("ctnnb1", 9.0, "other", False).status, "ASK_ORGANIZERS")
        self.assertEqual(c.check_t3_gene("mab21l2", 9.5, "same", False).status, "CLEAR_BY_NAMED_GENOTYPE_RULE")
        self.assertEqual(c.check_t3_gene("mab21l2", 9.5, "same", True).status, "ASK_ORGANIZERS")

if __name__ == "__main__":
    unittest.main()
