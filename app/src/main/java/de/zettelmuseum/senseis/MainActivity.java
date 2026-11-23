package de.zettelmuseum.senseis;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.DialogInterface;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
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
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.URLDecoder;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.zip.InflaterInputStream;

public class MainActivity extends Activity {
    private static final int REQUEST_IMPORT_DATABASE = 4101;
    private static final int REQUEST_SAVE_SGF = 4102;
    private static final String LOCAL_HOST = "senseis.local";
    private static final String BASE_URL = "https://senseis.local/";

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private SQLiteDatabase database;
    private WebView webView;
    private LinearLayout root;
    private TextView status;
    private ProgressBar progress;
    private String pendingSgfPath;
    private File databaseFile;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        databaseFile = new File(getFilesDir(), "senseis.db");
        buildShell();
        if (databaseFile.isFile() && openDatabase()) {
            showBrowser();
        } else {
            showImportScreen();
        }
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
        root.addView(toolbar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(48)));

        addToolButton(toolbar, "Home", new View.OnClickListener() {
            @Override public void onClick(View view) { loadHome(); }
        });
        addToolButton(toolbar, "Back", new View.OnClickListener() {
            @Override public void onClick(View view) { if (webView != null && webView.canGoBack()) webView.goBack(); }
        });
        addToolButton(toolbar, "Forward", new View.OnClickListener() {
            @Override public void onClick(View view) { if (webView != null && webView.canGoForward()) webView.goForward(); }
        });
        addToolButton(toolbar, "Search", new View.OnClickListener() {
            @Override public void onClick(View view) { showSearchDialog(); }
        });
        addToolButton(toolbar, "DB", new View.OnClickListener() {
            @Override public void onClick(View view) { chooseDatabase(); }
        });

        status = new TextView(this);
        status.setTextColor(Color.DKGRAY);
        status.setTextSize(12);
        status.setPadding(dp(10), dp(2), dp(10), dp(2));
        status.setSingleLine(true);
        status.setVisibility(View.GONE);
        root.addView(status, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(22)));

        progress = new ProgressBar(this);
        progress.setIndeterminate(true);
        progress.setVisibility(View.GONE);
        root.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(4)));
        setContentView(root);
    }

    private void addToolButton(LinearLayout bar, String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(12);
        button.setAllCaps(false);
        button.setMinHeight(dp(38));
        button.setMinimumHeight(dp(38));
        button.setPadding(dp(5), 0, dp(5), 0);
        button.setOnClickListener(listener);
        bar.addView(button, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));
    }

    private void showImportScreen() {
        removeBrowser();
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setPadding(dp(24), dp(24), dp(24), dp(24));
        TextView heading = new TextView(this);
        heading.setText("Sensei's Library — offline");
        heading.setTextSize(22);
        heading.setTextColor(Color.BLACK);
        heading.setGravity(Gravity.CENTER);
        panel.addView(heading, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        TextView explanation = new TextView(this);
        explanation.setText("Select the senseis.db file produced by the GitHub Actions workflow. The database contains the snapshot pages, images, attachments and SGF files. It is copied into the app's private storage; no internet connection is used.");
        explanation.setTextSize(16);
        explanation.setTextColor(Color.DKGRAY);
        explanation.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        textParams.topMargin = dp(18);
        panel.addView(explanation, textParams);
        Button choose = new Button(this);
        choose.setText("Import offline library database");
        choose.setAllCaps(false);
        choose.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { chooseDatabase(); }
        });
        LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        buttonParams.topMargin = dp(22);
        panel.addView(choose, buttonParams);
        root.addView(panel, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
    }

    private void removeBrowser() {
        if (webView != null) {
            root.removeView(webView);
            webView.destroy();
            webView = null;
        }
        for (int i = root.getChildCount() - 1; i >= 0; i--) {
            View child = root.getChildAt(i);
            if (child != status && child != progress && child != root.getChildAt(0)) {
                if (child instanceof LinearLayout) root.removeViewAt(i);
            }
        }
    }

    private void showBrowser() {
        removeBrowser();
        webView = new WebView(this);
        webView.setBackgroundColor(Color.WHITE);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        webView.addJavascriptInterface(new SaveBridge(), "SenseiBridge");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return routeRequest(request.getUrl());
            }

            @SuppressWarnings("deprecation")
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
                return routeRequest(Uri.parse(url));
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                return !LOCAL_HOST.equalsIgnoreCase(uri.getHost());
            }

            @SuppressWarnings("deprecation")
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                Uri uri = Uri.parse(url);
                return !LOCAL_HOST.equalsIgnoreCase(uri.getHost());
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                status.setText(url.replace(BASE_URL, ""));
                status.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                status.setText(url.replace(BASE_URL, ""));
            }
        });
        root.addView(webView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        status.setVisibility(View.VISIBLE);
        loadHome();
    }

    private WebResourceResponse routeRequest(Uri uri) {
        String scheme = uri.getScheme();
        String host = uri.getHost();
        if (!"https".equalsIgnoreCase(scheme) || !LOCAL_HOST.equalsIgnoreCase(host)) {
            if ("data".equalsIgnoreCase(scheme) || "blob".equalsIgnoreCase(scheme)) return null;
            return response("text/plain", "utf-8", new byte[0], 403, "Blocked");
        }
        if (database == null || !database.isOpen()) return response("text/plain", "utf-8", "Database not loaded".getBytes(), 503, "Unavailable");

        String path = decodePath(uri.getEncodedPath());
        if (path.length() == 0 || "/".equals(path)) {
            String query = uri.getEncodedQuery();
            if (query != null && query.length() > 0) {
                String resolved = findQueryPage(query);
                if (resolved != null) path = resolved;
                else return missingPage(query);
            } else {
                path = "__senseis_home__.html";
            }
        }
        path = normalizePath(path);
        if (path == null) return response("text/plain", "utf-8", new byte[0], 400, "Bad path");
        Cursor cursor = null;
        try {
            cursor = database.rawQuery("SELECT mime,encoding,name FROM files WHERE path=?", new String[]{path});
            if (!cursor.moveToFirst()) {
                String alias = findAlias(path);
                if (alias != null && !alias.equals(path)) return routeRequest(Uri.parse(BASE_URL + Uri.encode(alias, "/!$&'()*+,;=:@-._~")));
                return missingPage(path);
            }
            String mime = cursor.getString(0);
            String encoding = cursor.getString(1);
            String name = cursor.getString(2);
            InputStream dataStream = openPayloadStream(path, encoding);
            if (mime == null) mime = "application/octet-stream";
            String charset = mime.startsWith("text/") || mime.contains("xml") || mime.contains("javascript") || mime.equals("image/svg+xml") ? "utf-8" : null;
            Map<String, String> headers = new HashMap<String, String>();
            headers.put("Cache-Control", "no-store");
            headers.put("X-Content-Type-Options", "nosniff");
            if (path.toLowerCase(Locale.ROOT).endsWith(".sgf")) {
                mime = "application/x-go-sgf";
                charset = null;
            }
            return new WebResourceResponse(mime, charset, 200, "OK", headers, dataStream);
        } catch (Exception e) {
            return response("text/plain", "utf-8", ("Unable to read local file: " + e.getMessage()).getBytes(), 500, "Database error");
        } finally {
            if (cursor != null) cursor.close();
        }
    }

    private WebResourceResponse missingPage(String target) {
        String safe = escapeHtml(target);
        String page = "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Page not in snapshot</title></head>" +
                "<body style='font-family:sans-serif;padding:18px'><h2>Page not in this snapshot</h2><p>This page is not included in the offline database:</p><code>" + safe + "</code><p>Use Search to find a related page.</p><p><a href='/'>Library home</a></p></body></html>";
        return response("text/html", "utf-8", page.getBytes(java.nio.charset.Charset.forName("UTF-8")), 404, "Not Found");
    }

    private WebResourceResponse response(String mime, String charset, byte[] data, int statusCode, String reason) {
        if (android.os.Build.VERSION.SDK_INT >= 21) {
            return new WebResourceResponse(mime, charset, statusCode, reason, new HashMap<String, String>(), new ByteArrayInputStream(data));
        }
        return new WebResourceResponse(mime, charset, new ByteArrayInputStream(data));
    }

    private InputStream openPayloadStream(String path, String encoding) {
        InputStream input = new DatabaseBlobInputStream(path);
        return "deflate".equals(encoding) ? new InflaterInputStream(input) : input;
    }

    /** Reads a SQLite BLOB in small chunks so large images/attachments do not
     * need to be copied into one large Java byte array on this low-memory device. */
    private class DatabaseBlobInputStream extends InputStream {
        private static final int CHUNK_SIZE = 64 * 1024;
        private final String path;
        private byte[] chunk = new byte[0];
        private int position = 0;
        private long nextOffset = 1;
        private boolean finished = false;

        DatabaseBlobInputStream(String filePath) { path = filePath; }

        private boolean loadChunk() {
            if (finished) return false;
            Cursor c = null;
            try {
                c = database.rawQuery("SELECT substr(data, ?, ?) FROM files WHERE path=?",
                        new String[]{String.valueOf(nextOffset), String.valueOf(CHUNK_SIZE), path});
                if (!c.moveToFirst() || c.isNull(0)) {
                    finished = true;
                    return false;
                }
                chunk = c.getBlob(0);
                position = 0;
                if (chunk == null || chunk.length == 0) {
                    finished = true;
                    return false;
                }
                nextOffset += chunk.length;
                return true;
            } catch (Exception e) {
                finished = true;
                return false;
            } finally { if (c != null) c.close(); }
        }

        @Override public int read() {
            byte[] one = new byte[1];
            int count = read(one, 0, 1);
            return count < 0 ? -1 : (one[0] & 0xff);
        }

        @Override public int read(byte[] buffer, int offset, int length) {
            if (buffer == null) throw new NullPointerException("buffer");
            if (offset < 0 || length < 0 || length > buffer.length - offset) throw new IndexOutOfBoundsException();
            if (length == 0) return 0;
            int copied = 0;
            while (copied < length) {
                if (position >= chunk.length && !loadChunk()) return copied == 0 ? -1 : copied;
                int amount = Math.min(length - copied, chunk.length - position);
                System.arraycopy(chunk, position, buffer, offset + copied, amount);
                position += amount;
                copied += amount;
            }
            return copied;
        }

        @Override public void close() {
            finished = true;
            chunk = new byte[0];
        }
    }

    private String decodePath(String encoded) {
        if (encoded == null) return "";
        try { return URLDecoder.decode(encoded.replace("+", "%2B"), "UTF-8"); }
        catch (Exception e) { return encoded; }
    }

    private String normalizePath(String path) {
        if (path == null) return null;
        path = path.replace('\\', '/');
        while (path.startsWith("/")) path = path.substring(1);
        if (path.length() == 0) return "__senseis_home__.html";
        String[] parts = path.split("/");
        StringBuilder clean = new StringBuilder();
        for (String part : parts) {
            if (part.length() == 0 || ".".equals(part)) continue;
            if ("..".equals(part)) return null;
            if (clean.length() > 0) clean.append('/');
            clean.append(part);
        }
        return clean.toString();
    }

    private String findAlias(String value) {
        if (database == null) return null;
        String key = aliasKey(value);
        Cursor c = null;
        try {
            c = database.rawQuery("SELECT path FROM aliases WHERE alias=? LIMIT 1", new String[]{key});
            return c.moveToFirst() ? c.getString(0) : null;
        } catch (Exception e) { return null; }
        finally { if (c != null) c.close(); }
    }

    private String findQueryPage(String query) {
        String decoded;
        try { decoded = URLDecoder.decode(query.replace("+", "%2B"), "UTF-8"); }
        catch (Exception e) { decoded = query; }
        List<String> candidates = new ArrayList<String>();
        candidates.add(decoded);
        candidates.add(queryValue(decoded, "n"));
        candidates.add(queryValue(decoded, "page"));
        candidates.add(queryValue(decoded, "title"));
        candidates.add(queryValue(decoded, "q"));
        String[] fields = decoded.split("&");
        for (String field : fields) {
            int separator = field.indexOf('=');
            if (separator < 0) candidates.add(field);
            else if (separator + 1 < field.length()) candidates.add(field.substring(separator + 1));
        }
        for (String candidate : candidates) {
            if (candidate == null || candidate.length() == 0) continue;
            String found = findAlias(candidate);
            if (found != null) return found;
        }
        return null;
    }

    private String queryValue(String query, String wanted) {
        String[] fields = query.split("&");
        for (String field : fields) {
            int at = field.indexOf('=');
            if (at > 0 && wanted.equalsIgnoreCase(field.substring(0, at))) return field.substring(at + 1);
        }
        return null;
    }

    private String aliasKey(String value) {
        String key = value;
        try { key = URLDecoder.decode(key, "UTF-8"); } catch (Exception ignored) { }
        key = key.replace('\\', '/').trim();
        while (key.startsWith("/")) key = key.substring(1);
        while (key.endsWith("/")) key = key.substring(0, key.length() - 1);
        key = key.replaceAll("(?i)\\.(html?|xhtml|shtml)$", "");
        return key.toLowerCase(Locale.ROOT);
    }

    private String safeFilename(String name) {
        if (name == null || name.length() == 0) return "game.sgf";
        return name.replace("\\", "_").replace("\"", "_").replace("\r", "_").replace("\n", "_");
    }

    private String escapeHtml(String value) {
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    private void loadHome() {
        if (webView != null && database != null) webView.loadUrl(BASE_URL);
    }

    private void showSearchDialog() {
        if (database == null) {
            Toast.makeText(this, "Import the library database first", Toast.LENGTH_SHORT).show();
            return;
        }
        final EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setHint("Page title or text");
        input.setInputType(EditorInfo.TYPE_CLASS_TEXT);
        new AlertDialog.Builder(this)
                .setTitle("Search Sensei's Library")
                .setView(input)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Search", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        searchPages(input.getText().toString().trim());
                    }
                })
                .show();
    }

    private boolean containsAllTerms(InputStream stream, String[] terms) throws Exception {
        boolean[] found = new boolean[terms.length];
        int remaining = 0;
        int overlap = 0;
        for (String term : terms) {
            if (term.length() == 0) continue;
            remaining++;
            overlap = Math.max(overlap, term.length() - 1);
        }
        if (remaining == 0) return false;
        char[] chars = new char[8192];
        StringBuilder tail = new StringBuilder();
        InputStreamReader reader = new InputStreamReader(stream, "UTF-8");
        int count;
        while ((count = reader.read(chars)) != -1) {
            String part = (tail.toString() + new String(chars, 0, count)).toLowerCase(Locale.ROOT);
            for (int i = 0; i < terms.length; i++) {
                if (!found[i] && terms[i].length() > 0 && part.contains(terms[i])) {
                    found[i] = true;
                    remaining--;
                }
            }
            if (remaining == 0) return true;
            tail.setLength(0);
            if (overlap > 0 && part.length() > overlap) tail.append(part.substring(part.length() - overlap));
            else tail.append(part);
        }
        return false;
    }

    private void searchPages(final String query) {
        if (query.length() == 0) return;
        progress.setVisibility(View.VISIBLE);
        new Thread(new Runnable() {
            @Override public void run() {
                final List<String[]> results = new ArrayList<String[]>();
                Cursor cursor = null;
                try {
                    String[] terms = query.toLowerCase(Locale.ROOT).split("\\s+");
                    cursor = database.rawQuery("SELECT pages.path,pages.title,files.data,files.encoding FROM pages JOIN files ON files.path=pages.path ORDER BY pages.title COLLATE NOCASE", null);
                    while (cursor.moveToNext() && results.size() < 100) {
                        String title = cursor.getString(1);
                        boolean match = title != null && containsAllTerms(title, terms);
                        if (!match) {
                            byte[] payload = cursor.getBlob(2);
                            InputStream pageStream = new ByteArrayInputStream(payload);
                            if ("deflate".equals(cursor.getString(3))) pageStream = new InflaterInputStream(pageStream);
                            try { match = containsAllTerms(pageStream, terms); }
                            finally { pageStream.close(); }
                        }
                        if (match) results.add(new String[]{cursor.getString(0), title});
                    }
                } catch (Exception ignored) {
                } finally { if (cursor != null) cursor.close(); }
                mainHandler.post(new Runnable() {
                    @Override public void run() {
                        progress.setVisibility(View.GONE);
                        if (results.isEmpty()) {
                            Toast.makeText(MainActivity.this, "No matching pages found", Toast.LENGTH_SHORT).show();
                            return;
                        }
                        String[] labels = new String[results.size()];
                        for (int i = 0; i < results.size(); i++) labels[i] = results.get(i)[1];
                        new AlertDialog.Builder(MainActivity.this)
                                .setTitle(results.size() + " search results")
                                .setItems(labels, new DialogInterface.OnClickListener() {
                                    @Override public void onClick(DialogInterface dialog, int which) {
                                        String path = results.get(which)[0];
                                        webView.loadUrl(BASE_URL + Uri.encode(path, "/!$&'()*+,;=:@-._~"));
                                    }
                                })
                                .setNegativeButton("Close", null)
                                .show();
                    }
                });
            }
        }).start();
    }

    private void chooseDatabase() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try { startActivityForResult(intent, REQUEST_IMPORT_DATABASE); }
        catch (ActivityNotFoundException e) { Toast.makeText(this, "No file picker is available", Toast.LENGTH_LONG).show(); }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        final Uri uri = data.getData();
        if (requestCode == REQUEST_IMPORT_DATABASE) {
            importDatabase(uri);
        } else if (requestCode == REQUEST_SAVE_SGF) {
            savePendingSgf(uri);
        }
    }

    private void importDatabase(final Uri uri) {
        progress.setVisibility(View.VISIBLE);
        status.setVisibility(View.VISIBLE);
        status.setText("Importing SQLite database…");
        new Thread(new Runnable() {
            @Override public void run() {
                File temporary = new File(getFilesDir(), "senseis-import.tmp");
                String error = null;
                try {
                    InputStream input = getContentResolver().openInputStream(uri);
                    if (input == null) throw new IllegalStateException("Cannot open selected file");
                    FileOutputStream output = new FileOutputStream(temporary);
                    byte[] buffer = new byte[1024 * 1024];
                    int read;
                    while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
                    output.flush();
                    output.getFD().sync();
                    output.close();
                    input.close();
                    SQLiteDatabase test = SQLiteDatabase.openDatabase(temporary.getAbsolutePath(), null, SQLiteDatabase.OPEN_READONLY);
                    Cursor check = test.rawQuery("SELECT value FROM metadata WHERE key='schema_version'", null);
                    boolean valid = check.moveToFirst() && "4".equals(check.getString(0));
                    check.close();
                    Cursor tables = test.rawQuery("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('files','pages','aliases')", null);
                    valid = valid && tables.moveToFirst() && tables.getInt(0) == 4;
                    tables.close();
                    test.close();
                    if (!valid) throw new IllegalArgumentException("This file is not a compatible Sensei's Library database");
                    if (database != null && database.isOpen()) database.close();
                    if (databaseFile.exists() && !databaseFile.delete()) throw new IllegalStateException("Cannot replace previous database");
                    if (!temporary.renameTo(databaseFile)) throw new IllegalStateException("Cannot install database file");
                } catch (Exception e) {
                    error = e.getMessage() == null ? e.toString() : e.getMessage();
                    temporary.delete();
                }
                final String finalError = error;
                mainHandler.post(new Runnable() {
                    @Override public void run() {
                        progress.setVisibility(View.GONE);
                        if (finalError != null) {
                            status.setText("Database import failed");
                            new AlertDialog.Builder(MainActivity.this).setTitle("Import failed").setMessage(finalError).setPositiveButton("OK", null).show();
                        } else if (openDatabase()) {
                            Toast.makeText(MainActivity.this, "Offline library imported", Toast.LENGTH_LONG).show();
                            showBrowser();
                        }
                    }
                });
            }
        }).start();
    }

    private boolean openDatabase() {
        try {
            if (database != null && database.isOpen()) database.close();
            database = SQLiteDatabase.openDatabase(databaseFile.getAbsolutePath(), null,
                    SQLiteDatabase.OPEN_READONLY | SQLiteDatabase.NO_LOCALIZED_COLLATORS);
            Cursor check = database.rawQuery("SELECT value FROM metadata WHERE key='schema_version'", null);
            boolean valid = check.moveToFirst() && "3".equals(check.getString(0));
            check.close();
            return valid;
        } catch (Exception e) {
            if (database != null && database.isOpen()) database.close();
            database = null;
            return false;
        }
    }

    private class SaveBridge {
        @JavascriptInterface
        public void saveSgf(final String urlPath) {
            mainHandler.post(new Runnable() {
                @Override public void run() { beginSgfSave(urlPath); }
            });
        }
    }

    private void beginSgfSave(String urlPath) {
        String path = normalizePath(decodePath(Uri.parse(urlPath).getEncodedPath()));
        if (path == null || !path.toLowerCase(Locale.ROOT).endsWith(".sgf")) {
            Toast.makeText(this, "This is not an SGF file", Toast.LENGTH_SHORT).show();
            return;
        }
        Cursor cursor = null;
        try {
            cursor = database.rawQuery("SELECT mime FROM files WHERE path=?", new String[]{path});
            if (!cursor.moveToFirst() || !"application/x-go-sgf".equals(cursor.getString(0))) {
                Toast.makeText(this, "SGF file not found in the database", Toast.LENGTH_SHORT).show();
                return;
            }
            pendingSgfPath = path;
            String fileName = path.substring(path.lastIndexOf('/') + 1);
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("application/x-go-sgf");
            intent.putExtra(Intent.EXTRA_TITLE, fileName);
            startActivityForResult(intent, REQUEST_SAVE_SGF);
        } catch (Exception e) {
            Toast.makeText(this, "Cannot save SGF: " + e.getMessage(), Toast.LENGTH_LONG).show();
        } finally { if (cursor != null) cursor.close(); }
    }

    private void savePendingSgf(final Uri destination) {
        if (pendingSgfPath == null || database == null) return;
        final String path = pendingSgfPath;
        pendingSgfPath = null;
        progress.setVisibility(View.VISIBLE);
        new Thread(new Runnable() {
            @Override public void run() {
                String error = null;
                try {
                    Cursor cursor = database.rawQuery("SELECT encoding FROM files WHERE path=?", new String[]{path});
                    if (!cursor.moveToFirst()) throw new IllegalStateException("SGF data is missing");
                    String encoding = cursor.getString(0);
                    cursor.close();
                    InputStream input = openPayloadStream(path, encoding);
                    OutputStream output = getContentResolver().openOutputStream(destination);
                    if (output == null) throw new IllegalStateException("Cannot open destination");
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                    output.flush();
                    output.close();
                    input.close();
                } catch (Exception e) { error = e.getMessage() == null ? e.toString() : e.getMessage(); }
                final String finalError = error;
                mainHandler.post(new Runnable() {
                    @Override public void run() {
                        progress.setVisibility(View.GONE);
                        Toast.makeText(MainActivity.this, finalError == null ? "SGF saved" : "SGF save failed: " + finalError, Toast.LENGTH_LONG).show();
                    }
                });
            }
        }).start();
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) webView.destroy();
        if (database != null && database.isOpen()) database.close();
        super.onDestroy();
    }
}
