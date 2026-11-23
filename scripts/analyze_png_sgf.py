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
    page_references: list[tuple[str, list[str], list[str], list[tuple[str, str]]]] = []
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
                if not looks_html(path, prefix):
                    continue
                data = prefix + stream.read()
            soup = BeautifulSoup(data, "html.parser")
            image_urls = []
            for tag in soup.find_all(["img", "source"]):
                for attr in ("src", "data-src", "data-original"):
                    value = tag.get(attr)
                    if value:
                        image_urls.append(str(value))
            sgf_urls = []
            embedded_pairs = []
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href", ""))
                parsed = urllib.parse.urlsplit(html.unescape(href))
                if not parsed.path.lower().endswith(".sgf"):
                    continue
                sgf_urls.append(href)
                for image in anchor.find_all(["img", "source"]):
                    image_src = image.get("src") or image.get("data-src") or image.get("data-original")
                    if image_src:
                        embedded_pairs.append((str(image_src), href))
            page_references.append((path, image_urls, sgf_urls, embedded_pairs))

    casefold_paths: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        casefold_paths[path.casefold()].append(path)
    png_paths = {path for path in paths if path.lower().endswith(".png")}
    sgf_paths = {path for path in paths if path.lower().endswith(".sgf")}
    strong_candidates: dict[str, set[str]] = defaultdict(set)
    strong_reasons: dict[tuple[str, str], set[str]] = defaultdict(set)
    weak_candidates: dict[str, set[str]] = defaultdict(set)
    png_references: Counter[str] = Counter()
    sgf_references: Counter[str] = Counter()
    page_pair_count = 0
    ambiguous_pages = []

    # Strong filename evidence: identical relative path stem.
    sgf_by_stem: dict[str, set[str]] = defaultdict(set)
    for sgf in sgf_paths:
        sgf_by_stem[sgf[:-4].casefold()].add(sgf)
    for png in png_paths:
        matches = sgf_by_stem.get(png[:-4].casefold(), set())
        for sgf in matches:
            strong_candidates[png].add(sgf)
            strong_reasons[(png, sgf)].add("same_relative_path_stem")

    for page_path, image_urls, sgf_urls, embedded_pairs in page_references:
        page_pngs = set()
        page_sgfs = set()
        for raw in image_urls:
            resolved = resolve_local(raw, page_path, paths, casefold_paths)
            if resolved in png_paths:
                page_pngs.add(resolved)
                png_references[resolved] += 1
        for raw in sgf_urls:
            resolved = resolve_local(raw, page_path, paths, casefold_paths)
            if resolved in sgf_paths:
                page_sgfs.add(resolved)
                sgf_references[resolved] += 1
        # Strong structural evidence: the diagram image itself is wrapped in a link to the SGF.
        for image_url, sgf_url in embedded_pairs:
            png = resolve_local(image_url, page_path, paths, casefold_paths)
            sgf = resolve_local(sgf_url, page_path, paths, casefold_paths)
            if png in png_paths and sgf in sgf_paths:
                strong_candidates[png].add(sgf)
                strong_reasons[(png, sgf)].add("image_wrapped_by_sgf_link")
        # Weak evidence only: one image and one SGF link happen to share a page.
        if len(page_pngs) == 1 and len(page_sgfs) == 1:
            png = next(iter(page_pngs))
            sgf = next(iter(page_sgfs))
            weak_candidates[png].add(sgf)
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
    for png, sgfs in strong_candidates.items():
        for sgf in sgfs:
            reverse[sgf].add(png)

    unique_pairs = []
    ambiguous_pngs = []
    unmatched_pngs = []
    weak_only_pngs = []
    for png in sorted(png_paths):
        sgfs = strong_candidates.get(png, set())
        if len(sgfs) == 1:
            sgf = next(iter(sgfs))
            if len(reverse[sgf]) == 1:
                unique_pairs.append({"png": png, "sgf": sgf, "evidence": sorted(strong_reasons[(png, sgf)])})
            else:
                ambiguous_pngs.append({"png": png, "sgf_candidates": [sgf], "reason": "multiple_pngs_point_to_same_sgf"})
        elif len(sgfs) > 1:
            ambiguous_pngs.append({"png": png, "sgf_candidates": sorted(sgfs), "reason": "multiple_sgf_candidates"})
        elif weak_candidates.get(png):
            weak_only_pngs.append({"png": png, "page_level_sgf_candidates": sorted(weak_candidates[png])})
        else:
            unmatched_pngs.append(png)

    unique_pngs = {item["png"] for item in unique_pairs}
    unique_sgfs = {item["sgf"] for item in unique_pairs}
    report = {
        "archive": archive.name,
        "files_scanned": len(paths),
        "html_pages_scanned": len(page_references),
        "png_files": len(png_paths),
        "sgf_files": len(sgf_paths),
        "png_files_referenced_from_html": len(png_references),
        "sgf_files_linked_from_html": len(sgf_references),
        "pages_with_exactly_one_png_and_one_sgf": page_pair_count,
        "strong_unique_one_to_one_pairs": len(unique_pairs),
        "strong_uniquely_mapped_pngs": len(unique_pngs),
        "pngs_ambiguous_by_strong_evidence": len(ambiguous_pngs),
        "pngs_with_only_weak_same_page_evidence": len(weak_only_pngs),
        "pngs_with_no_sgf_candidate": len(unmatched_pngs),
        "sgfs_used_by_strong_unique_pairs": len(unique_sgfs),
        "all_pngs_have_strong_unique_sgf_mapping": len(unique_pairs) == len(png_paths),
        "extension_counts": extensions.most_common(40),
        "strong_unique_pairs_examples": unique_pairs[:100],
        "ambiguous_png_examples": ambiguous_pngs[:100],
        "weak_only_png_examples": weak_only_pngs[:100],
        "unmatched_png_examples": unmatched_pngs[:100],
        "ambiguous_page_examples": ambiguous_pages[:100],
        "method": [
            "strong: identical relative path stem (.png versus .sgf)",
            "strong: PNG is nested inside an HTML link to that exact SGF",
            "weak only: exactly one PNG and one SGF link occur on the same page; not accepted as a guaranteed mapping",
            "accepted mappings must be one-to-one in both directions",
        ],
        "caution": "Even a unique structural match does not prove that the SGF reproduces the exact PNG position. The SGF viewer must be checked against representative diagrams before image replacement.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
