import tempfile
import unittest
from pathlib import Path

from partport.kicad_context import find_project_file


class ProjectFileTests(unittest.TestCase):
    def test_prefers_matching_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "board.kicad_pro").touch()
            (root / "other.kicad_pro").touch()
            self.assertEqual(find_project_file(root, "board"), root / "board.kicad_pro")

    def test_returns_only_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "only.kicad_pro"
            project.touch()
            self.assertEqual(find_project_file(root), project)

    def test_multiple_projects_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.kicad_pro").touch()
            (root / "two.kicad_pro").touch()
            self.assertIsNone(find_project_file(root))


if __name__ == "__main__":
    unittest.main()
