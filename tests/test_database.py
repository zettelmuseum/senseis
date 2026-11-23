from __future__ import annotations

import io
import json
import struct
import tarfile
import tempfile
import unittest
import zlib
from pathlib import Path

from scripts.build_library import HEADER, RECORD, MAGIC, build_archive, safe_path
from scripts.analyze_snapshot import inspect_archive


def read_archive(path: Path) -> dict[str, bytes]:
    with path.open("rb") as stream:
        header = stream.read(HEADER.size)
        magic, version, count, payload_length, index_length, index_crc = HEADER.unpack(header)
        if magic != MAGIC or version != 1:
            raise AssertionError("bad archive header")
        stream.seek(HEADER.size + payload_length)
        packed_index = stream.read(index_length)
        raw_index = zlib.decompress(packed_index)
        if zlib.crc32(raw_index) & 0xffffffff != index_crc:
            raise AssertionError("bad directory CRC")
        pos = 0
        result = {}
        for _ in range(count):
            offset, stored_length, crc, flags, name_length = RECORD.unpack_from(raw_index, pos)
            pos += RECORD.size
            name = raw_index[pos:pos + name_length].decode("utf-8")
            pos += name_length
            stream.seek(HEADER.size + offset)
            packed = stream.read(stored_length)
            data = zlib.decompress(packed) if flags & 1 else packed
            if zlib.crc32(data) & 0xffffffff != crc:
                raise AssertionError("bad file CRC: " + name)
            result[name] = data
        if pos != len(raw_index):
            raise AssertionError("trailing directory data")
        return result


class CompactArchiveTests(unittest.TestCase):
    def make_archive(self, root: Path, include_large_image: bool = False) -> Path:
        archive = root / "sample.tar.bz2"
        members = {
            "snapshot/index.html": b"""<!doctype html><html><head><title>Home</title><base href='https://senseis.xmp.net/'></head><body>
                <h1>Sensei Home</h1><a href='?Go.Introduction'>Go introduction</a>
                <a href='files/tesuji.sgf'>SGF</a><img src='images/stone.png'>
                <img src='images/9a8fcc48e64b4f14cfd4234df48afe83.png' alt='Go diagram'></body></html>""",
            "snapshot/Go/Introduction.html": b"""<!doctype html><html><head><title>Go Introduction</title></head><body>
                <h1>Introduction</h1><a href='../index.html#top'>Home</a>
                <p>Rules and strategy</p></body></html>""",
            "snapshot/files/tesuji.sgf": b"(;GM[1]FF[4]SZ[19];B[pd];W[dd])",
            "snapshot/images/9a8fcc48e64b4f14cfd4234df48afe83.sgf": b"(;GM[1]FF[4]SZ[19];B[pd];W[dd])",
            "snapshot/images/9a8fcc48e64b4f14cfd4234df48afe83.png": b"\x89PNG\r\n\x1a\n" + b"x" * 60,
            "snapshot/images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png": b"\x89PNG\r\n\x1a\n" + b"unmatched diagram",
            "snapshot/images/stone.png": b"\x89PNG\r\n\x1a\n" + b"x" * 60,
            "snapshot/css/site.css": b"body { color: black; }" * 100,
            "snapshot/notes.txt": b"snapshot note",
        }
        if include_large_image:
            members["snapshot/images/large.jpg"] = b"\xff\xd8" + b"x" * (500 * 1024)
        with tarfile.open(archive, "w:bz2") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return archive

    def test_archive_sample_extracts_only_sampled_html(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = inspect_archive(self.make_archive(root), root / "sample", max_members=100, max_pages=1)
            self.assertEqual(report["sampled_pages"], 1)
            self.assertEqual(len([p for p in (root / "sample").rglob("*") if p.is_file()]), 1)
            self.assertEqual(report["page_examples"][0]["anchors"], 2)

    def test_compact_archive_roundtrip_and_skips_diagram_pngs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.make_archive(root)
            output = root / "senseis.slb"
            result = build_archive(archive, output)
            self.assertGreaterEqual(result["files"], 6)
            self.assertEqual(result["sgf_files"], 2)
            self.assertEqual(result["diagram_pngs_skipped"], 2)
            self.assertEqual(result["alias_entries"], 0)
            files = read_archive(output)
            self.assertIn("__senseis_home__.html", files)
            self.assertIn("href='?Go.Introduction'", files["snapshot/index.html"].decode("utf-8"))
            self.assertIn("src='images/stone.png'", files["snapshot/index.html"].decode("utf-8"))
            self.assertNotIn("snapshot/images/9a8fcc48e64b4f14cfd4234df48afe83.png", files)
            self.assertNotIn("snapshot/images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png", files)
            self.assertIn("snapshot/images/stone.png", files)
            self.assertEqual(files["snapshot/files/tesuji.sgf"], b"(;GM[1]FF[4]SZ[19];B[pd];W[dd])")

    def test_directory_is_compressed_and_has_no_alias_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "senseis.slb"
            result = build_archive(self.make_archive(root), output)
            self.assertGreater(result["directory_uncompressed_bytes"], result["directory_compressed_bytes"])
            self.assertEqual(result["directory_entries"], result["files"])
            self.assertEqual(result["alias_entries"], 0)
            self.assertEqual(output.stat().st_size, HEADER.size + result["payload_bytes"] + result["directory_compressed_bytes"])

    def test_images_larger_than_500_kib_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = build_archive(self.make_archive(root, include_large_image=True), root / "senseis.slb")
            self.assertEqual(result["images_removed"], 1)
            self.assertNotIn("snapshot/images/large.jpg", read_archive(root / "senseis.slb"))

    def test_archive_path_traversal_is_rejected(self):
        self.assertIsNone(safe_path("../outside.html"))
        self.assertIsNone(safe_path("/absolute/file.html"))
        self.assertEqual(safe_path("snapshot/pages/one.html"), "snapshot/pages/one.html")

    def test_sgf_compression_is_optional_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "sgf.tar.bz2"
            raw = b"(;GM[1]FF[4]SZ[19];B[pd];W[dd])" * 100
            with tarfile.open(archive, "w:bz2") as tar:
                info = tarfile.TarInfo("snapshot/game.sgf")
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
            report = root / "compression.json"
            report.write_text(json.dumps({"recommended": True}), encoding="utf-8")
            result = build_archive(archive, root / "game.slb", report)
            self.assertEqual(result["sgf_compression_enabled"], 1)
            self.assertEqual(read_archive(root / "game.slb")["snapshot/game.sgf"], raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
