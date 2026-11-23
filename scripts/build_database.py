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
WIKI_HOSTS = {"senseis.xmp.net", "www.senseis.xmp.net", "senseis.local"}
HTML_EXTENSIONS = {".html", ".htm", ".xhtml", ".shtml"}
TEXT_EXTENSIONS = {".html", ".htm", ".xhtml", ".shtml", ".php", ".css", ".js", ".txt", ".xml", ".json", ".sgf", ".md", ".csv", ".svg"}
SCHEMA_VERSION = 3
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


def resolve_internal_target(conn: sqlite3.Connection, href: str, current_path: str) -> tuple[str | None, str, bool]:
    """Resolve a snapshot URL to a stored archive path; return (path, fragment, same-site)."""
    try:
        parsed = urllib.parse.urlsplit(href)
    except ValueError:
        return None, "", False
    host = (parsed.hostname or "").lower()
    same_site = (not parsed.scheme and not parsed.netloc) or host in WIKI_HOSTS
    if not same_site:
        return None, parsed.fragment, False

    # PmWiki-style links commonly use /?Group.Page or ?Group.Page.
    query_candidates: list[str] = []
    if parsed.query:
        query_candidates.append(parsed.query)
        for qkey, qvalue in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            if qvalue:
                query_candidates.append(qvalue)
            if qkey and qkey.lower() not in {"action", "n", "page", "title", "q", "query", "url"}:
                query_candidates.append(qkey)
    for candidate in query_candidates:
        path = lookup_alias(conn, candidate)
        if path:
            return path, parsed.fragment, True

    raw_path = urllib.parse.unquote(parsed.path or "")
    if raw_path in {"", "/"}:
        return None, parsed.fragment, True
    raw_path = raw_path.replace("\\", "/")
    candidates: list[str] = []
    if raw_path.startswith("/"):
        candidates.append(raw_path.lstrip("/"))
    else:
        candidates.append(posixpath.normpath(posixpath.join(posixpath.dirname(current_path), raw_path)))
        candidates.append(raw_path)
    for candidate in list(candidates):
        normalized = posixpath.normpath(candidate).lstrip("./")
        if normalized and not normalized.startswith("../"):
            candidates.append(normalized)
            if not PurePosixPath(normalized).suffix:
                candidates.extend(normalized + ext for ext in (".html", ".htm", ".xhtml"))
    for candidate in candidates:
        candidate = candidate.lstrip("/")
        row = conn.execute("SELECT path FROM files WHERE path = ?", (candidate,)).fetchone()
        if row:
            return row[0], parsed.fragment, True
        alias = lookup_alias(conn, candidate)
        if alias:
            return alias, parsed.fragment, True
        alias = lookup_alias(conn, PurePosixPath(candidate).name)
        if alias:
            return alias, parsed.fragment, True
    return None, parsed.fragment, True


def local_url(path: str, fragment: str = "") -> str:
    encoded = "/" + urllib.parse.quote(path, safe="/!$&'()*+,;=:@-._~")
    if fragment:
        encoded += "#" + urllib.parse.quote(urllib.parse.unquote(fragment), safe="-._~:@!$&'()*+,;=/?")
    return encoded


