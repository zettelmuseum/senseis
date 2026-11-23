import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_png_sgf import analyze_archive


class DiagramMappingTests(unittest.TestCase):
    def make_archive(self, root: Path, page: bytes) -> Path:
        archive = root / "snapshot.tar.bz2"
        members = {
            "snapshot/page.html": page,
            "snapshot/images/diagram.png": b"not-a-real-png",
            "snapshot/games/game.sgf": b"(;GM[1]FF[4]SZ[19];B[pd])",
        }
        with tarfile.open(archive, "w:bz2") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return archive

    def test_single_image_and_sgf_on_same_page_is_unique(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = self.make_archive(
                Path(temporary),
                b"<html><body><a href='games/game.sgf'><img src='images/diagram.png'></a></body></html>",
            )
            report = analyze_archive(archive)
        self.assertTrue(report["all_pngs_have_matching_sgf"])
        self.assertEqual(report["png_sgf_pairs"], 1)

    def test_multiple_images_on_page_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = self.make_archive(
                Path(temporary),
                b"<html><body><img src='images/diagram.png'><img src='images/diagram.png'><a href='games/game.sgf'>SGF</a></body></html>",
            )
            report = analyze_archive(archive)
        self.assertEqual(report["png_sgf_pairs"], 0)
        self.assertEqual(report["png_files_without_matching_sgf"], 1)


if __name__ == "__main__":
    unittest.main()
