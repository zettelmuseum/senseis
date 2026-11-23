#!/usr/bin/env python3
"""Stream the Sensei's Library tar.bz2 snapshot into a self-contained SQLite database."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import posixpath
import re
import sqlite3
import tarfile
import time
import urllib.parse
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup

SNAPSHOT_URL = "https://senseis.xmp.net/files/snapshots/senseis-library.tar.bz2"
HTML_EXTENSIONS = {".html", ".htm", ".xhtml", ".shtml"}
TEXT_EXTENSIONS = {".html", ".htm", ".xhtml", ".shtml", ".php", ".css", ".js", ".txt", ".xml", ".json", ".sgf", ".md", ".csv", ".svg"}
SCHEMA_VERSION = 5
MAX_IMAGE_BYTES = 500 * 1024


def safe_tar_path(name: str) -> str | None:
    """Return a canonical relative POSIX path or None for an unsafe tar member."""
    name = name.replace("\\", "/")
    if not name or name.startswith("/"):
        return None
    path = PurePosixPath(name)
    if any(part in {"..", ""} for part in path.parts):
        return None
    normalized = posixpath.normpath(name).lstrip("./")
    if normalized in {"", "."} or normalized.startswith("../"):
        return None
    return normalized


def is_html_file(path: str, data: bytes) -> bool:
    suffix = PurePosixPath(path).suffix.lower()
    sample = data[:2048].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    if sample.startswith((b"<!doctype html", b"<html", b"<?xml")) or b"<html" in sample[:512]:
        return True
    return suffix in HTML_EXTENSIONS


def mime_for(path: str, is_html: bool) -> str:
    if is_html:
        return "text/html"
    if path.lower().endswith(".sgf"):
        return "application/x-go-sgf"
    if path.lower().endswith(".svg"):
        return "image/svg+xml"
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def store_payload(data: bytes, path: str) -> tuple[bytes, str]:
    """Deflate text-like files only when the compressed representation is smaller."""
    if len(data) >= 256 and (PurePosixPath(path).suffix.lower() in TEXT_EXTENSIONS):
        packed = zlib.compress(data, 6)
        if len(packed) + 16 < len(data):
            return packed, "deflate"
    return data, "raw"



def unpack_payload(data: bytes, encoding: str) -> bytes:
    return zlib.decompress(data) if encoding == "deflate" else data


def alias_key(value: str) -> str:
    value = urllib.parse.unquote(value).replace("\\", "/").strip().strip("/")
    value = re.sub(r"[?#].*$", "", value)
    value = re.sub(r"\.(?:html?|xhtml|shtml)$", "", value, flags=re.I)
    return value.casefold()


def add_alias(conn: sqlite3.Connection, alias: str, path: str) -> None:
    key = alias_key(alias)
    if key:
        conn.execute("INSERT OR IGNORE INTO aliases(alias, path) VALUES (?, ?)", (key, path))


def lookup_alias(conn: sqlite3.Connection, value: str) -> str | None:
    key = alias_key(value)
    if not key:
        return None
    row = conn.execute("SELECT path FROM aliases WHERE alias = ?", (key,)).fetchone()
    return row[0] if row else None


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
      PRAGMA page_size=4096;
      PRAGMA journal_mode=OFF;
      PRAGMA synchronous=OFF;
      PRAGMA temp_store=MEMORY;
      CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE files (
        path TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        mime TEXT NOT NULL,
        size INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        encoding TEXT NOT NULL,
        is_html INTEGER NOT NULL DEFAULT 0,
        data BLOB NOT NULL
      );
      CREATE TABLE pages (
        path TEXT PRIMARY KEY REFERENCES files(path),
        title TEXT NOT NULL
      );
      CREATE TABLE aliases (alias TEXT PRIMARY KEY, path TEXT NOT NULL);
      PRAGMA user_version=5;
    """)


