import tempfile
import unittest
from pathlib import Path

from partport.models import ResultStatus, RunnerOptions
from partport.validation import OutputSnapshot, validate_import


class ValidationTests(unittest.TestCase):
    def test_accepts_well_formed_symbol_and_footprint(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            before = OutputSnapshot.capture(project)
            symbols = project / "PartPortLib" / "symbols"
            footprints = project / "PartPortLib" / "partport.pretty"
            symbols.mkdir(parents=True)
            footprints.mkdir(parents=True)
            (symbols / "partport.kicad_sym").write_text(
                '(kicad_symbol_lib (version 20231120) (generator "test"))\n',
                encoding="utf-8",
            )
            (footprints / "Test.kicad_mod").write_text(
                '(footprint "Test" (layer "F.Cu"))\n', encoding="utf-8"
            )
            report = validate_import(
                project,
                RunnerOptions(models=()),
                before,
                [],
            )
            self.assertEqual(report.status, ResultStatus.SUCCESS)

    def test_rejects_success_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            before = OutputSnapshot.capture(project)
            report = validate_import(
                project,
                RunnerOptions(import_footprint=False, models=()),
                before,
                [],
            )
            self.assertEqual(report.status, ResultStatus.FAILED)
            self.assertTrue(report.errors)

    def test_recognizes_explicit_existing_part_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            symbols = project / "PartPortLib" / "symbols"
            symbols.mkdir(parents=True)
            (symbols / "partport.kicad_sym").write_text(
                '(kicad_symbol_lib (version 20231120))\n', encoding="utf-8"
            )
            before = OutputSnapshot.capture(project)
            report = validate_import(
                project,
                RunnerOptions(import_footprint=False, models=()),
                before,
                ["Symbol already exists, skipping"],
            )
            self.assertEqual(report.status, ResultStatus.SKIPPED)


if __name__ == "__main__":
    unittest.main()
