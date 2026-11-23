import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_png_sgf import analyze_archive


CODE = "9a8fcc48e64b4f14cfd4234df48afe83"


class DiagramMappingTests(unittest.TestCase):
    def make_archive(self, root: Path, png_name: str = CODE + ".png", sgf_name: str = CODE + ".sgf") -> Path:
        archive = root / "snapshot.tar.bz2"
        members = {
            "snapshot/images/" + png_name: b"png",
            "snapshot/images/" + sgf_name: b"(;GM[1]FF[4]SZ[19];B[pd])",
        }
        with tarfile.open(archive, "w:bz2") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return archive

    def test_identical_32_character_code_pairs_png_and_sgf(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = analyze_archive(self.make_archive(Path(temporary)))
        self.assertTrue(report["all_pngs_have_matching_sgf"])
        self.assertEqual(report["png_sgf_pairs"], 1)
        self.assertEqual(report["png_files_without_matching_sgf"], 0)

    def test_png_without_same_code_sgf_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = analyze_archive(self.make_archive(Path(temporary), sgf_name="differentcode1234567890123456.sgf"))
        self.assertFalse(report["all_pngs_have_matching_sgf"])
        self.assertEqual(report["png_sgf_pairs"], 0)
        self.assertEqual(report["png_files_without_matching_sgf"], 1)

    def test_wrong_length_code_is_not_paired(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = analyze_archive(self.make_archive(Path(temporary), png_name="short.png", sgf_name="short.sgf"))
        self.assertEqual(report["png_sgf_pairs"], 0)
        self.assertEqual(report["png_files_with_invalid_code_name"], 1)


if __name__ == "__main__":
    unittest.main()