SGF_VIEWER_JS = r"""
(function(){
function prop(n,k){return n.p[k]||[];}
function parseSgf(s){
 var i=0;
 function skip(){while(i<s.length&&/\s/.test(s[i]))i++;}
 function value(){
  i++;var out="";
  while(i<s.length&&s[i]!=="]"){
   if(s[i]==="\\"){i++;if(i<s.length){if(s[i]==="\r"){i++;if(s[i]==="\n")i++;}else if(s[i]!=="\n")out+=s[i++];else i++;}}
   else out+=s[i++];
  }
  if(s[i]==="]")i++;return out;
 }
 function node(){
  i++;var p={};skip();
  while(i<s.length&&/[A-Z]/.test(s[i])){
   var k="";while(i<s.length&&/[A-Z]/.test(s[i]))k+=s[i++];
   var vals=[];skip();while(s[i]==="["){vals.push(value());skip();}
   p[k]=vals;
  }
  return {p:p,children:[]};
 }
 function tree(){
  skip();if(s[i]!=="(")return null;i++;skip();
  var first=null,last=null;
  while(i<s.length&&s[i]===";"){
   var n=node();if(!first)first=n;if(last)last.children.push(n);last=n;skip();
  }
  while(i<s.length&&s[i]==="("){
   var variation=tree();if(last&&variation)last.children.push(variation);skip();
  }
  if(s[i]===")")i++;
  return first;
 }
 while(i<s.length&&s[i]!=="(")i++;
 var root=tree(),line=[],n=root;
 while(n){line.push(n);n=n.children.length?n.children[0]:null;}
 return line;
}
function coord(v,size){if(!v||v.length<2)return null;var x=v.charCodeAt(0)-97,y=v.charCodeAt(1)-97;if(x<0||y<0||x>=size||y>=size)return null;return [x,y];}
function boardAt(line,upto,size){
 var b=new Array(size*size).fill(0);
 function group(x,y,color,seen){
  var stack=[[x,y]],stones=[],libs=false;
  while(stack.length){var q=stack.pop(),idx=q[1]*size+q[0];if(seen.has(idx))continue;seen.add(idx);stones.push(idx);
   var dirs=[[1,0],[-1,0],[0,1],[0,-1]];
   for(var d of dirs){var nx=q[0]+d[0],ny=q[1]+d[1];if(nx<0||ny<0||nx>=size||ny>=size)continue;var ni=ny*size+nx;if(!b[ni])libs=true;else if(b[ni]===color&&!seen.has(ni))stack.push([nx,ny]);}
  }return {stones:stones,liberty:libs};
 }
 for(var z=0;z<=upto&&z<line.length;z++){
  var p=line[z].p;
  if(z===0&&p.SZ&&p.SZ[0]){var parsed=parseInt(p.SZ[0].split(":")[0],10);if(parsed>=2&&parsed<=25&&parsed!==size)return boardAt(line,upto,parsed);}
  [["AB",1],["AW",2],["AE",0]].forEach(function(pair){(p[pair[0]]||[]).forEach(function(v){var c=coord(v,size);if(c)b[c[1]*size+c[0]]=pair[1];});});
  var mv=p.B?["B",1]:p.W?["W",2]:null;
  if(mv){var c=coord(p[mv[0]][0],size);if(c){var x=c[0],y=c[1],idx=y*size+x;b[idx]=mv[1];
   var dirs=[[1,0],[-1,0],[0,1],[0,-1]],seen=new Set();
   dirs.forEach(function(d){var nx=x+d[0],ny=y+d[1];if(nx<0||ny<0||nx>=size||ny>=size)return;var ni=ny*size+nx;if(b[ni]===3-mv[1]&&!seen.has(ni)){var g=group(nx,ny,3-mv[1],seen);if(!g.liberty)g.stones.forEach(function(k){b[k]=0;});}});
  }}
 }
 return b;
}
function draw(canvas,line,index,size){
 var ratio=window.devicePixelRatio||1,w=420,margin=24,step=(w-2*margin)/(size-1);
 canvas.width=w*ratio;canvas.height=w*ratio;canvas.style.width="100%";canvas.style.height="auto";
 var c=canvas.getContext("2d");c.scale(ratio,ratio);c.fillStyle="#d9ad68";c.fillRect(0,0,w,w);
 c.strokeStyle="#342719";c.lineWidth=1;
 for(var j=0;j<size;j++){var p=margin+j*step;c.beginPath();c.moveTo(margin,p);c.lineTo(w-margin,p);c.stroke();c.beginPath();c.moveTo(p,margin);c.lineTo(p,w-margin);c.stroke();}
 if(size===19){[3,9,15].forEach(function(y){[3,9,15].forEach(function(x){c.beginPath();c.arc(margin+x*step,margin+y*step,2.7,0,Math.PI*2);c.fillStyle="#342719";c.fill();});});}
 var b=boardAt(line,index,size);
 for(var y=0;y<size;y++)for(var x=0;x<size;x++){var v=b[y*size+x];if(!v)continue;var px=margin+x*step,py=margin+y*step,r=step*.46;
  c.beginPath();c.arc(px,py,r,0,Math.PI*2);c.fillStyle=v===1?"#111":"#f8f8f5";c.fill();c.strokeStyle="#222";c.lineWidth=1;c.stroke();
 }
 var last=line[index],m=last&&(last.p.B||last.p.W);if(m&&m[0]){var q=coord(m[0],size);if(q){c.beginPath();c.arc(margin+q[0]*step,margin+q[1]*step,step*.17,0,Math.PI*2);c.strokeStyle=m===last.p.B?"#fff":"#111";c.lineWidth=2;c.stroke();}}
}
function init(el){
 var path=el.getAttribute("data-sgf");
 el.innerHTML="<div class='sgfv-board'><canvas></canvas></div><div class='sgfv-controls'><button type='button' class='sgfv-prev'>‹</button><span class='sgfv-count'></span><button type='button' class='sgfv-next'>›</button></div>";
 var canvas=el.querySelector("canvas"),count=el.querySelector(".sgfv-count"),prev=el.querySelector(".sgfv-prev"),next=el.querySelector(".sgfv-next");
 fetch(path).then(function(r){if(!r.ok)throw new Error("SGF unavailable");return r.text();}).then(function(s){
  var line=parseSgf(s);if(!line.length)throw new Error("Empty SGF");
  var size=19;if(line[0].p.SZ&&line[0].p.SZ[0])size=parseInt(line[0].p.SZ[0].split(":")[0],10)||19;
  var index=line.length-1;
  function render(){draw(canvas,line,index,size);count.textContent=(index+1)+" / "+line.length;prev.disabled=index===0;next.disabled=index===line.length-1;}
  prev.addEventListener("click",function(){if(index>0){index--;render();}});
  next.addEventListener("click",function(){if(index<line.length-1){index++;render();}});
  render();
 }).catch(function(){el.textContent="SGF diagram unavailable";});
}
document.querySelectorAll(".senseis-sgf-viewer").forEach(init);
})();
"""

