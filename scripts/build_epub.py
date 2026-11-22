#!/usr/bin/env python3
"""Convert the Sensei's Library HTML snapshot into a linked EPUB 3 book."""
from __future__ import annotations

import argparse
import hashlib
import html
import mimetypes
import posixpath
import re
import shutil
import tarfile
import tempfile
import urllib.parse
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from ebooklib import epub

SNAPSHOT_URL = "https://senseis.xmp.net/files/snapshots/senseis-library.tar.bz2"
WIKI_HOSTS = {"senseis.xmp.net", "www.senseis.xmp.net"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class Page:
    source: Path
    rel: str
    title: str
    uid: str
    filename: str
    soup: BeautifulSoup
    item: epub.EpubHtml | None = None


def digest(value: str, size: int = 10) -> str:
    return hashlib.sha1(value.encode("utf-8", "replace")).hexdigest()[:size]


def slug(value: str, limit: int = 64) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    return (value[:limit].rstrip("-._") or "page")


def key(value: str) -> str:
    value = urllib.parse.unquote_plus(value).replace("\\", "/").strip()
    return re.sub(r"/+", "/", value).strip("./").strip("/").casefold()


def extract_snapshot(archive: Path, root: Path) -> int:
    """Safely extract regular files only; reject absolute and traversal paths."""
    root.mkdir(parents=True, exist_ok=True)
    base = root.resolve()
    count = 0
    try:
        with tarfile.open(archive, "r:bz2") as tar:
            for member in tar:
                if not member.isfile() or member.name.startswith("/"):
                    continue
                target = (base / member.name.replace("\\", "/")).resolve()
                try:
                    target.relative_to(base)
                except ValueError:
                    continue
                stream = tar.extractfile(member)
                if stream is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream, target.open("wb") as out:
                    shutil.copyfileobj(stream, out)
                count += 1
    except (OSError, tarfile.TarError) as exc:
        raise RuntimeError(f"Cannot extract snapshot: {exc}") from exc
    if count == 0:
        raise RuntimeError("Snapshot archive contains no regular files.")
    return count


def get_pages(root: Path) -> tuple[list[Page], dict[str, Page]]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".html", ".htm", ".xhtml", ".shtml"}:
            files.append(path)
        elif not path.suffix:
            try:
                head = path.open("rb").read(512).lstrip().lower()
            except OSError:
                continue
            if head.startswith((b"<!doctype html", b"<html", b"<?xml")):
                files.append(path)
    files.sort(key=lambda p: p.relative_to(root).as_posix().casefold())
    if not files:
        sample = [p.relative_to(root).as_posix() for p in list(root.rglob("*"))[:20] if p.is_file()]
        raise RuntimeError(f"No HTML pages found in snapshot. Extracted file examples: {sample}")

    pages, aliases = [], {}
    for source in files:
        rel = source.relative_to(root).as_posix()
        soup = BeautifulSoup(source.read_bytes(), "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        title = re.sub(r"^Sensei['’]s Library\\s*[:|–—-]\\s*", "", title, flags=re.I)
        title = re.sub(r"\\s*[|–—-]\\s*Sensei['’]s Library\\s*$", "", title, flags=re.I)
        if not title:
            heading = soup.find(["h1", "h2"])
            title = heading.get_text(" ", strip=True) if heading else source.stem.replace("_", " ")
        title = title[:300] or source.name
        filename = f"pages/{slug(source.stem)}-{digest(rel)}.xhtml"
        page = Page(source, rel, title, f"page-{digest(rel, 16)}", filename, soup)
        pages.append(page)
        for alias in (rel, rel.removesuffix(source.suffix), source.name, source.stem, title,
                      urllib.parse.quote(rel), urllib.parse.quote(title)):
            aliases.setdefault(key(alias), page)
    return pages, aliases


def resolve_page(href: str, current: Page, aliases: dict[str, Page]):
    parsed = urllib.parse.urlsplit(href)
    host = (parsed.hostname or "").lower()
    same_wiki = (not parsed.scheme and not parsed.netloc) or host in WIKI_HOSTS
    if not same_wiki:
        return None, parsed.fragment, False
    candidates = []
    if parsed.query:
        raw = parsed.query.split("&", 1)[0]
        candidates.append(raw)
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            if v:
                candidates.append(v)
            if k and k.lower() not in {"page", "title", "action", "view"}:
                candidates.append(k)
    if parsed.path and parsed.path != "/":
        path = urllib.parse.unquote(parsed.path)
        candidates += [path, path.lstrip("/")]
        if path.lower().endswith((".html", ".htm", ".xhtml")):
            candidates.append(path.rsplit(".", 1)[0])
        else:
            candidates += [path + ".html", path + ".htm"]
        if not path.startswith("/"):
            candidates.append(posixpath.normpath(posixpath.join(posixpath.dirname(current.rel), path)))
    for candidate in candidates:
        found = aliases.get(key(candidate))
        if found:
            return found, parsed.fragment, True
    return None, parsed.fragment, same_wiki


def local_asset(raw: str, page: Page, root: Path, basename_index: dict[str, list[Path]]) -> Path | None:
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        if (parsed.hostname or "").lower() not in WIKI_HOSTS:
            return None
    decoded = urllib.parse.unquote(parsed.path).replace("\\", "/")
    if not decoded:
        return None
    choices = [root / decoded.lstrip("/")] if decoded.startswith("/") else [page.source.parent / decoded, root / decoded]
    for candidate in choices:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root.resolve())
            if resolved.is_file():
                return resolved
        except (OSError, ValueError):
            pass
    found = basename_index.get(Path(decoded).name.casefold(), [])
    return found[0] if len(found) == 1 else None


def rel_href(source: str, target: str) -> str:
    return posixpath.relpath(target, posixpath.dirname(source) or ".")


def rewrite_page(page: Page, root: Path, aliases: dict[str, Page], basename_index: dict[str, list[Path]],
                 book: epub.EpubBook, assets: dict[Path, epub.EpubItem]) -> str:
    soup = page.soup
    for node in soup.find_all(["script", "noscript", "base"]):
        node.decompose()
    body = soup.body or soup
    for node in body.find_all(attrs={"name": True}):
        if not node.get("id"):
            node["id"] = node.get("name")

    for anchor in body.find_all(href=True):
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        target, fragment, same_wiki = resolve_page(href, page, aliases)
        if target:
            out = rel_href(page.filename, target.filename)
            if fragment:
                out += "#" + urllib.parse.quote(urllib.parse.unquote(fragment), safe="-._~:@!$&'()*+,;=/?")
            anchor["href"] = out
        elif same_wiki:
            parsed = urllib.parse.urlsplit(href)
            if parsed.scheme and parsed.netloc:
                anchor["href"] = href
            elif parsed.query:
                anchor["href"] = "https://senseis.xmp.net/?" + parsed.query
            else:
                anchor["href"] = urllib.parse.urljoin("https://senseis.xmp.net/", href)
            if fragment and "#" not in anchor["href"]:
                anchor["href"] += "#" + fragment

    for image in body.find_all(["img", "image"]):
        attr = "href" if image.name == "image" and image.has_attr("href") else "src"
        raw = image.get(attr)
        if not raw:
            continue
        found = local_asset(str(raw), page, root, basename_index)
        if found is None or found.suffix.lower() not in IMAGE_EXTS:
            continue
        item = assets.get(found)
        if item is None:
            relative = found.relative_to(root).as_posix()
            suffix = found.suffix.lower()
            media = "image/svg+xml" if suffix == ".svg" else (mimetypes.guess_type(found.name)[0] or "application/octet-stream")
            item = epub.EpubItem(uid=f"asset-{digest(relative, 16)}",
                                 file_name=f"assets/{slug(found.stem, 55)}-{digest(relative)}{suffix}",
                                 media_type=media, content=found.read_bytes())
            book.add_item(item)
            assets[found] = item
        image[attr] = rel_href(page.filename, item.file_name)

    output = []
    for node in list(body.contents):
        if isinstance(node, NavigableString):
            output.append(html.escape(str(node)))
        elif isinstance(node, Tag):
            output.append(node.decode(formatter="xml"))
    return "\n".join(output)


def make_index(filename: str, title: str, pages: list[Page], home: bool = False) -> epub.EpubHtml:
    item = epub.EpubHtml(title=title, file_name=filename, lang="en")
    if home:
        groups: dict[str, list[Page]] = defaultdict(list)
        for page in pages:
            letter = page.title[:1].upper()
            groups[letter if letter.isascii() and letter.isalpha() else "#"].append(page)
        lines = ["<h1>Sensei's Library</h1>", "<p>Offline snapshot — choose an initial letter.</p>", "<ul>"]
        for letter in sorted(groups, key=lambda x: (x == "#", x)):
            label = "Other" if letter == "#" else letter
            lines.append(f'<li><a href="index-{slug(letter)}.xhtml">{html.escape(label)} ({len(groups[letter]):,})</a></li>')
        lines.append("</ul>")
    else:
        lines = [f"<h1>{html.escape(title)}</h1>", '<p><a href="index.xhtml">Back to index</a></p>', "<ol>"]
        for page in pages:
            lines.append(f'<li><a href="{html.escape(rel_href(filename, page.filename), quote=True)}">{html.escape(page.title)}</a></li>')
        lines.append("</ol>")
    item.content = "\n".join(lines)
    return item


def validate_epub(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None or archive.read("mimetype") != b"application/epub+zip":
            raise RuntimeError("The generated EPUB failed ZIP/mimetype validation.")
        names = set(archive.namelist())
        if "EPUB/content.opf" not in names:
            raise RuntimeError("The generated EPUB has no package document.")
        for name in names:
            if not name.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            soup = BeautifulSoup(archive.read(name), "html.parser")
            for node in soup.find_all(href=True):
                link = urllib.parse.urlsplit(str(node.get("href", "")))
                if link.scheme or link.netloc or not link.path:
                    continue
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), urllib.parse.unquote(link.path)))
                if target not in names:
                    raise RuntimeError(f"Broken internal EPUB link: {name} -> {link.path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.archive.is_file():
        raise SystemExit(f"Snapshot not found: {args.archive}")

    with tempfile.TemporaryDirectory(prefix="senseis-") as temp:
        root = Path(temp) / "snapshot"
        extracted = extract_snapshot(args.archive, root)
        pages, aliases = get_pages(root)
        book = epub.EpubBook()
        book.set_identifier("senseis-library-" + digest(SNAPSHOT_URL, 16))
        book.set_title("Sensei's Library")
        book.set_language("en")
        book.add_metadata("DC", "source", SNAPSHOT_URL)
        book.add_metadata("DC", "description", "Offline EPUB converted from the Sensei's Library snapshot.")
        css = "body{font-family:serif;line-height:1.45;margin:4%}img,svg{max-width:100%;height:auto}table{border-collapse:collapse;max-width:100%}td,th{vertical-align:top;padding:.2em}pre,code{white-space:pre-wrap;overflow-wrap:anywhere}"
        book.add_item(epub.EpubItem(uid="senseis-style", file_name="styles/senseis.css", media_type="text/css", content=css.encode()))
        basenames: dict[str, list[Path]] = defaultdict(list)
        page_sources = {p.source.resolve() for p in pages}
        for path in root.rglob("*"):
            if path.is_file() and path.resolve() not in page_sources:
                basenames[path.name.casefold()].append(path.resolve())
        assets: dict[Path, epub.EpubItem] = {}
        for page in pages:
            item = epub.EpubHtml(title=page.title, file_name=page.filename, lang="en")
            item.content = rewrite_page(page, root, aliases, basenames, book, assets)
            item.add_link(href="../styles/senseis.css", rel="stylesheet", type="text/css")
            page.item = item
            book.add_item(item)

        pages.sort(key=lambda p: (p.title.casefold(), p.rel.casefold()))
        groups: dict[str, list[Page]] = defaultdict(list)
        for page in pages:
            first = page.title[:1].upper()
            groups[first if first.isascii() and first.isalpha() else "#"].append(page)
        home = make_index("index.xhtml", "Alphabetical index", pages, home=True)
        book.add_item(home)
        index_pages = []
        toc = [epub.Link("index.xhtml", "Alphabetical index", "senseis-index")]
        for letter in sorted(groups, key=lambda x: (x == "#", x)):
            label = "Other" if letter == "#" else letter
            index = make_index(f"index-{slug(letter)}.xhtml", label, groups[letter])
            book.add_item(index)
            index_pages.append(index)
            toc.append(epub.Link(index.file_name, label, f"index-{slug(letter)}"))
        book.toc = tuple(toc)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", home, *index_pages, *(p.item for p in pages if p.item)]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(args.output), book, {})
        validate_epub(args.output)
        page_count, image_count = len(pages), len(assets)

    print(f"Extracted files: {extracted}")
    print(f"Wiki pages: {page_count}")
    print(f"Embedded images: {image_count}")
    print(f"EPUB: {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"ERROR: {error}") from error
