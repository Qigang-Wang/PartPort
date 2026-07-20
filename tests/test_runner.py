import sys
import tempfile
import unittest
from pathlib import Path

from partport.jlc2_runner import build_command, summarize_process_failure
from partport.models import RunnerOptions


class RunnerCommandTests(unittest.TestCase):
    def test_uses_current_python_not_exe(self):
        with tempfile.TemporaryDirectory() as directory:
            command = build_command("C123", Path(directory), RunnerOptions())
            self.assertEqual(command[0], sys.executable)
            self.assertEqual(command[1:3], ["-m", "JLC2KiCadLib.JLC2KiCadLib"])
            self.assertNotIn("JLC2KiCadLib.exe", command)
            self.assertIn("--skip_existing", command)

    def test_disable_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            options = RunnerOptions(import_symbol=False, import_footprint=False, models=())
            command = build_command("C123", Path(directory), options)
            self.assertIn("--no_symbol", command)
            self.assertIn("--no_footprint", command)
            self.assertNotIn("-models", command)

    def test_failure_summary_prefers_final_exception(self):
        lines = [
            "Creating footprint ...",
            "Traceback (most recent call last):",
            '  File "footprint_handlers.py", line 296, in h_ARC',
            "AttributeError: 'Vector2D' object has no attribute 'rotate'",
        ]
        self.assertEqual(
            summarize_process_failure(lines, 1),
            "AttributeError: 'Vector2D' object has no attribute 'rotate' (exit code 1)",
        )

    def test_failure_summary_falls_back_to_exit_status(self):
        self.assertEqual(
            summarize_process_failure([], 1),
            "JLC2KiCadLib exited with code 1.",
        )


if __name__ == "__main__":
    unittest.main()
