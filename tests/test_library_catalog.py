import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partport.library_catalog import load_global_library_catalog


class LibraryCatalogTests(unittest.TestCase):
    def test_reads_kicad_libraries_and_skips_table_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            symbol = root / "mine.kicad_sym"
            footprint = root / "mine.pretty"
            symbol.write_text('(kicad_symbol_lib (version 20231120))\n', encoding="utf-8")
            footprint.mkdir()
            (root / "sym-lib-table").write_text(
                '(sym_lib_table\n'
                f' (lib (name "Mine")(type "KiCad")(uri "{symbol.as_posix()}"))\n'
                ' (lib (name "Stock")(type "Table")(uri "stock"))\n)\n',
                encoding="utf-8",
            )
            (root / "fp-lib-table").write_text(
                '(fp_lib_table\n'
                f' (lib (name "MineFP")(type "KiCad")(uri "{footprint.as_posix()}"))\n)\n',
                encoding="utf-8",
            )
            catalog = load_global_library_catalog(root)
            self.assertTrue(catalog.symbols[0].writable)
            self.assertFalse(catalog.symbols[1].writable)
            self.assertTrue(catalog.footprints[0].writable)

    def test_resolves_environment_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            symbol = root / "mine.kicad_sym"
            symbol.write_text('(kicad_symbol_lib (version 20231120))\n', encoding="utf-8")
            (root / "sym-lib-table").write_text(
                '(sym_lib_table (lib (name "Mine")(type "KiCad")'
                '(uri "${PARTPORT_TEST_LIB}/mine.kicad_sym")))',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"PARTPORT_TEST_LIB": str(root)}):
                catalog = load_global_library_catalog(root)
            self.assertEqual(catalog.symbols[0].path, symbol.resolve())


if __name__ == "__main__":
    unittest.main()
