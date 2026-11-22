#!/usr/bin/env python3
"""Extract only a bounded sample of HTML members and report the snapshot page structure."""
from __future__ import annotations

import argparse
import json
import posixpath
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup

HTML_EXTENSIONS = {".html", ".htm", ".xhtml", ".shtml"}


def safe_name(name: str) -> str | None:
    name = name.replace("\\", "/")
    if not name or name.startswith("/"):
        return None
    parts = PurePosixPath(name).parts
    if any(part == ".." for part in parts):
        return None
    result = posixpath.normpath(name).lstrip("./")
    if result in {"", "."} or result.startswith("../"):
        return None
    return result


def looks_html(name: str, prefix: bytes) -> bool:
    head = prefix[:2048].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    if head.startswith((b"<!doctype html", b"<html", b"<?xml")) or b"<html" in head[:512]:
        return True
    return PurePosixPath(name).suffix.lower() in HTML_EXTENSIONS


def inspect_archive(archive: Path, output_dir: Path, max_members: int, max_pages: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stats: Counter[str] = Counter()
    page_examples = []
    extensions: Counter[str] = Counter()
    with tarfile.open(archive, mode="r|bz2") as tar:
        for member in tar:
            stats["members_scanned"] += 1
            if stats["members_scanned"] > max_members:
                break
            if not member.isfile():
                continue
            path = safe_name(member.name)
            if path is None:
                stats["unsafe_members_skipped"] += 1
                continue
            extension = PurePosixPath(path).suffix.lower() or "[no extension]"
            extensions[extension] += 1
            # Only HTML pages are written to the sample directory. Other
            # members are streamed past without creating an extracted file.
            stream = tar.extractfile(member)
            if stream is None:
                continue
            with stream:
                prefix = stream.read(2048)
                if not looks_html(path, prefix):
                    continue
                data = prefix + stream.read()
            stats["html_detected"] += 1
            target = output_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            soup = BeautifulSoup(data, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            body = soup.body or soup
            anchors = body.find_all("a", href=True)
            images = body.find_all("img", src=True)
            sgf_links = [
                a for a in anchors
                if str(a.get("href", "")).lower().split("?", 1)[0].split("#", 1)[0].endswith(".sgf")
            ]
            page_examples.append({
                "path": path,
                "title": title[:180],
                "bytes": len(data),
                "anchors": len(anchors),
                "images": len(images),
                "sgf_links": len(sgf_links),
                "headings": len(body.find_all(["h1", "h2", "h3"])),
                "forms": len(body.find_all("form")),
                "scripts": len(body.find_all("script")),
            })
            stats["sampled_pages"] += 1
            if stats["sampled_pages"] >= max_pages:
                break
    if not page_examples:
        raise RuntimeError(
            f"No HTML pages found in the first {stats['members_scanned']:,} archive members. "
            "The snapshot layout may differ from the expected static HTML export; inspect the member listing."
        )
    return {
        **dict(stats),
        "max_members": max_members,
        "max_pages": max_pages,
        "extension_counts_in_scanned_prefix": extensions.most_common(30),
        "page_examples": page_examples[:20],
        "note": "Only sampled HTML pages were extracted; other archive members were streamed past, not written to disk.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sample-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--max-members", type=int, default=15000)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()
    if args.max_members < 1 or args.max_pages < 1:
        parser.error("--max-members and --max-pages must be positive")
    report = inspect_archive(args.archive, args.sample_dir, args.max_members, args.max_pages)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "page_examples"}, ensure_ascii=False, indent=2))
    print(f"Sample pages extracted: {report['sampled_pages']}; report: {args.report}")


if __name__ == "__main__":
    main()
