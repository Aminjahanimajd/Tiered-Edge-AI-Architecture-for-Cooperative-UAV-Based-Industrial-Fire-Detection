import unittest

from tools.run_yolo_experiment import blocking_processes, parse_nvidia_query


class RunYoloExperimentTests(unittest.TestCase):
    def test_gpu_snapshot_parser_preserves_units(self):
        self.assertEqual(
            parse_nvidia_query("38, 12.5, 100, 3996, 4"),
            {
                "temperature_c": 38.0,
                "power_w": 12.5,
                "memory_used_mib": 100.0,
                "memory_free_mib": 3996.0,
                "gpu_utilization_percent": 4.0,
            },
        )

    def test_gpu_heavy_game_is_a_preflight_blocker(self):
        self.assertEqual(blocking_processes(["explorer.exe", "CS2.EXE"]), ["cs2.exe"])


if __name__ == "__main__":
    unittest.main()