def write_home_page(conn: sqlite3.Connection, file_count: int, page_count: int) -> None:
    grouped = conn.execute("SELECT upper(substr(title,1,1)) AS letter, COUNT(*) FROM pages WHERE path != '__senseis_home__.html' GROUP BY letter ORDER BY letter").fetchall()
    entries = []
    for letter, count in grouped:
        entries.append(f"<li><strong>{html.escape(letter or '#')}</strong> — {count:,} pages</li>")
    content = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Sensei's Library — Offline</title></head><body>"
        "<h1>Sensei's Library</h1><p>Offline snapshot, available entirely on this device.</p>"
        f"<p><strong>{page_count:,}</strong> wiki pages · <strong>{file_count:,}</strong> stored files</p>"
        "<h2>Browse the library</h2><p>Use the Search button in the app toolbar to find a page by title or text.</p>"
        "<ul>" + "".join(entries) + "</ul>"
        "<h2>SGF files</h2><p>Tap an SGF link in a wiki page to save the original file through Android's file picker.</p>"
        "</body></html>"
    ).encode("utf-8")
    conn.execute(
        "INSERT OR REPLACE INTO files(path,name,mime,size,sha256,encoding,is_html,data) VALUES(?,?,?,?,?,?,1,?)",
        ("__senseis_home__.html", "__senseis_home__.html", "text/html", len(content), hashlib.sha256(content).hexdigest(), "raw", content),
    )
    conn.execute("INSERT OR REPLACE INTO pages(path,title) VALUES(?,?)", ("__senseis_home__.html", "Sensei's Library — Offline"))
    add_alias(conn, "home", "__senseis_home__.html")
    add_alias(conn, "index", "__senseis_home__.html")
    conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('start_path','__senseis_home__.html')")