def paired_sgf_for_png(conn: sqlite3.Connection, png_path: str) -> str | None:
    if not png_path.lower().endswith(".png"):
        return None
    name = PurePosixPath(png_path).name
    code = name[:-4]
    if len(code) != 32 or not re.fullmatch(r"[0-9a-fA-F]{32}", code):
        return None
    sgf_path = png_path[:-4] + ".sgf"
    return sgf_path if conn.execute("SELECT 1 FROM files WHERE path=?", (sgf_path,)).fetchone() else None


def rewrite_html(conn: sqlite3.Connection, path: str, raw: bytes) -> tuple[bytes, str, str]:
    soup = BeautifulSoup(raw, "html.parser")
    # A snapshot may contain a live-site <base> element. Removing it ensures
    # every relative resource and navigation target stays under the app origin.
    for base in soup.find_all("base"):
        base.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if not title:
        heading = soup.find(["h1", "h2"])
        title = heading.get_text(" ", strip=True) if heading else PurePosixPath(path).stem.replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip()[:300] or PurePosixPath(path).name

    for tag in soup.find_all(href=True):
        href = str(tag.get("href", "")).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:", "blob:")):
            continue
        target, fragment, same_site = resolve_internal_target(conn, href, path)
        if target:
            sgf_path = paired_sgf_for_png(conn, target)
            if sgf_path:
                tag.attrs.pop("href", None)
                tag["title"] = "SGF diagram"
            else:
                tag["href"] = local_url(target, fragment)
        elif same_site:
            parsed = urllib.parse.urlsplit(href)
            # Keep an unresolved internal wiki reference local. The app renders a
            # useful offline "not included in this snapshot" page instead of sending
            # the reader to the live site.
            if parsed.query:
                tag["href"] = "/?" + parsed.query + (("#" + parsed.fragment) if parsed.fragment else "")
            elif parsed.path:
                tag["href"] = local_url(parsed.path.lstrip("/"), parsed.fragment)

    for tag in list(soup.find_all(src=True)):
        src = str(tag.get("src", "")).strip()
        if not src or src.startswith(("data:", "blob:", "javascript:")):
            continue
        target, fragment, same_site = resolve_internal_target(conn, src, path)
        if target:
            sgf_path = paired_sgf_for_png(conn, target)
            if sgf_path:
                viewer = soup.new_tag("div")
                viewer["class"] = "senseis-sgf-viewer"
                viewer["data-sgf"] = local_url(sgf_path)
                viewer["aria-label"] = str(tag.get("alt", "Go diagram"))
                tag.replace_with(viewer)
            else:
                tag["src"] = local_url(target, fragment)

    for tag in soup.find_all("a", href=True):
        target, _, _ = resolve_internal_target(conn, str(tag.get("href", "")), path)
        destination = target or ""
        if str(tag.get("href", "")).lower().split("#", 1)[0].split("?", 1)[0].lower().endswith(".sgf") or destination.lower().endswith(".sgf"):
            tag["data-senseis-sgf"] = "1"
            tag["download"] = PurePosixPath(destination or urllib.parse.urlsplit(str(tag.get("href", ""))).path).name or "game.sgf"
            tag["title"] = "Save SGF file"

    if soup.html is None:
        wrapped = BeautifulSoup("<!doctype html><html><head></head><body></body></html>", "html.parser")
        for node in list(soup.contents):
            wrapped.body.append(node)
        soup = wrapped
    if soup.head is None:
        soup.html.insert(0, soup.new_tag("head"))
    if not soup.head.find("meta", attrs={"name": "viewport"}):
        viewport = soup.new_tag("meta", attrs={"name": "viewport", "content": "width=device-width, initial-scale=1"})
        soup.head.append(viewport)
    style = soup.new_tag("style")
    style.string = "body{max-width:100%;margin:0 auto;padding:12px;line-height:1.45;overflow-wrap:anywhere}img,video,svg{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse;display:block;overflow-x:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere}.senseis-sgf-viewer{max-width:420px;margin:12px auto;background:#d9ad68;padding:4px;border:1px solid #80613c}.sgfv-controls{display:flex;align-items:center;justify-content:center;gap:20px;padding:5px;background:#eee}.sgfv-controls button{min-width:42px;min-height:36px;font-size:22px}.sgfv-controls span{font:13px sans-serif}"
    soup.head.append(style)
    bridge = soup.new_tag("script")
    bridge.string = SGF_VIEWER_JS + "(function(){document.addEventListener('click',function(e){var n=e.target;while(n&&n.tagName!=='A')n=n.parentNode;if(!n||!n.hasAttribute('data-senseis-sgf'))return;e.preventDefault();if(window.SenseiBridge&&window.SenseiBridge.saveSgf)window.SenseiBridge.saveSgf(n.getAttribute('href'));},true);})();"
    (soup.body or soup.html).append(bridge)

    body = soup.body or soup
    search_text = re.sub(r"\s+", " ", body.get_text(" ", strip=True)).strip()
    return str(soup).encode("utf-8"), title, search_text


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
      CREATE INDEX files_name_idx ON files(name COLLATE NOCASE);
      CREATE INDEX files_mime_idx ON files(mime);
      CREATE TABLE pages (
        path TEXT PRIMARY KEY REFERENCES files(path),
        title TEXT NOT NULL
      );
      CREATE INDEX pages_title_idx ON pages(title COLLATE NOCASE);
      CREATE VIRTUAL TABLE pages_search USING fts4(search_text, content='');
      CREATE TABLE aliases (alias TEXT PRIMARY KEY, path TEXT NOT NULL);
      CREATE INDEX aliases_path_idx ON aliases(path);
      PRAGMA user_version=3;
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
    text_value = "Sensei's Library offline snapshot search browse library SGF files"
    conn.execute("INSERT OR REPLACE INTO pages(path,title) VALUES(?,?)", ("__senseis_home__.html", "Sensei's Library — Offline"))
    page_rowid = conn.execute("SELECT rowid FROM pages WHERE path=?", ("__senseis_home__.html",)).fetchone()[0]
    conn.execute("INSERT INTO pages_search(rowid,search_text) VALUES(?,?)", (page_rowid, text_value))
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
        print(f"Import pass complete: {counters['files']:,} files; PNG images retained unchanged pending SGF mapping analysis", flush=True)

        # Pass 2a: identify all HTML pages and create aliases before any links
        # are rewritten, so links to pages later in the tar stream also resolve.
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
            body = soup.body or soup
            search_text = re.sub(r"\s+", " ", body.get_text(" ", strip=True)).strip()
            conn.execute("INSERT OR REPLACE INTO pages(path,title) VALUES(?,?)", (path, title))
            # Contentless FTS stores only the inverted index; path/title live in pages.
            page_rowid = conn.execute("SELECT rowid FROM pages WHERE path=?", (path,)).fetchone()[0]
            conn.execute("INSERT INTO pages_search(rowid,search_text) VALUES(?,?)", (page_rowid, search_text))
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
                print(f"Indexed {index:,}/{len(html_paths):,} HTML pages", flush=True)
        conn.commit()

        # Also map every stored file by its relative path; this includes image,
        # stylesheet, script, PDF and SGF attachments.
        for (path,) in conn.execute("SELECT path FROM files ORDER BY path"):
            add_alias(conn, path, path)
            add_alias(conn, PurePosixPath(path).name, path)
            add_alias(conn, PurePosixPath(path).stem, path)
        conn.commit()

        # Pass 2b: rewrite only same-wiki URLs. External URLs are left untouched;
        # the Android application itself blocks all network traffic.
        for index, path in enumerate(html_paths, 1):
            packed, encoding = conn.execute("SELECT data,encoding FROM files WHERE path=?", (path,)).fetchone()
            raw = unpack_payload(packed, encoding)
            rewritten, title, search_text = rewrite_html(conn, path, raw)
            stored, new_encoding = store_payload(rewritten, path)
            conn.execute("UPDATE files SET data=?,encoding=?,size=?,sha256=? WHERE path=?",
                         (sqlite3.Binary(stored), new_encoding, len(rewritten), hashlib.sha256(rewritten).hexdigest(), path))
            conn.execute("UPDATE pages SET title=? WHERE path=?", (title, path))
            if index % progress_every == 0:
                conn.commit()
                print(f"Rewrote {index:,}/{len(html_paths):,} HTML pages", flush=True)
        conn.commit()

        # The snapshot uses identical 32-hex basenames for each diagram PNG and
        # its SGF source. HTML has already been rewritten to render the SGF, so
        # remove the redundant PNG payloads and their aliases from the database.
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

        # FTS4 initially receives each page before HTML rewriting, then that
        # row is replaced with the final text. Merge obsolete FTS segments and
        # reclaim SQLite pages freed by the rewritten HTML BLOBs.
        before_compaction_bytes = temporary.stat().st_size
        before_compaction_freelist_pages = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        conn.execute("INSERT INTO pages_search(pages_search) VALUES('optimize')")
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
