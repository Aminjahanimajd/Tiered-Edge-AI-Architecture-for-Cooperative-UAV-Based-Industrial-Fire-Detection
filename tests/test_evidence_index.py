import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "build_evidence_index.py"
SPEC = importlib.util.spec_from_file_location("build_evidence_index", TOOL_PATH)
INDEX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INDEX)


class EvidenceIndexTests(unittest.TestCase):
    def test_success_with_missing_capture_is_incomplete(self):
        self.assertEqual(
            INDEX.evidence_status({"exit_code": 0, "stdout": None, "stderr": ""}),
            "INCOMPLETE",
        )

    def test_successful_stderr_is_visible(self):
        self.assertEqual(
            INDEX.evidence_status(
                {"exit_code": 0, "stdout": "result", "stderr": "warning"}
            ),
            "PASS_WITH_STDERR",
        )


if __name__ == "__main__":
    unittest.main()
