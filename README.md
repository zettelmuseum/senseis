# Sensei's Library — offline Android edition

This repository builds an offline Android reader and a SQLite database from the public Sensei's Library snapshot:

https://senseis.xmp.net/files/snapshots/senseis-library.tar.bz2

## Build with GitHub Actions

1. Open **Actions**.
2. Select **Build Sensei's Library Android app and SQLite database**.
3. Run the workflow on `main`.
4. Download both artifacts from the completed run:
   - `senseis-android-app` — install `SenseisLibrary.apk`.
   - `senseis-offline-database` — contains `senseis.db`.
5. Start the app, tap **Import offline library database**, and select `senseis.db`.

The APK and database are intentionally separate. The APK stays small; the large snapshot database is copied into the app's private storage on first import. The library then works offline and does not request internet permission.

## Snapshot conversion

`scripts/build_database.py` reads the bzip2-compressed tar archive as a stream. It does **not** extract the full 50,000+ file archive onto disk. Text payloads are deflated when that reduces size. Page text is not duplicated in an uncompressed column: full-text search uses an FTS4 token index instead. PNG images are quantized to 32 colors and scaled to 75% width and height; image files larger than 500 KiB are omitted. The source snapshot archive is cached between GitHub Actions runs. HTML pages are indexed by path, filename, title and wiki-style `Group.Page` aliases. Internal links are mapped to the local `https://senseis.local/` WebView origin; fragment identifiers are retained. Images, stylesheets, scripts and other attachments are served from the same database. SGF links open Android's document-creation picker so the original SGF file can be saved to a user-selected location.

## Bounded snapshot tests

The workflow runs synthetic archive tests, then scans at most the first 15,000 archive members and extracts no more than 80 HTML pages into a temporary sample directory. It reports page titles, headings, links, images, forms, scripts and SGF links before starting the complete streaming database import. This checks the real snapshot's structure without unpacking the entire archive.

The full converter subsequently streams all regular files directly into `senseis.db`. No 50,000-file directory tree is created.

## Android build

The app is a small Java-only WebView application and is built directly with the Android SDK command-line tools (no Gradle project). The WebView serves HTML and attachments from SQLite at a local HTTPS origin; requests to other network hosts are blocked. The app includes title/text search, home/back/forward navigation, database import, and SGF export via Android's Storage Access Framework.
