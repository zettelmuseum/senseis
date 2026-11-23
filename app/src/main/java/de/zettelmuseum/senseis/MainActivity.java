package de.zettelmuseum.senseis;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.DialogInterface;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.net.URLConnection;
import java.net.URLDecoder;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.zip.CRC32;
import java.util.zip.InflaterInputStream;

public class MainActivity extends Activity {
    private static final int REQUEST_IMPORT = 4101;
    private static final int REQUEST_SAVE_SGF = 4102;
    private static final String LOCAL_HOST = "senseis.local";
    private static final String BASE_URL = "https://senseis.local/";
    private static final byte[] MAGIC = new byte[]{'S','L','I','B','P','K','0','1'};
    private static final int HEADER_SIZE = 32;
    private static final int FLAG_DEFLATE = 1;
    private static final int FLAG_HTML = 2;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private File archiveFile;
    private Entry[] entries;
    private WebView webView;
    private LinearLayout root;
    private TextView status;
    private ProgressBar progress;
    private String pendingSgfPath;

    private static final class Entry {
        final String path;
        final long offset;
        final long length;
        final long crc;
        final int flags;
        Entry(String p, long o, long l, long c, int f) {
            path = p; offset = o; length = l; crc = c; flags = f;
        }
        boolean isHtml() { return (flags & FLAG_HTML) != 0; }
        boolean isCompressed() { return (flags & FLAG_DEFLATE) != 0; }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        archiveFile = new File(getFilesDir(), "senseis.slb");
        buildShell();
        if (archiveFile.isFile() && openArchive()) showBrowser(); else showImportScreen();
    }

