import unittest

from tools.prepare_ssd_mobilenet_experiment import training_schedule


class PrepareSsdMobileNetExperimentTests(unittest.TestCase):
    def test_schedule_uses_ceil_steps_and_linear_lr_scaling(self):
        schedule = training_schedule(image_count=3558, batch_size=8, epochs=100)
        self.assertEqual(schedule["steps_per_epoch"], 445)
        self.assertEqual(schedule["total_steps"], 44500)
        self.assertEqual(schedule["warmup_steps"], 1335)
        self.assertAlmostEqual(schedule["learning_rate_base"], 0.005)
        self.assertAlmostEqual(schedule["warmup_learning_rate"], 0.005 / 3.0)

    def test_schedule_rejects_nonpositive_values(self):
        with self.assertRaises(ValueError):
            training_schedule(0, 8, 100)


if __name__ == "__main__":
    unittest.main()
