from __future__ import annotations

import sqlite3
import struct
import tarfile
import tempfile
import unittest
import zlib
import io
import contextlib
from pathlib import Path

from scripts.build_database import build_database, unpack_payload
from scripts.analyze_snapshot import inspect_archive


class SenseisDatabaseTests(unittest.TestCase):
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
            "snapshot/images/9a8fcc48e64b4f14cfd4234df48afe83.png": b"\\x89PNG\\r\\n\\x1a\\n" + b"x" * 60,
            "snapshot/images/stone.png": b"\x89PNG\r\n\x1a\n" + b"x" * 60,
            "snapshot/css/site.css": b"body { color: black; }" * 100,
            "snapshot/notes.txt": b"snapshot note",
        }
        if include_large_image:
            members["snapshot/images/large.jpg"] = b"\\xff\\xd8" + b"x" * (500 * 1024)
        with tarfile.open(archive, "w:bz2") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                import io
                tar.addfile(info, io.BytesIO(data))
        return archive

    def test_archive_sample_extracts_only_sampled_html(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.make_archive(root)
            sample = root / "sample"
            report = inspect_archive(archive, sample, max_members=100, max_pages=1)
            self.assertEqual(report["sampled_pages"], 1)
            files = [p for p in sample.rglob("*") if p.is_file()]
            self.assertEqual(len(files), 1)
            self.assertEqual(report["page_examples"][0]["anchors"], 2)

    def test_database_keeps_pages_links_and_sgf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.make_archive(root)
            database = root / "senseis.db"
            result = build_database(archive, database, progress_every=1000)
            self.assertGreaterEqual(result["files"], 6)
            self.assertEqual(result["sgf_files"], 2)
            self.assertEqual(result["diagram_pngs_removed"], 1)
            conn = sqlite3.connect(database)
            try:
                home = conn.execute("SELECT value FROM metadata WHERE key='start_path'").fetchone()[0]
                self.assertEqual(home, "__senseis_home__.html")
                page = conn.execute(
                    "SELECT data,encoding FROM files WHERE path='snapshot/index.html'"
                ).fetchone()
                html = unpack_payload(page[0], page[1]).decode("utf-8")
                self.assertIn("/snapshot/Go/Introduction.html", html)
                self.assertIn("data-senseis-sgf", html)
                self.assertIn("senseis-sgf-viewer", html)
                self.assertIn("/snapshot/images/9a8fcc48e64b4f14cfd4234df48afe83.sgf", html)
                self.assertIsNone(conn.execute("SELECT path FROM files WHERE path='snapshot/images/9a8fcc48e64b4f14cfd4234df48afe83.png'").fetchone())
                self.assertIsNotNone(conn.execute("SELECT path FROM files WHERE path='snapshot/images/stone.png'").fetchone())
                self.assertNotIn("<base", html.lower())
                sgf = conn.execute(
                    "SELECT data FROM files WHERE path='snapshot/files/tesuji.sgf'"
                ).fetchone()[0]
                self.assertTrue(sgf.startswith(b"(;GM[1]"))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0], 3)
                columns = [row[1] for row in conn.execute("PRAGMA table_info(pages)")]
                self.assertNotIn("search_text", columns)
                matches = conn.execute(
                    "SELECT pages.path FROM pages_search JOIN pages ON pages.rowid=pages_search.docid WHERE pages_search MATCH ?", ('"Rules" AND "strategy"',)
                ).fetchall()
                self.assertIn(("snapshot/Go/Introduction.html",), matches)
                # SQLite integrity_check cannot validate contentless FTS4 tables
                # and reports a SQL logic error for this supported storage mode.
                # The MATCH assertion above verifies the inverted index is usable.
            finally:
                conn.close()

    def test_aliases_fragments_and_sgf_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.make_archive(root)
            database = root / "senseis.db"
            build_database(archive, database, progress_every=1000)
            conn = sqlite3.connect(database)
            try:
                row = conn.execute("SELECT data,encoding FROM files WHERE path='snapshot/Go/Introduction.html'").fetchone()
                page = unpack_payload(row[0], row[1]).decode("utf-8")
                self.assertIn("/snapshot/index.html#top", page)
                self.assertEqual(conn.execute("SELECT path FROM aliases WHERE alias='go.introduction'").fetchone()[0], "snapshot/Go/Introduction.html")
                self.assertEqual(conn.execute("SELECT path FROM aliases WHERE alias='tesuji.sgf'").fetchone()[0], "snapshot/files/tesuji.sgf")
            finally:
                conn.close()

    def test_images_larger_than_500_kib_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.make_archive(root, include_large_image=True)
            database = root / "senseis.db"
            result = build_database(archive, database, progress_every=1000)
            self.assertEqual(result["images_removed"], 1)
            conn = sqlite3.connect(database)
            try:
                self.assertIsNone(conn.execute(
                    "SELECT path FROM files WHERE path='snapshot/images/large.jpg'"
                ).fetchone())
            finally:
                conn.close()


    def test_archive_path_traversal_is_rejected(self):
        from scripts.build_database import safe_tar_path
        self.assertIsNone(safe_tar_path("../outside.html"))
        self.assertIsNone(safe_tar_path("/absolute/file.html"))
        self.assertEqual(safe_tar_path("snapshot/pages/one.html"), "snapshot/pages/one.html")
    def test_payload_compression_roundtrip(self):
        from scripts.build_database import store_payload
        original = b"Sensei library page text " * 200
        packed, encoding = store_payload(original, "page.html")
        self.assertEqual(unpack_payload(packed, encoding), original)
        self.assertIn(encoding, {"raw", "deflate"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
