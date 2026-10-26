import unittest

from drone_enhanced_core.protocol import HazardAlert, TargetBox


MODEL_HASH = "a" * 64


class ProtocolTests(unittest.TestCase):
    def test_valid_alert_serializes_explicit_image_frame(self):
        box = TargetBox(0.5, 0.4, 0.1, 0.2, 1280, 720)
        alert = HazardAlert(
            "exp-1",
            "trial-1",
            "event-1",
            "sentinel",
            "fire",
            0.8,
            3,
            100,
            110,
            MODEL_HASH,
            box,
        )
        payload = alert.to_dict()
        self.assertEqual(payload["event_id"], "event-1")
        self.assertEqual(
            payload["target_box"]["coordinate_frame"],
            "source_camera_normalized_image",
        )

    def test_box_rejects_geometrically_invalid_values(self):
        with self.assertRaises(ValueError):
            TargetBox(1.2, 0.4, 0.1, 0.2, 640, 480)
        with self.assertRaises(ValueError):
            TargetBox(0.5, 0.4, 0.0, 0.2, 640, 480)

    def test_alert_rejects_invalid_hash_and_timestamp_order(self):
        box = TargetBox(0.5, 0.4, 0.1, 0.2, 640, 480)
        with self.assertRaises(ValueError):
            HazardAlert(
                "exp",
                "trial",
                "event",
                "sentinel",
                "fire",
                0.8,
                3,
                100,
                90,
                "invalid",
                box,
            )


if __name__ == "__main__":
    unittest.main()
