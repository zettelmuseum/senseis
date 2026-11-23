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
    sample = prefix[:2048].lstrip(b"\\xef\\xbb\\xbf\\x00\\t\\r\\n ").lower()
    return (
        sample.startswith((b"<!doctype html", b"<html", b"<?xml"))
        or b"<html" in sample[:512]
        or PurePosixPath(path).suffix.lower() in HTML_EXTENSIONS
    )


def resolve_local(raw_url: str, page_path: str, known_paths: set[str]) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(html.unescape(raw_url.strip()))
    except ValueError:
        return None
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        return None
    if parsed.netloc and (parsed.hostname or "").lower() not in WIKI_HOSTS:
        return None
    raw_path = urllib.parse.unquote(parsed.path or "").replace("\\", "/")
    if not raw_path:
        return None
    if raw_path.startswith("/"):
        candidates = [raw_path.lstrip("/")]
    else:
        candidates = [
            posixpath.normpath(posixpath.join(posixpath.dirname(page_path), raw_path)),
            raw_path,
        ]
    for candidate in candidates:
        normalized = safe_path(candidate)
        if normalized in known_paths:
            return normalized
        if normalized:
            folded = normalized.casefold()
            matches = [path for path in known_paths if path.casefold() == folded]
            if len(matches) == 1:
                return matches[0]
    return None


def analyze_archive(archive: Path, report_path: Path | None = None) -> dict:
    paths: set[str] = set()
    html_members: list[tuple[str, bytes]] = []
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
            stream = tar.extractfile(member)
            if stream is None:
                continue
            with stream:
                prefix = stream.read(2048)
                if looks_html(path, prefix):
                    html_members.append((path, prefix + stream.read()))

    png_paths = {path for path in paths if path.lower().endswith(".png")}
    sgf_paths = {path for path in paths if path.lower().endswith(".sgf")}
    candidates: dict[str, set[str]] = defaultdict(set)
    reasons: dict[tuple[str, str], set[str]] = defaultdict(set)
    png_references: Counter[str] = Counter()
    sgf_references: Counter[str] = Counter()
    page_pair_count = 0
    ambiguous_pages = []

    # Strong filename evidence: identical path stem, including directory.
    sgf_by_stem: dict[str, set[str]] = defaultdict(set)
    for sgf in sgf_paths:
        sgf_by_stem[sgf[:-4].casefold()].add(sgf)
    for png in png_paths:
        stem = png[:-4].casefold()
        matches = sgf_by_stem.get(stem, set())
        if len(matches) == 1:
            sgf = next(iter(matches))
            candidates[png].add(sgf)
            reasons[(png, sgf)].add("same_path_stem")
        elif len(matches) > 1:
            for sgf in matches:
                candidates[png].add(sgf)
                reasons[(png, sgf)].add("duplicate_casefolded_stem")

    for page_path, data in html_members:
        soup = BeautifulSoup(data, "html.parser")
        page_pngs = set()
        page_sgfs = set()
        for tag in soup.find_all(["img", "source"]):
            for attr in ("src", "data-src", "data-original"):
                raw = tag.get(attr)
                if raw:
                    resolved = resolve_local(str(raw), page_path, paths)
                    if resolved in png_paths:
                        page_pngs.add(resolved)
                        png_references[resolved] += 1
        for tag in soup.find_all("a", href=True):
            raw = str(tag.get("href", ""))
            parsed = urllib.parse.urlsplit(html.unescape(raw))
            if not parsed.path.lower().endswith(".sgf"):
                continue
            resolved = resolve_local(raw, page_path, paths)
            if resolved in sgf_paths:
                page_sgfs.add(resolved)
                sgf_references[resolved] += 1
        if len(page_pngs) == 1 and len(page_sgfs) == 1:
            png = next(iter(page_pngs))
            sgf = next(iter(page_sgfs))
            candidates[png].add(sgf)
            reasons[(png, sgf)].add("sole_png_and_sgf_on_same_page")
            page_pair_count += 1
        elif page_pngs and page_sgfs:
            ambiguous_pages.append({
                "page": page_path,
                "png_count": len(page_pngs),
                "sgf_count": len(page_sgfs),
                "png_examples": sorted(page_pngs)[:5],
                "sgf_examples": sorted(page_sgfs)[:5],
            })

    reverse: dict[str, set[str]] = defaultdict(set)
    for png, sgfs in candidates.items():
        for sgf in sgfs:
            reverse[sgf].add(png)

    unique_pairs = []
    ambiguous_pngs = []
    unmatched_pngs = []
    for png in sorted(png_paths):
        sgfs = candidates.get(png, set())
        if len(sgfs) == 1:
            sgf = next(iter(sgfs))
            if len(reverse[sgf]) == 1:
                unique_pairs.append({"png": png, "sgf": sgf, "evidence": sorted(reasons[(png, sgf)])})
            else:
                ambiguous_pngs.append({"png": png, "sgf_candidates": [sgf], "reason": "multiple_pngs_point_to_same_sgf"})
        elif len(sgfs) > 1:
            ambiguous_pngs.append({"png": png, "sgf_candidates": sorted(sgfs), "reason": "multiple_sgf_candidates"})
        else:
            unmatched_pngs.append(png)

    uniquely_mapped_pngs = {item["png"] for item in unique_pairs}
    unique_sgfs = {item["sgf"] for item in unique_pairs}
    report = {
        "archive": archive.name,
        "files_scanned": len(paths),
        "html_pages_scanned": len(html_members),
        "png_files": len(png_paths),
        "sgf_files": len(sgf_paths),
        "png_files_referenced_from_html": len(png_references),
        "sgf_files_linked_from_html": len(sgf_references),
        "pages_with_exactly_one_png_and_one_sgf": page_pair_count,
        "unique_one_to_one_pairs": len(unique_pairs),
        "uniquely_mapped_pngs": len(uniquely_mapped_pngs),
        "pngs_ambiguous": len(ambiguous_pngs),
        "pngs_unmatched": len(unmatched_pngs),
        "sgfs_used_by_unique_pairs": len(unique_sgfs),
        "all_pngs_uniquely_mapped": len(unique_pairs) == len(png_paths),
        "extension_counts": extensions.most_common(40),
        "unique_pairs_examples": unique_pairs[:100],
        "ambiguous_png_examples": ambiguous_pngs[:100],
        "unmatched_png_examples": unmatched_pngs[:100],
        "ambiguous_page_examples": ambiguous_pages[:100],
        "method": [
            "same exact relative path stem (.png versus .sgf)",
            "or exactly one resolvable PNG and exactly one resolvable SGF link on the same HTML page",
            "a mapping is accepted only if it is one-to-one in both directions",
        ],
        "caution": "A one-PNG/one-SGF page is structural evidence, not proof that the SGF reproduces the exact pixels. Visual equivalence must be checked before replacing all diagrams.",
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
