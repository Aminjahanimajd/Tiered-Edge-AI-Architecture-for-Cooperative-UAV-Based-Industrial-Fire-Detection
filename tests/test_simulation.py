import unittest

from drone_enhanced_core.simulation import replay_coordination


class CoordinationReplayTests(unittest.TestCase):
    def test_mismatch_then_confirmation_has_one_final_decision(self):
        result = replay_coordination(
            [
                {
                    "event_id": "wrong",
                    "verdict": "REJECTED",
                    "confidence": 0.1,
                    "now_ns": 1200000000,
                },
                {
                    "event_id": "simulated-event-1",
                    "verdict": "CONFIRMED",
                    "confidence": 0.9,
                    "now_ns": 1500000000,
                },
            ]
        )
        self.assertEqual(len(result["final_decisions"]), 1)
        self.assertEqual(result["final_decisions"][0]["decision"], "CONFIRMED")

    def test_no_verdict_produces_one_timeout(self):
        result = replay_coordination([])
        self.assertEqual(len(result["final_decisions"]), 1)
        self.assertEqual(result["final_decisions"][0]["decision"], "TIMEOUT")

    def test_duplicate_confirmation_cannot_create_second_final_decision(self):
        verdict = {
            "event_id": "simulated-event-1",
            "verdict": "CONFIRMED",
            "confidence": 0.9,
            "now_ns": 1500000000,
        }
        duplicate = dict(verdict)
        duplicate["now_ns"] = 1600000000
        result = replay_coordination([verdict, duplicate])
        self.assertEqual(len(result["final_decisions"]), 1)
        self.assertFalse(result["records"][-1]["accepted"])


if __name__ == "__main__":
    unittest.main()
