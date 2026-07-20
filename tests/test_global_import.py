import tempfile
import unittest
from pathlib import Path

from partport.global_import import merge_footprint_library, merge_symbol_library


class GlobalMergeTests(unittest.TestCase):
    def test_merges_symbol_and_rewrites_footprint_nickname(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "staged.kicad_sym"
            target = root / "target.kicad_sym"
            staged.write_text(
                '(kicad_symbol_lib (version 20231120)\n'
                ' (symbol "New" (property "Footprint" "partport:NewFP")'
                '  (symbol "New_0_1")))\n',
                encoding="utf-8",
            )
            target.write_text(
                '(kicad_symbol_lib (version 20231120)\n'
                ' (symbol "Old" (symbol "Old_0_1")))\n',
                encoding="utf-8",
            )
            written, skipped = merge_symbol_library(
                staged, target, "MyFootprints", skip_existing=True
            )
            text = target.read_text(encoding="utf-8")
            self.assertEqual((written, skipped), (1, 0))
            self.assertIn('(symbol "Old"', text)
            self.assertIn('(symbol "New"', text)
            self.assertIn('"MyFootprints:NewFP"', text)
            self.assertTrue(target.with_name(target.name + ".partport.bak").is_file())

    def test_skips_existing_top_level_symbol_not_nested_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "staged.kicad_sym"
            target = root / "target.kicad_sym"
            content = (
                '(kicad_symbol_lib (version 20231120)\n'
                ' (symbol "Same" (symbol "Same_0_1")))\n'
            )
            staged.write_text(content, encoding="utf-8")
            target.write_text(content, encoding="utf-8")
            self.assertEqual(
                merge_symbol_library(staged, target, "FP", skip_existing=True),
                (0, 1),
            )

    def test_merges_footprint_and_rewrites_model_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "stage.pretty"
            target = root / "global.pretty"
            staged.mkdir()
            target.mkdir()
            (staged / "New.kicad_mod").write_text(
                '(footprint "New" (model '
                '"${KIPRJMOD}/PartPortLib/partport.pretty/packages3d/New.step"))\n',
                encoding="utf-8",
            )
            (staged / "packages3d").mkdir()
            (staged / "packages3d" / "New.step").write_bytes(b"STEP")
            written, skipped = merge_footprint_library(
                staged,
                target,
                "${MY_GLOBAL_LIB}/global.pretty",
                skip_existing=True,
            )
            self.assertEqual((written, skipped), (1, 0))
            text = (target / "New.kicad_mod").read_text(encoding="utf-8")
            self.assertIn("${MY_GLOBAL_LIB}/global.pretty/packages3d/New.step", text)
            self.assertEqual((target / "packages3d" / "New.step").read_bytes(), b"STEP")


if __name__ == "__main__":
    unittest.main()
