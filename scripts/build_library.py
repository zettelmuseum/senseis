#!/usr/bin/env python3
"""Build a compact Sensei's Library archive: concatenated payloads + compressed directory."""
from __future__ import annotations
import argparse, hashlib, html, json, mimetypes, os, re, struct, tarfile, tempfile, time, zlib
from collections import Counter
from pathlib import Path, PurePosixPath

MAGIC = b"SLIBPK01"
VERSION = 1
HEADER = struct.Struct(">8sIIIII")
RECORD = struct.Struct(">HQQQI BH")
TEXT_EXTENSIONS = {".html",".htm",".xhtml",".shtml",".php",".css",".js",".txt",".xml",".json",".md",".csv",".svg"}
HTML_EXTENSIONS = {".html",".htm",".xhtml",".shtml"}
MAX_IMAGE_BYTES = 500 * 1024
TITLE_RE = re.compile(rb"<title\\b[^>]*>(.*?)</title\\s*>", re.I | re.S)
TAG_RE = re.compile(rb"<[^>]*>")
CHARSET_RE = re.compile(rb"<meta[^>]+charset\\s*=\\s*[\"']?([a-zA-Z0-9._-]+)", re.I)

def safe_path(name: str) -> str | None:
    name = name.replace("\\", "/")
    if not name or name.startswith("/"): return None
    parts = PurePosixPath(name).parts
    if any(p in ("..", "") for p in parts): return None
    value = "/".join(p for p in parts if p not in ("", "."))
    return value or None

def is_html(path: str, data: bytes) -> bool:
    sample = data[:2048].lstrip(b"\\xef\\xbb\\xbf\\x00\\t\\r\\n ").lower()
    return PurePosixPath(path).suffix.lower() in HTML_EXTENSIONS or sample.startswith((b"<!doctype html", b"<html", b"<?xml")) or b"<html" in sample[:512]

def page_title(data: bytes, path: str) -> str:
    m = TITLE_RE.search(data)
    if not m: return PurePosixPath(path).stem.replace("_", " ")[:300]
    cs = CHARSET_RE.search(data[:8192])
    enc = cs.group(1).decode("ascii", "ignore") if cs else "utf-8"
    try: raw = m.group(1).decode(enc, "replace")
    except LookupError: raw = m.group(1).decode("utf-8", "replace")
    return re.sub(r"\\s+", " ", html.unescape(TAG_RE.sub(b" ", raw.encode("utf-8", "replace")).decode("utf-8"))).strip()[:300]

def mime_for(path: str, html_file: bool) -> str:
    if html_file: return "text/html"
    if path.lower().endswith(".sgf"): return "application/x-go-sgf"
    if path.lower().endswith(".svg"): return "image/svg+xml"
    return mimetypes.guess_type(path)[0] or "application/octet-stream"

