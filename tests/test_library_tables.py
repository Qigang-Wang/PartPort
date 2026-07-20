import tempfile
import unittest
from pathlib import Path

from partport.library_tables import LibraryTableError, update_table


class LibraryTableTests(unittest.TestCase):
    def test_creates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sym-lib-table"
            self.assertTrue(update_table(path, "sym_lib_table", "partport", "${KIPRJMOD}/x", "test"))
            self.assertFalse(update_table(path, "sym_lib_table", "partport", "${KIPRJMOD}/x", "test"))
            self.assertEqual(path.read_text(encoding="utf-8").count('(name "partport")'), 1)

    def test_detects_nickname_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fp-lib-table"
            update_table(path, "fp_lib_table", "partport", "one", "test")
            with self.assertRaises(LibraryTableError):
                update_table(path, "fp_lib_table", "partport", "two", "test")

    def test_rejects_malformed_table(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sym-lib-table"
            path.write_text("(sym_lib_table\n", encoding="utf-8")
            with self.assertRaises(LibraryTableError):
                update_table(path, "sym_lib_table", "partport", "uri", "test")

    def test_ignores_commented_library_and_trailing_parenthesis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sym-lib-table"
            path.write_text(
                '(sym_lib_table\n'
                '  ; (lib (name "partport")(uri "wrong"))\n'
                ')\n'
                '; a trailing comment may contain )\n',
                encoding="utf-8",
            )
            changed = update_table(
                path,
                "sym_lib_table",
                "partport",
                "${KIPRJMOD}/PartPortLib/symbols/partport.kicad_sym",
                "PartPort imported symbols",
            )
            self.assertTrue(changed)
            updated = path.read_text(encoding="utf-8")
            self.assertIn('${KIPRJMOD}/PartPortLib/symbols/partport.kicad_sym', updated)
            self.assertTrue(updated.rstrip().endswith("; a trailing comment may contain )"))


if __name__ == "__main__":
    unittest.main()
