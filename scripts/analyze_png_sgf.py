#!/usr/bin/env python3
"""Check whether every PNG diagram in the Sensei snapshot has a unique SGF source."""
from __future__ import annotations

import argparse
import html
import json
import posixpath
import tarfile
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup

HTML_EXTENSIONS = {".html", ".htm", ".xhtml", ".shtml"}
WIKI_HOSTS = {"senseis.xmp.net", "www.senseis.xmp.net"}


def safe_path(value: str) -> str | None:
    value = value.replace("\\", "/")
    if not value or value.startswith("/"):
        return None
    parts = PurePosixPath(value).parts
    if any(part in {"..", ""} for part in parts):
        return None
    normalized = posixpath.normpath(value).lstrip("./")
    return normalized if normalized not in {"", "."} and not normalized.startswith("../") else None


def looks_html(path: str, prefix: bytes) -> bool:
    sample = prefix[:2048].lstrip(bytes((239, 187, 191, 0, 9, 13, 10, 32))).lower()
    return (
        sample.startswith((b"<!doctype html", b"<html", b"<?xml"))
        or b"<html" in sample[:512]
        or PurePosixPath(path).suffix.lower() in HTML_EXTENSIONS
    )


def resolve_local(raw_url: str, page_path: str, known_paths: set[str], casefold_paths: dict[str, list[str]]) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(html.unescape(raw_url.strip()))
    except ValueError:
        return None
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        return None
    if parsed.netloc and (parsed.hostname or "").lower() not in WIKI_HOSTS:
        return None
    raw_path = urllib.parse.unquote(parsed.path or "").replace("\\\\", "/")
    if not raw_path:
        return None
    candidates = [raw_path.lstrip("/")] if raw_path.startswith("/") else [
        posixpath.normpath(posixpath.join(posixpath.dirname(page_path), raw_path)),
        raw_path,
    ]
    for candidate in candidates:
        normalized = safe_path(candidate)
        if normalized and normalized in known_paths:
            return normalized
        if normalized:
            matches = casefold_paths.get(normalized.casefold(), [])
            if len(matches) == 1:
                return matches[0]
    return None


def analyze_archive(archive: Path, report_path: Path | None = None) -> dict:
    paths: set[str] = set()
    extensions: Counter[str] = Counter()
    with tarfile.open(archive, mode="r|bz2") as tar:
        for member in tar:
            if not member.isfile():
                continue
            path = safe_path(member.name)
            if path is None:
                continue
            paths.add(path)
            extension = PurePosixPath(path).suffix.lower() or "[no extension]"
            extensions[extension] += 1

    png_paths = {path for path in paths if path.lower().endswith(".png")}
    sgf_paths = {path for path in paths if path.lower().endswith(".sgf")}
    pairs = []
    unmatched_pngs = []
    invalid_names = []
    for png in sorted(png_paths):
        stem = png[:-4]
        if len(PurePosixPath(stem).name) != 32 or any(c not in "0123456789abcdefABCDEF" for c in PurePosixPath(stem).name):
            invalid_names.append(png)
            continue
        sgf = stem + ".sgf"
        if sgf in sgf_paths:
            pairs.append({"png": png, "sgf": sgf})
        else:
            unmatched_pngs.append(png)

    paired_pngs = {item["png"] for item in pairs}
    report = {
        "archive": archive.name,
        "files_scanned": len(paths),
        "png_files": len(png_paths),
        "sgf_files": len(sgf_paths),
        "png_sgf_pairs": len(pairs),
        "png_files_with_matching_sgf": len(paired_pngs),
        "png_files_without_matching_sgf": len(unmatched_pngs),
        "png_files_with_invalid_code_name": len(invalid_names),
        "all_pngs_have_matching_sgf": len(pairs) + len(unmatched_pngs) + len(invalid_names) == len(png_paths)
            and not unmatched_pngs and not invalid_names,
        "extension_counts": extensions.most_common(40),
        "unmatched_png_examples": unmatched_pngs[:100],
        "invalid_png_name_examples": invalid_names[:100],
        "method": "Exact same relative path and 32-character hexadecimal basename; only extension differs (.png versus .sgf).",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = analyze_archive(args.archive, args.report)
    print(json.dumps({key: value for key, value in report.items() if not key.endswith("_examples")}, ensure_ascii=False, indent=2))
    print(f"Report written: {args.report}")


if __name__ == "__main__":
    main()
