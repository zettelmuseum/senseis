# Sensei's Library EPUB

This repository builds an offline EPUB from the public Sensei's Library snapshot:

https://senseis.xmp.net/files/snapshots/senseis-library.tar.bz2

## Build

1. Open the **Actions** tab.
2. Select **Build Sensei's Library EPUB**.
3. Choose **Run workflow** on the `main` branch.
4. When the run finishes, download the `senseis-library-epub` artifact.

The EPUB contains the archived HTML pages, an alphabetical index, and locally embedded images referenced by those pages. Wiki links that resolve to pages in the snapshot are rewritten to EPUB chapter links, including their fragment anchors. Links to pages absent from the snapshot remain clickable web links.

The generated EPUB is uploaded as a workflow artifact and is not committed to the repository.
