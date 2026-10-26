import importlib.util
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "benchmark_exact_device_candidate.py"
SPEC = importlib.util.spec_from_file_location("exact_device_benchmark", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class EvidenceHelpersTests(unittest.TestCase):
    def test_sha256_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "value.bin"
            path.write_bytes(b"abc")
            self.assertEqual(
                MODULE.file_sha256(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_resource_snapshot_has_timestamps(self):
        sample = MODULE.resource_snapshot()
        self.assertIn("utc", sample)
        self.assertIn("monotonic_ns", sample)

    def test_formal_constants_match_protocol(self):
        self.assertEqual(MODULE.FORMAL_IMAGE_COUNT, 64)
        self.assertEqual(MODULE.FORMAL_WARMUP, 20)
        self.assertEqual(MODULE.FORMAL_ITERATIONS, 200)
        self.assertEqual(MODULE.FORMAL_RESOURCE_INTERVAL_SECONDS, 1.0)


if __name__ == "__main__":
    unittest.main()