    private void buildShell() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(4), dp(3), dp(4), dp(3));
        toolbar.setBackgroundColor(Color.rgb(238, 240, 243));
        root.addView(toolbar, new LinearLayout.LayoutParams(-1, dp(48)));
        addToolButton(toolbar, "Home", new View.OnClickListener() { @Override public void onClick(View v) { loadHome(); } });
        addToolButton(toolbar, "Back", new View.OnClickListener() { @Override public void onClick(View v) { if (webView != null && webView.canGoBack()) webView.goBack(); } });
        addToolButton(toolbar, "Forward", new View.OnClickListener() { @Override public void onClick(View v) { if (webView != null && webView.canGoForward()) webView.goForward(); } });
        addToolButton(toolbar, "Search", new View.OnClickListener() { @Override public void onClick(View v) { showSearchDialog(); } });
        addToolButton(toolbar, "File", new View.OnClickListener() { @Override public void onClick(View v) { chooseArchive(); } });
        status = new TextView(this);
        status.setTextColor(Color.DKGRAY); status.setTextSize(12); status.setPadding(dp(10), dp(2), dp(10), dp(2));
        status.setSingleLine(true); status.setVisibility(View.GONE);
        root.addView(status, new LinearLayout.LayoutParams(-1, dp(22)));
        progress = new ProgressBar(this); progress.setIndeterminate(true); progress.setVisibility(View.GONE);
        root.addView(progress, new LinearLayout.LayoutParams(-2, dp(4)));
        setContentView(root);
    }

    private void addToolButton(LinearLayout bar, String label, View.OnClickListener listener) {
        Button b = new Button(this); b.setText(label); b.setTextSize(12); b.setAllCaps(false);
        b.setMinHeight(dp(38)); b.setMinimumHeight(dp(38)); b.setPadding(dp(5), 0, dp(5), 0); b.setOnClickListener(listener);
        bar.addView(b, new LinearLayout.LayoutParams(0, -1, 1f));
    }

    private void showImportScreen() {
        removeBrowser();
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER); panel.setPadding(dp(24), dp(24), dp(24), dp(24));
        TextView heading = new TextView(this); heading.setText("Sensei's Library — offline");
        heading.setTextSize(22); heading.setTextColor(Color.BLACK); heading.setGravity(Gravity.CENTER);
        panel.addView(heading, new LinearLayout.LayoutParams(-1, -2));
        TextView explanation = new TextView(this);
        explanation.setText("Select the senseis.slb archive produced by GitHub Actions. It contains the compressed pages, images, attachments and SGF files in one compact binary file. No internet connection is used.");
        explanation.setTextSize(16); explanation.setTextColor(Color.DKGRAY); explanation.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(-1, -2); tp.topMargin = dp(18); panel.addView(explanation, tp);
        Button choose = new Button(this); choose.setText("Import offline library"); choose.setAllCaps(false);
        choose.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View v) { chooseArchive(); } });
        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(-2, -2); bp.topMargin = dp(22); panel.addView(choose, bp);
        root.addView(panel, new LinearLayout.LayoutParams(-1, 0, 1f));
    }

    private void removeBrowser() {
        if (webView != null) { root.removeView(webView); webView.destroy(); webView = null; }
        for (int i = root.getChildCount() - 1; i >= 0; i--) {
            View child = root.getChildAt(i);
            if (child != status && child != progress && i != 0 && child instanceof LinearLayout) root.removeViewAt(i);
        }
    }

    private void showBrowser() {
        removeBrowser();
        webView = new WebView(this); webView.setBackgroundColor(Color.WHITE);
        WebSettings s = webView.getSettings(); s.setJavaScriptEnabled(true); s.setDomStorageEnabled(false); s.setDatabaseEnabled(false); s.setCacheMode(WebSettings.LOAD_NO_CACHE); s.setSaveFormData(false);
        s.setAllowFileAccess(false); s.setAllowContentAccess(false); s.setSupportZoom(true);
        s.setBuiltInZoomControls(true); s.setDisplayZoomControls(false); s.setSupportMultipleWindows(false); s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        webView.addJavascriptInterface(new SaveBridge(), "SenseiBridge");
        webView.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) { return routeRequest(r.getUrl()); }
            @SuppressWarnings("deprecation") @Override public WebResourceResponse shouldInterceptRequest(WebView v, String u) { return routeRequest(Uri.parse(u)); }
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl(); if (isWikiHost(u.getHost())) { webView.loadUrl(toLocalUrl(u)); return true; }
                return !LOCAL_HOST.equalsIgnoreCase(u.getHost());
            }
            @SuppressWarnings("deprecation") @Override public boolean shouldOverrideUrlLoading(WebView v, String value) {
                Uri u = Uri.parse(value); if (isWikiHost(u.getHost())) { webView.loadUrl(toLocalUrl(u)); return true; }
                return !LOCAL_HOST.equalsIgnoreCase(u.getHost());
            }
            @Override public void onPageStarted(WebView v, String url, android.graphics.Bitmap icon) {
                status.setText(url.replace(BASE_URL, "")); status.setVisibility(View.VISIBLE);
            }
            @Override public void onPageFinished(WebView v, String url) { status.setText(url.replace(BASE_URL, "")); injectPageEnhancements(v); }
        });
        root.addView(webView, new LinearLayout.LayoutParams(-1, 0, 1f));
        status.setVisibility(View.VISIBLE); loadHome();
    }

    private boolean isWikiHost(String host) {
        return host != null && ("senseis.xmp.net".equalsIgnoreCase(host) || "www.senseis.xmp.net".equalsIgnoreCase(host));
    }

    private String toLocalUrl(Uri uri) {
        StringBuilder b = new StringBuilder(BASE_URL);
        String p = uri.getEncodedPath(); if (p != null && p.length() > 1) b.append(p.substring(1));
        if (uri.getEncodedQuery() != null) b.append('?').append(uri.getEncodedQuery());
        if (uri.getEncodedFragment() != null) b.append('#').append(uri.getEncodedFragment());
        return b.toString();
    }

    private void injectPageEnhancements(WebView target) {
        InputStream in = null;
        try {
            in = getAssets().open("senseis-page.js"); byte[] buf = new byte[8192]; StringBuilder script = new StringBuilder(); int n;
            while ((n = in.read(buf)) != -1) script.append(new String(buf, 0, n, "UTF-8"));
            target.evaluateJavascript(script.toString(), null);
        } catch (Exception ignored) {
        } finally { if (in != null) try { in.close(); } catch (Exception ignored) { } }
    }

    private WebResourceResponse routeRequest(Uri uri) {
        String scheme = uri.getScheme(), host = uri.getHost();
        boolean local = "https".equalsIgnoreCase(scheme) && LOCAL_HOST.equalsIgnoreCase(host);
        boolean wiki = ("https".equalsIgnoreCase(scheme) || "http".equalsIgnoreCase(scheme)) && isWikiHost(host);
        if (!local && !wiki) {
            if ("data".equalsIgnoreCase(scheme) || "blob".equalsIgnoreCase(scheme)) return null;
            return response("text/plain", "utf-8", new byte[0], 403, "Blocked");
        }
        String path = decodePath(uri.getEncodedPath());
        if (local && path.startsWith("/__app/")) return openBundledAsset(path.substring(7));
        if (entries == null) return response("text/plain", "utf-8", "Archive not loaded".getBytes(), 503, "Unavailable");
        if (path.length() == 0 || "/".equals(path)) {
            String q = uri.getEncodedQuery();
            if (q != null && q.length() > 0) { path = findQueryPage(q); if (path == null) return missingPage(q); }
            else path = "__senseis_home__.html";
        }
        path = normalizePath(path);
        if (path == null) return response("text/plain", "utf-8", new byte[0], 400, "Bad path");
        Entry e = findEntry(path);
        if (e == null && !path.startsWith("snapshot/")) e = findEntry("snapshot/" + path);
        if (e == null) {
            String alias = findAlias(path);
            if (alias != null) e = findEntry(alias);
        }
        if (e == null) return missingPage(path);
        String mime = mimeFor(e.path);
        String charset = mime.startsWith("text/") || mime.contains("xml") || mime.contains("javascript") ? "utf-8" : null;
        if (mime.equals("application/x-go-sgf")) charset = null;
        Map<String, String> headers = new HashMap<String, String>();
        headers.put("Cache-Control", "no-store"); headers.put("X-Content-Type-Options", "nosniff");
        try { return new WebResourceResponse(mime, charset, 200, "OK", headers, openPayloadStream(e)); }
        catch (Exception ex) { return response("text/plain", "utf-8", ("Unable to read local file: " + ex.getMessage()).getBytes(), 500, "Archive error"); }
    }

    private WebResourceResponse openBundledAsset(String path) {
        if (path.length() == 0 || path.startsWith("/") || path.contains("..") || path.indexOf('\\') >= 0) {
            return response("text/plain", "utf-8", new byte[0], 400, "Bad asset path");
        }
        String mime;
        if (path.endsWith(".js")) mime = "application/javascript";
        else if (path.endsWith(".css")) mime = "text/css";
        else return response("text/plain", "utf-8", new byte[0], 404, "Not Found");
        try {
            InputStream in = getAssets().open("besogo/" + path);
            Map<String, String> headers = new HashMap<String, String>();
            headers.put("Cache-Control", "public, max-age=31536000");
            headers.put("X-Content-Type-Options", "nosniff");
            return new WebResourceResponse(mime, "utf-8", 200, "OK", headers, in);
        } catch (IOException e) {
            return response("text/plain", "utf-8", new byte[0], 404, "Not Found");
        }
    }

    private Entry findEntry(String path) {
        if (entries == null) return null;
        int lo = 0, hi = entries.length - 1;
        while (lo <= hi) {
            int mid = (lo + hi) >>> 1;
            int c = entries[mid].path.compareToIgnoreCase(path);
            if (c == 0) {
                if (entries[mid].path.equals(path)) return entries[mid];
                int left = mid - 1;
                while (left >= lo && entries[left].path.equalsIgnoreCase(path)) { if (entries[left].path.equals(path)) return entries[left]; left--; }
                int right = mid + 1;
                while (right <= hi && entries[right].path.equalsIgnoreCase(path)) { if (entries[right].path.equals(path)) return entries[right]; right++; }
                return entries[mid];
            }
            if (c < 0) lo = mid + 1; else hi = mid - 1;
        }
        return null;
    }

    // Aliases are derived on demand from paths; no alias table is stored in the archive.
    private String findAlias(String value) {
        String key = aliasKey(value);
        String dotted = key.replace('/', '.');
        for (Entry e : entries) {
            String p = e.path.toLowerCase(Locale.ROOT);
            String noExt = p.replaceFirst("\\.(html?|xhtml|shtml)$", "");
            String base = p.substring(p.lastIndexOf('/') + 1);
            String stem = base.replaceFirst("\\.[^.]*$", "");
            String rel = noExt.startsWith("snapshot/") ? noExt.substring(9) : noExt;
            String lastTwo = noExt;
            int slash = noExt.lastIndexOf('/');
            if (slash > 0) lastTwo = noExt.substring(noExt.lastIndexOf('/', slash - 1) + 1);
            if (key.equals(p) || key.equals(noExt) || key.equals(base) || key.equals(stem)
                    || dotted.equals(rel.replace('/', '.')) || dotted.equals(lastTwo.replace('/', '.'))) return e.path;
        }
        // Wiki names such as Group.Page map naturally to Group/Page.html.
        String candidate = dotted.replace('.', '/') + ".html";
        Entry found = findEntry(candidate);
        if (found != null) return found.path;
        found = findEntry("snapshot/" + candidate);
        return found == null ? null : found.path;
    }

    private String findQueryPage(String query) {
        String decoded;
        try { decoded = URLDecoder.decode(query.replace("+", "%2B"), "UTF-8"); } catch (Exception ex) { decoded = query; }
        List<String> candidates = new ArrayList<String>();
        candidates.add(decoded); candidates.add(queryValue(decoded, "n")); candidates.add(queryValue(decoded, "page"));
        candidates.add(queryValue(decoded, "title")); candidates.add(queryValue(decoded, "q"));
        for (String field : decoded.split("&")) { int at = field.indexOf('='); candidates.add(at < 0 ? field : field.substring(at + 1)); }
        for (String c : candidates) if (c != null && c.length() > 0) {
            String alias = findAlias(c); if (alias != null) return alias;
        }
        return null;
    }

    private String queryValue(String query, String wanted) {
        for (String field : query.split("&")) { int at = field.indexOf('='); if (at > 0 && wanted.equalsIgnoreCase(field.substring(0, at))) return field.substring(at + 1); }
        return null;
    }

    private String aliasKey(String value) {
        String key = value;
        try { key = URLDecoder.decode(key, "UTF-8"); } catch (Exception ignored) { }
        key = key.replace('\\', '/').trim();
        while (key.startsWith("/")) key = key.substring(1);
        while (key.endsWith("/")) key = key.substring(0, key.length() - 1);
        return key.replaceFirst("(?i)\\.(html?|xhtml|shtml)$", "").toLowerCase(Locale.ROOT);
    }

    private String normalizePath(String path) {
        if (path == null) return null;
        path = path.replace('\\', '/'); while (path.startsWith("/")) path = path.substring(1);
        if (path.length() == 0) return "__senseis_home__.html";
        StringBuilder b = new StringBuilder();
        for (String part : path.split("/")) {
            if (part.length() == 0 || ".".equals(part)) continue;
            if ("..".equals(part)) return null;
            if (b.length() > 0) b.append('/');
            b.append(part);
        }
        return b.toString();
    }

    private String decodePath(String path) {
        if (path == null) return "";
        try { return URLDecoder.decode(path.replace("+", "%2B"), "UTF-8"); } catch (Exception e) { return path; }
    }

    private String mimeFor(String path) {
        if (path.toLowerCase(Locale.ROOT).endsWith(".sgf")) return "application/x-go-sgf";
        if (path.toLowerCase(Locale.ROOT).endsWith(".svg")) return "image/svg+xml";
        String mime = URLConnection.guessContentTypeFromName(path);
        return mime == null ? "application/octet-stream" : mime;
    }

    private WebResourceResponse missingPage(String target) {
        String safe = escapeHtml(target);
        String page = "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Page not in snapshot</title></head><body style='font-family:sans-serif;padding:18px'><h2>Page not in this snapshot</h2><p>This page is not included:</p><code>" + safe + "</code><p>Use Search to find a related page.</p><p><a href='/'>Library home</a></p></body></html>";
        return response("text/html", "utf-8", page.getBytes(java.nio.charset.Charset.forName("UTF-8")), 404, "Not Found");
    }

    private WebResourceResponse response(String mime, String charset, byte[] data, int code, String reason) {
        if (android.os.Build.VERSION.SDK_INT >= 21) return new WebResourceResponse(mime, charset, code, reason, new HashMap<String, String>(), new ByteArrayInputStream(data));
        return new WebResourceResponse(mime, charset, new ByteArrayInputStream(data));
    }

    private InputStream openPayloadStream(Entry entry) throws IOException {
        FileInputStream file = new FileInputStream(archiveFile);
        file.getChannel().position(HEADER_SIZE + entry.offset);
        InputStream bounded = new BoundedInputStream(file, entry.length);
        InputStream decoded = entry.isCompressed() ? new InflaterInputStream(bounded) : bounded;
        return new CrcInputStream(decoded, entry.crc);
    }

    private static final class BoundedInputStream extends FilterInputStream {
        long remaining;
        BoundedInputStream(InputStream in, long length) { super(in); remaining = length; }
        @Override public int read() throws IOException {
            if (remaining <= 0) return -1;
            int v = in.read(); if (v < 0) throw new IOException("Truncated payload"); remaining--; return v;
        }
        @Override public int read(byte[] b, int off, int len) throws IOException {
            if (remaining <= 0) return -1;
            int n = in.read(b, off, (int)Math.min((long)len, remaining));
            if (n < 0) throw new IOException("Truncated payload"); remaining -= n; return n;
        }
    }

    private static final class CrcInputStream extends FilterInputStream {
        final CRC32 crc = new CRC32(); final long expected; boolean checked;
        CrcInputStream(InputStream in, long expected) { super(in); this.expected = expected; }
        private void verify() throws IOException { if (!checked) { checked = true; if (crc.getValue() != expected) throw new IOException("CRC32 mismatch"); } }
        @Override public int read() throws IOException { int v = in.read(); if (v < 0) verify(); else crc.update(v); return v; }
        @Override public int read(byte[] b, int off, int len) throws IOException { int n = in.read(b, off, len); if (n < 0) verify(); else crc.update(b, off, n); return n; }
    }

    private Entry[] readDirectory(File file) throws Exception {
        RandomAccessFile raf = new RandomAccessFile(file, "r");
        try {
            if (raf.length() < HEADER_SIZE) throw new IOException("File is too short");
            byte[] magic = new byte[8]; raf.readFully(magic);
            for (int i = 0; i < 8; i++) if (magic[i] != MAGIC[i]) throw new IOException("Not a Sensei's Library archive");
            int version = raf.readInt(), count = raf.readInt(); long payloadLength = raf.readLong();
            int indexLength = raf.readInt(); long indexCrc = raf.readInt() & 0xffffffffL;
            if (version != 1 || count < 1 || count > 500000 || payloadLength < 0 || indexLength < 1 || indexLength > 64 * 1024 * 1024) throw new IOException("Unsupported archive header");
            if (raf.length() != HEADER_SIZE + payloadLength + indexLength) throw new IOException("Archive length mismatch");
            byte[] compressed = new byte[indexLength]; raf.seek(HEADER_SIZE + payloadLength); raf.readFully(compressed);
            InputStream zin = new InflaterInputStream(new ByteArrayInputStream(compressed));
            ByteArrayOutputStream rawOut = new ByteArrayOutputStream(); byte[] buf = new byte[32768]; int n;
            while ((n = zin.read(buf)) != -1) rawOut.write(buf, 0, n);
            zin.close(); byte[] raw = rawOut.toByteArray();
            CRC32 crc = new CRC32(); crc.update(raw); if (crc.getValue() != indexCrc) throw new IOException("Directory CRC32 mismatch");
            ByteBuffer b = ByteBuffer.wrap(raw).order(ByteOrder.BIG_ENDIAN);
            Entry[] result = new Entry[count];
            for (int i = 0; i < count; i++) {
                if (b.remaining() < 23) throw new IOException("Truncated directory");
                long offset = b.getLong(), length = b.getLong(), fileCrc = b.getInt() & 0xffffffffL;
                int flags = b.get() & 255, nameLength = b.getShort() & 65535;
                if (nameLength < 1 || b.remaining() < nameLength || offset < 0 || length < 0 || offset + length > payloadLength) throw new IOException("Invalid directory entry");
                byte[] name = new byte[nameLength]; b.get(name);
                result[i] = new Entry(new String(name, "UTF-8"), offset, length, fileCrc, flags);
                if (i > 0 && result[i-1].path.compareToIgnoreCase(result[i].path) > 0) throw new IOException("Unsorted directory");
            }
            if (b.hasRemaining()) throw new IOException("Unexpected directory data");
            return result;
        } finally { raf.close(); }
    }

    private boolean openArchive() {
        try { entries = readDirectory(archiveFile); return true; }
        catch (Exception e) { entries = null; return false; }
    }

    private String escapeHtml(String value) {
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    private void loadHome() { if (webView != null && entries != null) webView.loadUrl(BASE_URL); }

    private void showSearchDialog() {
        if (entries == null) { Toast.makeText(this, "Import the library archive first", Toast.LENGTH_SHORT).show(); return; }
        final EditText input = new EditText(this); input.setSingleLine(true); input.setHint("Page title or text");
        input.setInputType(EditorInfo.TYPE_CLASS_TEXT);
        new AlertDialog.Builder(this).setTitle("Search Sensei's Library").setView(input)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Search", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int w) { searchPages(input.getText().toString().trim()); }
                }).show();
    }

    private boolean containsAllTerms(InputStream stream, String[] terms) throws Exception {
        boolean[] found = new boolean[terms.length]; int remaining = 0, overlap = 0;
        for (String term : terms) if (term.length() > 0) { remaining++; overlap = Math.max(overlap, term.length() - 1); }
        if (remaining == 0) return false;
        char[] chars = new char[8192]; StringBuilder tail = new StringBuilder();
        InputStreamReader reader = new InputStreamReader(stream, "UTF-8"); int count;
        while ((count = reader.read(chars)) != -1) {
            String part = (tail.toString() + new String(chars, 0, count)).toLowerCase(Locale.ROOT);
            for (int i = 0; i < terms.length; i++) if (!found[i] && terms[i].length() > 0 && part.contains(terms[i])) { found[i] = true; remaining--; }
            if (remaining == 0) return true;
            tail.setLength(0); if (overlap > 0 && part.length() > overlap) tail.append(part.substring(part.length() - overlap));
        }
        return false;
    }

    private void searchPages(final String query) {
        if (query.length() == 0) return;
        progress.setVisibility(View.VISIBLE);
        new Thread(new Runnable() {
            @Override public void run() {
                final List<String[]> results = new ArrayList<String[]>();
                try {
                    String[] terms = query.toLowerCase(Locale.ROOT).split("\\s+");
                    for (Entry e : entries) {
                        if (!e.isHtml()) continue;
                        String title = e.path.substring(e.path.lastIndexOf('/') + 1).replaceFirst("(?i)\\.(html?|xhtml|shtml)$", "").replace('_', ' ');
                        boolean match = title.toLowerCase(Locale.ROOT).contains(terms[0]);
                        if (!match) { InputStream in = openPayloadStream(e); try { match = containsAllTerms(in, terms); } finally { in.close(); } }
                        if (match) results.add(new String[]{e.path, title});
                        if (results.size() >= 100) break;
                    }
                } catch (Exception ignored) { }
                mainHandler.post(new Runnable() {
                    @Override public void run() {
                        progress.setVisibility(View.GONE);
                        if (results.isEmpty()) { Toast.makeText(MainActivity.this, "No matching pages found", Toast.LENGTH_SHORT).show(); return; }
                        String[] labels = new String[results.size()]; for (int i = 0; i < results.size(); i++) labels[i] = results.get(i)[1];
                        new AlertDialog.Builder(MainActivity.this).setTitle(results.size() + " search results").setItems(labels, new DialogInterface.OnClickListener() {
                            @Override public void onClick(DialogInterface d, int which) { webView.loadUrl(BASE_URL + Uri.encode(results.get(which)[0], "/!$&'()*+,;=:@-._~")); }
                        }).setNegativeButton("Close", null).show();
                    }
                });
            }
        }).start();
    }

    private void chooseArchive() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT); i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("*/*");
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try { startActivityForResult(i, REQUEST_IMPORT); } catch (ActivityNotFoundException e) { Toast.makeText(this, "No file picker is available", Toast.LENGTH_LONG).show(); }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        if (requestCode == REQUEST_IMPORT) importArchive(data.getData());
        else if (requestCode == REQUEST_SAVE_SGF) savePendingSgf(data.getData());
    }

    private void importArchive(final Uri uri) {
        progress.setVisibility(View.VISIBLE); status.setVisibility(View.VISIBLE); status.setText("Importing compact archive…");
        new Thread(new Runnable() {
            @Override public void run() {
                File temp = new File(getFilesDir(), "senseis-import.tmp"); String error = null;
                try {
                    InputStream in = getContentResolver().openInputStream(uri); if (in == null) throw new IOException("Cannot open selected file");
                    FileOutputStream out = new FileOutputStream(temp); byte[] buf = new byte[1024 * 1024]; int n;
                    while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
                    out.flush(); out.getFD().sync(); out.close(); in.close();
                    readDirectory(temp);
                    File backup = new File(getFilesDir(), "senseis-old.slb");
                    if (archiveFile.exists()) archiveFile.renameTo(backup);
                    if (!temp.renameTo(archiveFile)) throw new IOException("Cannot install archive");
                    if (backup.exists()) backup.delete();
                } catch (Exception e) { error = e.getMessage() == null ? e.toString() : e.getMessage(); temp.delete(); }
                final String finalError = error;
                mainHandler.post(new Runnable() {
                    @Override public void run() {
                        progress.setVisibility(View.GONE);
                        if (finalError != null) { status.setText("Archive import failed"); new AlertDialog.Builder(MainActivity.this).setTitle("Import failed").setMessage(finalError).setPositiveButton("OK", null).show(); }
                        else if (openArchive()) { Toast.makeText(MainActivity.this, "Offline library imported", Toast.LENGTH_LONG).show(); showBrowser(); }
                    }
                });
            }
        }).start();
    }

    private class SaveBridge {
        @JavascriptInterface public void saveSgf(final String urlPath) {
            mainHandler.post(new Runnable() { @Override public void run() { beginSgfSave(urlPath); } });
        }
    }

    private void beginSgfSave(String urlPath) {
        String path = normalizePath(decodePath(Uri.parse(urlPath).getEncodedPath()));
        Entry e = path == null ? null : findEntry(path);
        if (e == null || !e.path.toLowerCase(Locale.ROOT).endsWith(".sgf")) { Toast.makeText(this, "SGF file not found", Toast.LENGTH_SHORT).show(); return; }
        pendingSgfPath = e.path;
        String name = e.path.substring(e.path.lastIndexOf('/') + 1);
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT); i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("application/x-go-sgf"); i.putExtra(Intent.EXTRA_TITLE, name);
        try { startActivityForResult(i, REQUEST_SAVE_SGF); } catch (ActivityNotFoundException ex) { Toast.makeText(this, "No file picker is available", Toast.LENGTH_LONG).show(); }
    }

    private void savePendingSgf(final Uri destination) {
        if (pendingSgfPath == null) return;
        final Entry e = findEntry(pendingSgfPath); pendingSgfPath = null; if (e == null) return;
        progress.setVisibility(View.VISIBLE);
        new Thread(new Runnable() {
            @Override public void run() {
                String error = null;
                try {
                    InputStream in = openPayloadStream(e); OutputStream out = getContentResolver().openOutputStream(destination);
                    if (out == null) throw new IOException("Cannot open destination");
                    byte[] buf = new byte[65536]; int n; while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
                    out.flush(); out.close(); in.close();
                } catch (Exception ex) { error = ex.getMessage() == null ? ex.toString() : ex.getMessage(); }
                final String result = error;
                mainHandler.post(new Runnable() { @Override public void run() {
                    progress.setVisibility(View.GONE);
                    Toast.makeText(MainActivity.this, result == null ? "SGF saved" : "SGF save failed: " + result, Toast.LENGTH_LONG).show();
                }});
            }
        }).start();
    }

    private int dp(int value) { return (int)(value * getResources().getDisplayMetrics().density + 0.5f); }
    @Override public void onBackPressed() { if (webView != null && webView.canGoBack()) webView.goBack(); else super.onBackPressed(); }
    @Override protected void onDestroy() { if (webView != null) webView.destroy(); super.onDestroy(); }
}