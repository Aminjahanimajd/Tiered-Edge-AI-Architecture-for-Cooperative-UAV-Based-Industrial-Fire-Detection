import unittest

from tools.analyze_integrated_trial import identity_check, summary


class AnalyzeIntegratedTrialTests(unittest.TestCase):
    def test_summary_uses_population_statistics_and_preserves_n(self):
        observed = summary([1.0, 2.0, 3.0])
        self.assertEqual(observed["n"], 3)
        self.assertEqual(observed["mean"], 2.0)
        self.assertEqual(observed["median"], 2.0)
        self.assertAlmostEqual(observed["population_standard_deviation"], (2.0 / 3.0) ** 0.5)

    def test_identity_check_reports_missing_correlated_event(self):
        observed = identity_check(
            {
                "alerts": [{"event_id": "a"}, {"event_id": "b"}],
                "verdicts": [{"event_id": "a"}],
            }
        )
        self.assertFalse(observed["all_groups_match"])
        self.assertEqual(observed["missing_by_group"]["verdicts"], ["b"])


if __name__ == "__main__":
    unittest.main()
