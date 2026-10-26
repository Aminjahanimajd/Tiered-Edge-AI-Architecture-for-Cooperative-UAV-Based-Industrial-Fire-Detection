import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.consolidate_host_resource_summary import consolidate


class HostResourceSummaryTests(unittest.TestCase):
    def make_fixture(self, root: Path, status: str = "completed") -> tuple[Path, Path]:
        comparison = root / "comparison.csv"
        resources = root / "resources"
        resources.mkdir()
        with comparison.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=["model_id", "canonical_evidence_id"]
            )
            writer.writeheader()
            for index in range(6):
                model_id = f"model_{index}"
                evidence_id = f"evidence_{index}"
                writer.writerow(
                    {"model_id": model_id, "canonical_evidence_id": evidence_id}
                )
                directory = resources / evidence_id
                directory.mkdir()
                metric = lambda mean, maximum: {
                    "mean": mean,
                    "maximum": maximum,
                }
                summary = {
                    "status": status,
                    "return_code": 0,
                    "model_id": model_id,
                    "sampling_interval_seconds": 0.5,
                    "duration_seconds": 10.0 + index,
                    "sample_count": 20 + index,
                    "evidence": {"resource_samples_sha256": "a" * 64},
                    "metrics": {
                        "system_cpu_percent": metric(10.0, 20.0),
                        "system_ram_used_mib": metric(1000.0, 1100.0),
                        "gpu_utilization_percent": metric(30.0, 40.0),
                        "gpu_memory_used_mib": metric(100.0, 200.0),
                        "gpu_power_w": metric(12.0, 14.0),
                        "gpu_temperature_c": metric(45.0, 50.0),
                    },
                }
                (directory / "run_summary.json").write_text(
                    json.dumps(summary), encoding="utf-8"
                )
        return comparison, resources

    def test_consolidates_only_canonical_six_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            comparison, resources = self.make_fixture(Path(temporary))
            rows, inputs = consolidate(comparison, resources)
        self.assertEqual(6, len(rows))
        self.assertEqual(6, len(inputs))
        self.assertEqual("evidence_0", rows[0]["canonical_evidence_id"])
        self.assertEqual(1000.0, rows[0]["system_ram_mean_mib"])
        self.assertEqual(50.0, rows[0]["gpu_temperature_max_c"])

    def test_rejects_noncompleted_resource_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            comparison, resources = self.make_fixture(Path(temporary), status="failed")
            with self.assertRaisesRegex(ValueError, "not completed"):
                consolidate(comparison, resources)


if __name__ == "__main__":
    unittest.main()
