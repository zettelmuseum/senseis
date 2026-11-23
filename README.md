# Sensei's Library — offline Android edition

This repository builds a small offline Android reader and a compact binary archive from the public Sensei's Library snapshot:

https://senseis.xmp.net/files/snapshots/senseis-library.tar.bz2

## Build with GitHub Actions

1. Open **Actions**.
2. Select **Build Sensei's Library Android app and compact archive**.
3. Run the workflow on `main`.
4. Download both artifacts from the completed run:
   - `senseis-android-app` — install `SenseisLibrary.apk`.
   - `senseis-offline-library` — contains `senseis.slb`.
5. Start the app, tap **Import offline library**, and select `senseis.slb`.

The APK and archive are separate. The APK stays small; the archive is copied into the app's private storage on first import. The library then works offline and does not request internet permission.

## Compact archive format

The library is stored in a purpose-built read-only binary format instead of SQLite:

- A short fixed header identifies the format and locates the directory.
- All file payloads are concatenated directly, with no per-file database rows or indexes.
- Text-like files are deflated when compression makes them smaller; SGF compression is enabled only when the real-file benchmark recommends it.
- One compressed directory at the end stores each path, payload offset, stored length, CRC32 and flags.
- The directory contains no page table, alias table, SQL indexes, duplicate titles or duplicate file names.
- The Android app loads the directory once and uses binary search to find files. It streams each payload directly from its offset and verifies its CRC32 while reading.
- Wiki-style aliases such as `Group.Page` are derived from paths only when needed; no large alias list is persisted.

The format is versioned (`SLIBPK01`). The app validates the header, directory CRC, entry bounds and per-file CRC. File MIME types are derived from their extensions.

## Snapshot conversion

`scripts/build_library.py` streams the bzip2 tar archive without extracting the full 50,000+ file archive onto disk. SGF files remain ordinary archive entries; diagram handling is deliberately performed by the Android app after an HTML page has been unpacked, not while the archive is built. Images larger than 500 KiB are omitted. The source snapshot archive is cached between GitHub Actions runs.

## Bounded snapshot tests

The workflow runs synthetic archive tests, then scans at most the first 15,000 archive members and extracts no more than 80 HTML pages into a temporary sample directory. It reports page titles, headings, links, images, forms, scripts and SGF links before starting the complete streaming archive build.

## Android app

The app is a small Java-only WebView application built directly with Android SDK command-line tools (no Gradle project). The WebView serves HTML and attachments from the local `https://senseis.local/` origin; requests to other network hosts are blocked. Before an HTML response is passed to WebView, the app unpacks it from the archive and replaces links to `.sgf` files with small placeholders. Any content inside those SGF links is discarded, so pages containing many diagrams do not create all of their embedded preview elements during initial page parsing. Ordinary images are marked lazy before parsing. The app includes title/text search, home/back/forward navigation, archive import and SGF export through Android's Storage Access Framework. An optional Dark/Light toolbar toggle applies a dark stylesheet inside WebView and remembers the selection between app launches; light mode remains the default.

## SGF diagrams

SGF placeholders are activated only when tapped. The app fetches that one local SGF file and creates a single [BesoGo](https://github.com/yewang/besogo) viewer; it does not initialize viewers for all diagrams on the page. Closing the viewer aborts an in-flight SGF request, empties its board DOM and restores the lightweight placeholder. BesoGo uses fixed sizing with keyboard and wheel handlers disabled, avoiding per-viewer global resize listeners. BesoGo source and its MIT license are bundled under `app/src/main/assets/besogo/`; the Sensei board theme is used without optional third-party texture images.