def build_database(archive: Path, output: Path, progress_every: int = 2500) -> dict[str, int | str]:
    if not archive.is_file() or archive.stat().st_size == 0:
        raise RuntimeError(f"Snapshot archive is missing or empty: {archive}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    if temporary.exists():
        temporary.unlink()
    conn = sqlite3.connect(str(temporary))
    started = time.time()
    counters: Counter[str] = Counter()
    try:
        create_schema(conn)
        conn.execute("INSERT INTO metadata(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        conn.execute("INSERT INTO metadata(key,value) VALUES('source_url',?)", (SNAPSHOT_URL,))
        conn.execute("INSERT INTO metadata(key,value) VALUES('created_utc',?)", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))

        insert_sql = "INSERT OR REPLACE INTO files(path,name,mime,size,sha256,encoding,is_html,data) VALUES(?,?,?,?,?,?,?,?)"
        with tarfile.open(archive, mode="r|bz2") as tar:
            for member in tar:
                counters["members_seen"] += 1
                if not member.isfile():
                    continue
                path = safe_tar_path(member.name)
                if path is None:
                    counters["unsafe_or_empty"] += 1
                    continue
                source = tar.extractfile(member)
                if source is None:
                    continue
                with source:
                    data = source.read()
                is_html = is_html_file(path, data)
                mime = mime_for(path, is_html)
                if mime.startswith("image/") and len(data) > MAX_IMAGE_BYTES:
                    counters["images_removed"] += 1
                    counters["image_bytes_removed"] += len(data)
                    continue
                original_size = len(data)
                stored, encoding = store_payload(data, path)
                name = PurePosixPath(path).name
                conn.execute(insert_sql, (path, name, mime, original_size, hashlib.sha256(data).hexdigest(), encoding, int(is_html), sqlite3.Binary(stored)))
                counters["files"] += 1
                counters["bytes_original"] += original_size
                counters["html_files"] += int(is_html)
                counters["sgf_files"] += int(path.lower().endswith(".sgf"))
                if counters["files"] % progress_every == 0:
                    conn.commit()
                    print(f"Stored {counters['files']:,} files ({counters['bytes_original'] / (1024**2):,.1f} MiB uncompressed)", flush=True)
        conn.commit()
        if counters["files"] == 0:
            raise RuntimeError("No regular files were found in the tar.bz2 archive.")
        print(f"Import pass complete: {counters['files']:,} files", flush=True)

        # Pass 2: register HTML titles and aliases; page HTML remains byte-for-byte unchanged.
        html_paths = [row[0] for row in conn.execute("SELECT path FROM files WHERE is_html=1 ORDER BY path")]
        for index, path in enumerate(html_paths, 1):
            packed, encoding = conn.execute("SELECT data,encoding FROM files WHERE path=?", (path,)).fetchone()
            raw = unpack_payload(packed, encoding)
            soup = BeautifulSoup(raw, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            if not title:
                heading = soup.find(["h1", "h2"])
                title = heading.get_text(" ", strip=True) if heading else PurePosixPath(path).stem.replace("_", " ")
            title = re.sub(r"\s+", " ", title).strip()[:300] or PurePosixPath(path).name
            conn.execute("INSERT OR REPLACE INTO pages(path,title) VALUES(?,?)", (path, title))
            add_alias(conn, path, path)
            add_alias(conn, PurePosixPath(path).name, path)
            add_alias(conn, PurePosixPath(path).stem, path)
            add_alias(conn, PurePosixPath(path).with_suffix("").as_posix().replace("/", "."), path)
            parts = PurePosixPath(path).with_suffix("").parts
            if len(parts) >= 2:
                add_alias(conn, ".".join(parts[-2:]), path)
            add_alias(conn, title, path)
            if index % progress_every == 0:
                conn.commit()
                print(f"Registered {index:,}/{len(html_paths):,} HTML pages", flush=True)
        conn.commit()

        # Also map every stored file by its relative path; this includes image,
        # stylesheet, script, PDF and SGF attachments.
        for (path,) in conn.execute("SELECT path FROM files ORDER BY path"):
            add_alias(conn, path, path)
            add_alias(conn, PurePosixPath(path).name, path)
            add_alias(conn, PurePosixPath(path).stem, path)
        conn.commit()

        # The app dynamically renders matching SGF files in place of these PNGs,
        # so remove the redundant diagram PNG payloads and their aliases.
        diagram_png_rows = conn.execute("""
            SELECT p.path, p.size
            FROM files AS p
            JOIN files AS s ON s.path = substr(p.path, 1, length(p.path) - 3) || 'sgf'
            WHERE lower(p.path) LIKE '%.png'
              AND length(p.name) = 36
              AND substr(p.name, 33, 4) = '.png'
              AND substr(p.name, 1, 32) NOT GLOB '*[^0-9A-Fa-f]*'
        """).fetchall()
        if diagram_png_rows:
            diagram_paths = [row[0] for row in diagram_png_rows]
            counters["diagram_pngs_removed"] = len(diagram_paths)
            counters["diagram_png_bytes_removed"] = sum(int(row[1]) for row in diagram_png_rows)
            conn.executemany("DELETE FROM aliases WHERE path=?", ((p,) for p in diagram_paths))
            conn.executemany("DELETE FROM files WHERE path=?", ((p,) for p in diagram_paths))
            conn.commit()
            print(f"Removed {len(diagram_paths):,} redundant PNG diagrams ({counters['diagram_png_bytes_removed'] / (1024**2):,.1f} MiB); SGF viewers remain", flush=True)

        file_count = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        page_count = int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
        write_home_page(conn, file_count, page_count)
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('file_count',?)", (str(file_count),))
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('page_count',?)", (str(page_count),))
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('sgf_count',?)", (str(counters['sgf_files']),))
        conn.commit()
        conn.execute("PRAGMA optimize")
        conn.commit()

        # Reclaim SQLite pages freed by removed PNG payloads.
        before_compaction_bytes = temporary.stat().st_size
        before_compaction_freelist_pages = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        conn.commit()
        conn.execute("VACUUM")
        conn.execute("PRAGMA optimize")
        conn.commit()
        after_compaction_freelist_pages = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        # Collect storage diagnostics while the database connection is still open.
        storage_rows = conn.execute("SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC").fetchall()
        table_storage = {name: int(size) for name, size in storage_rows}
        payload_rows = conn.execute("SELECT encoding, COUNT(*), SUM(length(data)) FROM files GROUP BY encoding").fetchall()
        payload_storage = {encoding: {"files": int(count), "stored_bytes": int(size or 0)} for encoding, count, size in payload_rows}
        conn.close()
        os.replace(temporary, output)
        result = {
            "table_storage_bytes": table_storage,
            "payload_storage": payload_storage,
            "members_seen": int(counters["members_seen"]),
            "files": file_count,
            "pages": page_count,
            "sgf_files": int(counters["sgf_files"]),
            "uncompressed_bytes": int(counters["bytes_original"]),
            "images_removed": int(counters["images_removed"]),
            "image_bytes_removed": int(counters["image_bytes_removed"]),
            "diagram_pngs_removed": int(counters["diagram_pngs_removed"]),
            "diagram_png_bytes_removed": int(counters["diagram_png_bytes_removed"]),
            "database_bytes_before_compaction": before_compaction_bytes,
            "database_freelist_pages_before_compaction": before_compaction_freelist_pages,
            "database_freelist_pages_after_compaction": after_compaction_freelist_pages,
            "database_bytes": output.stat().st_size,
            "seconds": round(time.time() - started, 1),
        }
        print(json.dumps(result, indent=2))
        return result
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        if temporary.exists():
            temporary.unlink()
        raise

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", type=Path, help="Optional JSON build summary path")
    args = parser.parse_args()
    try:
        result = build_database(args.archive, args.output)
        if args.summary:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, sqlite3.Error, tarfile.TarError, RuntimeError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
