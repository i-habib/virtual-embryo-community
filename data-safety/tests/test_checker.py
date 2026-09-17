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

    def test_t3_exact_and_ambiguous(self):
        self.assertEqual(c.check_t3_gene("gata4", 8.75, "same", False).status, "EXCLUDED")
        self.assertEqual(c.check_t3_gene("ctnnb1", 9.0, "other", False).status, "ASK_ORGANIZERS")
        self.assertEqual(c.check_t3_gene("mab21l2", 9.5, "same", False).status, "CLEAR_BY_NAMED_GENOTYPE_RULE")
        self.assertEqual(c.check_t3_gene("mab21l2", 9.5, "same", True).status, "ASK_ORGANIZERS")

if __name__ == "__main__":
    unittest.main()
