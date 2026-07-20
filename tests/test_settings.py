import json
import tempfile
import unittest
from pathlib import Path

from partport.settings import PartPortSettings, load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = PartPortSettings(
                "global",
                "Symbols",
                "Footprints",
                "en",
                r"C:\Projects\Board",
                ("szlcsc",),
            )
            save_settings(expected, path)
            self.assertEqual(load_settings(path), expected)

    def test_invalid_destination_falls_back_to_project(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"destination": "invalid"}), encoding="utf-8")
            self.assertEqual(load_settings(path).destination, "project")

    def test_invalid_language_falls_back_to_chinese(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"language": "invalid"}), encoding="utf-8")
            self.assertEqual(load_settings(path).language, "zh_CN")

    def test_empty_sources_fall_back_to_both(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"data_sources": []}), encoding="utf-8")
            self.assertEqual(load_settings(path).data_sources, ("lcsc", "szlcsc"))
