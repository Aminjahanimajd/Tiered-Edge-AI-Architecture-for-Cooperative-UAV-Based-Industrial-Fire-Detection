import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_mmodal_physical_csv", ROOT / "tools/audit_mmodal_physical_csv.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MmodalPhysicalCsvTests(unittest.TestCase):
    def test_timestamp_columns_are_summarized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            path.write_text(
                "a,b\n2022-08-10 08:38:51.1,2022-08-10 16:38:51.1\n"
                "2022-08-10 08:38:52.2,2022-08-10 16:38:52.2\n",
                encoding="latin-1",
            )
            summary = MODULE.timestamp_summary(path)
            self.assertEqual(summary["timestamp_status"], "PASS")
            self.assertEqual(summary["timestamp_column_count"], 2)
            self.assertEqual(summary["first_timestamps"][1], "2022-08-10 16:38:51.1")

    def test_measurement_csv_has_no_timestamp_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            path.write_text("a,b\n1,2\n3,4\n", encoding="latin-1")
            summary = MODULE.timestamp_summary(path)
            self.assertEqual(summary["timestamp_status"], "NO_TIMESTAMP_COLUMNS")
