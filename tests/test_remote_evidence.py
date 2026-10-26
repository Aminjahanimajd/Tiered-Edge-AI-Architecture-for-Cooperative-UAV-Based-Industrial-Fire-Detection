import base64
import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "run_remote_evidence.py"
SPEC = importlib.util.spec_from_file_location("run_remote_evidence", TOOL_PATH)
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)


class RemoteEvidenceTests(unittest.TestCase):
    def test_console_rendering_escapes_unrepresentable_unicode(self):
        rendered = EVIDENCE.console_safe_text("active: \u25cf", "cp1252")
        self.assertEqual(rendered, "active: \\u25cf")

    def test_base64_remote_command_round_trip(self):
        command = "sh -lc 'printf HELLO\\n'"
        encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
        self.assertEqual(
            EVIDENCE.decode_remote_command(encoded),
            command,
        )

    def test_invalid_base64_remote_command_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid Base64"):
            EVIDENCE.decode_remote_command("not base64!")


if __name__ == "__main__":
    unittest.main()
