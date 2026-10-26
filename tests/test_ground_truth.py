import json
import os
import tempfile
import unittest

from drone_enhanced_core.ground_truth import GroundTruthRecorder


class GroundTruthRecorderTests(unittest.TestCase):
    def test_positive_trial_sequence_is_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "markers.jsonl")
            recorder = GroundTruthRecorder(path, "exp", "trial", "fire")
            start = recorder.mark_visible_start("lighter ignited")
            end = recorder.mark_visible_end("lighter extinguished")
            recorder.append_correction(start["sequence"], "start was approximately late", "operator note")
            recorder.complete()
            with open(path, "r", encoding="utf-8") as source:
                records = [json.loads(line) for line in source]
            self.assertEqual(
                [record["event_type"] for record in records],
                [
                    "TRIAL_STARTED",
                    "HAZARD_VISIBLE_START",
                    "HAZARD_VISIBLE_END",
                    "CORRECTION",
                    "TRIAL_COMPLETED",
                ],
            )
            self.assertEqual(end["sequence"], 3)

    def test_cannot_complete_while_fire_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = GroundTruthRecorder(
                os.path.join(directory, "markers.jsonl"), "exp", "trial", "fire"
            )
            recorder.mark_visible_start()
            with self.assertRaises(RuntimeError):
                recorder.complete()
            recorder.abort("test cleanup")

    def test_negative_trial_rejects_fire_visibility_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = GroundTruthRecorder(
                os.path.join(directory, "markers.jsonl"),
                "exp",
                "trial",
                "empty_background",
            )
            with self.assertRaises(RuntimeError):
                recorder.mark_visible_start()
            recorder.complete()


if __name__ == "__main__":
    unittest.main()