def build_database(archive: Path, output: Path, sgf_compression_report: Path | None = None) -> dict:
    if not archive.is_file() or not archive.stat().st_size: raise RuntimeError(f"Snapshot archive missing: {archive}")
    started = time.time(); counts = Counter(); extstats = {}
    compress_sgf = False
    if sgf_compression_report and sgf_compression_report.is_file():
        compress_sgf = bool(json.loads(sgf_compression_report.read_text("utf-8")).get("recommended", False))
    output.parent.mkdir(parents=True, exist_ok=True)
    payload_tmp = output.with_suffix(output.suffix + ".payload")
    final_tmp = output.with_suffix(output.suffix + ".part")
    entries = []
    try:
        with payload_tmp.open("wb") as payload, tarfile.open(archive, "r|bz2") as tar:
            for member in tar:
                counts["members_seen"] += 1
                if not member.isfile(): continue
                path = safe_path(member.name)
                if path is None: counts["unsafe_or_empty"] += 1; continue
                name = PurePosixPath(path).name
                if path.lower().endswith(".png") and len(name)==36 and name[32:].lower()==".png" and re.fullmatch(r"[0-9a-fA-F]{32}",name[:32]):
                    counts["diagram_pngs_skipped"] += 1; counts["diagram_png_bytes_skipped"] += member.size; continue
                src = tar.extractfile(member)
                if src is None: continue
                with src: raw = src.read()
                html_file = is_html(path, raw); mime = mime_for(path, html_file)
                if mime.startswith("image/") and len(raw) > MAX_IMAGE_BYTES:
                    counts["images_removed"] += 1; counts["image_bytes_removed"] += len(raw); continue
                suffix = PurePosixPath(path).suffix.lower() or "[no extension]"
                stat = extstats.setdefault(suffix, {"files":0,"original_bytes":0,"stored_payload_bytes":0,"compressed_files":0})
                stat["files"] += 1; stat["original_bytes"] += len(raw)
                packed = raw; flags = 2 if html_file else 0
                if len(raw) >= 256 and (suffix in TEXT_EXTENSIONS or (suffix==".sgf" and compress_sgf)):
                    candidate = zlib.compress(raw, 6)
                    if len(candidate)+16 < len(raw): packed=candidate; flags |= 1; stat["compressed_files"] += 1
                offset = payload.tell(); payload.write(packed)
                stat["stored_payload_bytes"] += len(packed)
                title = page_title(raw, path) if html_file else ""
                p = path.encode("utf-8"); t = title.encode("utf-8")
                if len(p)>65535 or len(t)>65535: raise RuntimeError("Path/title too long for directory format")
                entries.append((path, title, offset, len(packed), len(raw), zlib.crc32(raw)&0xffffffff, flags))
                counts["files"] += 1; counts["bytes_original"] += len(raw)
                counts["html_files"] += int(html_file); counts["sgf_files"] += int(path.lower().endswith(".sgf"))
                if counts["files"] % 10000 == 0: print(f"Packed {counts['files']:,} files", flush=True)
        if not entries: raise RuntimeError("No regular files found in snapshot")
        # A tiny built-in landing page; no database metadata or aliases are stored.
        home = b"<!doctype html><html><head><meta charset='utf-8'><title>Sensei's Library - Offline</title></head><body><h1>Sensei's Library</h1><p>Offline snapshot.</p><p>Use Search in the app toolbar to find a page.</p></body></html>"
        homepath="__senseis_home__.html"; homeoffset=payload_tmp.stat().st_size
        with payload_tmp.open("ab") as payload: payload.write(home)
        entries.append((homepath,"Sensei's Library - Offline",homeoffset,len(home),len(home),zlib.crc32(home)&0xffffffff,2))
        entries.sort(key=lambda x:x[0].casefold())
        raw_index=bytearray()
        for path,title,offset,stored,original,crc,flags in entries:
            p=path.encode("utf-8"); t=title.encode("utf-8")
            raw_index += RECORD.pack(len(p),offset,stored,original,crc,flags,len(t))
            raw_index += p+t
        compressed_index=zlib.compress(bytes(raw_index),9)
        header=HEADER.pack(MAGIC,VERSION,len(entries),len(raw_index),len(compressed_index),zlib.crc32(raw_index)&0xffffffff)
        with final_tmp.open("wb") as out, compressed_index and payload_tmp.open("rb") as payload:
            out.write(header); out.write(compressed_index)
            while True:
                block=payload.read(1024*1024)
                if not block: break
                out.write(block)
        os.replace(final_tmp,output)
        result={
            "format":"SLIBPK01","format_version":VERSION,"files":len(entries),
            "pages":counts["html_files"]+1,"sgf_files":counts["sgf_files"],
            "uncompressed_bytes":counts["bytes_original"]+len(home),
            "payload_bytes":payload_tmp.stat().st_size,"directory_uncompressed_bytes":len(raw_index),
            "directory_compressed_bytes":len(compressed_index),"directory_entries":len(entries),
            "directory_alias_entries":0,"file_type_storage":dict(sorted(extstats.items(),key=lambda x:x[1]["stored_payload_bytes"],reverse=True)),
            "images_removed":counts["images_removed"],"image_bytes_removed":counts["image_bytes_removed"],
            "diagram_pngs_skipped":counts["diagram_pngs_skipped"],"diagram_png_bytes_skipped":counts["diagram_png_bytes_skipped"],
            "sgf_compression_enabled":int(compress_sgf),"archive_bytes":output.stat().st_size,
            "seconds":round(time.time()-started,1)
        }
        print(json.dumps(result,indent=2)); return result
    finally:
        for p in (payload_tmp,final_tmp):
            try: p.unlink()
            except FileNotFoundError: pass

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",required=True,type=Path); parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--summary",type=Path); parser.add_argument("--sgf-compression-report",type=Path)
    args=parser.parse_args()
    result=build_database(args.archive,args.output,args.sgf_compression_report)
    if args.summary:
        args.summary.parent.mkdir(parents=True,exist_ok=True); args.summary.write_text(json.dumps(result,indent=2)+"\\n","utf-8")
if __name__=="__main__": main()
