package de.zettelmuseum.senseis;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Rewrites SGF hyperlinks before WebView parses an archived HTML page.
 * The link's expensive embedded contents (including any preview element) are
 * discarded; only a small, lazy-open placeholder and its SGF URL remain.
 */
final class SgfHtmlPreprocessor {
    private static final Pattern SGF_ANCHOR =
            Pattern.compile("(?is)<a\\b([^>]*)>(.*?)</a\\s*>");
    private static final Pattern HREF_ATTRIBUTE =
            Pattern.compile("(?is)(?:^|\\s)href\\s*=\\s*(?:\"([^\"]*)\"|'([^']*)'|([^\\s>]+))");
    private static final Pattern IMG_TAG = Pattern.compile("(?is)<img\\b[^>]*>");
    private static final Pattern ATTRIBUTE =
            Pattern.compile("(?is)(?:^|\\s)%s\\s*=");
    private static final Pattern END_HEAD = Pattern.compile("(?i)</head\\s*>");
    private static final String PLACEHOLDER_STYLE =
            "<style>" +
            ".senseis-sgf-placeholder{display:inline-flex;align-items:center;justify-content:center;" +
            "min-width:148px;min-height:42px;margin:4px;padding:8px 12px;" +
            "border:1px solid #b59a70;border-radius:5px;background:#f3e4ca;color:#29231a;" +
            "font:600 14px sans-serif;cursor:pointer}" +
            ".senseis-sgf-placeholder:active{background:#e5d0aa}" +
            ".senseis-sgf-panel{max-width:640px;margin:12px auto;padding:8px;" +
            "border:1px solid #c9b58f;background:#f6ead4}" +
            ".senseis-sgf-close{display:block;margin:0 0 8px auto;padding:6px 12px}" +
            ".senseis-sgf-board{width:100%;max-width:640px;margin:0 auto}" +
            ".senseis-sgf-error{padding:12px;color:#8b1b1b;background:#fff0f0}" +
            "</style>";

    private SgfHtmlPreprocessor() { }

    static String prepare(String html, String scriptUrl) {
        if (html == null) return "";
        String result = replaceSgfAnchors(html);
        result = makeImagesLazy(result);
        return injectAppResources(result, scriptUrl);
    }

    static String replaceSgfAnchors(String html) {
        Matcher anchors = SGF_ANCHOR.matcher(html);
        StringBuffer out = new StringBuffer(html.length());
        while (anchors.find()) {
            String attributes = anchors.group(1);
            Matcher href = HREF_ATTRIBUTE.matcher(attributes);
            if (!href.find()) {
                anchors.appendReplacement(out, Matcher.quoteReplacement(anchors.group(0)));
                continue;
            }
            String url = href.group(1) != null ? href.group(1)
                    : href.group(2) != null ? href.group(2) : href.group(3);
            url = decodeBasicEntities(url);
            if (!isSgfUrl(url)) {
                anchors.appendReplacement(out, Matcher.quoteReplacement(anchors.group(0)));
                continue;
            }
            String placeholder = "<button type=\"button\" class=\"senseis-sgf-placeholder\""
                    + " data-senseis-sgf=\"" + escapeAttribute(url) + "\""
                    + " aria-label=\"Open Go diagram\">Open Go diagram</button>";
            anchors.appendReplacement(out, Matcher.quoteReplacement(placeholder));
        }
        anchors.appendTail(out);
        return out.toString();
    }

    private static boolean isSgfUrl(String value) {
        if (value == null) return false;
        String path = value.trim();
        int query = path.indexOf('?');
        int fragment = path.indexOf('#');
        int end = path.length();
        if (query >= 0 && query < end) end = query;
        if (fragment >= 0 && fragment < end) end = fragment;
        return path.substring(0, end).toLowerCase(Locale.ROOT).endsWith(".sgf");
    }

    private static String makeImagesLazy(String html) {
        Matcher images = IMG_TAG.matcher(html);
        StringBuffer out = new StringBuffer(html.length());
        while (images.find()) {
            String tag = images.group();
            if (!hasAttribute(tag, "loading")) tag = addAttribute(tag, "loading=\"lazy\"");
            if (!hasAttribute(tag, "decoding")) tag = addAttribute(tag, "decoding=\"async\"");
            if (!hasAttribute(tag, "fetchpriority")) tag = addAttribute(tag, "fetchpriority=\"low\"");
            images.appendReplacement(out, Matcher.quoteReplacement(tag));
        }
        images.appendTail(out);
        return out.toString();
    }

    private static boolean hasAttribute(String tag, String name) {
        Pattern p = Pattern.compile(String.format(Locale.ROOT,
                ATTRIBUTE.pattern(), Pattern.quote(name)));
        return p.matcher(tag).find();
    }

    private static String addAttribute(String tag, String attribute) {
        int end = tag.lastIndexOf('>');
        if (end < 0) return tag;
        int insert = end;
        if (insert > 0 && tag.charAt(insert - 1) == '/') insert--;
        return tag.substring(0, insert) + " " + attribute + tag.substring(insert);
    }

    private static String injectAppResources(String html, String scriptUrl) {
        boolean hasScript = html.indexOf("senseis-page.js") >= 0;
        boolean hasPlaceholders = html.indexOf("senseis-sgf-placeholder") >= 0;
        StringBuilder additions = new StringBuilder();
        if (hasPlaceholders && html.indexOf("senseis-sgf-placeholder{") < 0) {
            additions.append(PLACEHOLDER_STYLE);
        }
        if (!hasScript && scriptUrl != null && scriptUrl.length() > 0) {
            additions.append("<script defer src=\"")
                    .append(escapeAttribute(scriptUrl))
                    .append("\"></script>");
        }
        if (additions.length() == 0) return html;

        Matcher endHead = END_HEAD.matcher(html);
        if (endHead.find()) {
            return html.substring(0, endHead.start()) + additions
                    + html.substring(endHead.start());
        }
        return additions + html;
    }

    private static String decodeBasicEntities(String value) {
        return value.replace("&amp;", "&").replace("&#38;", "&")
                .replace("&#x26;", "&").replace("&quot;", "\"")
                .replace("&#39;", "'");
    }

    private static String escapeAttribute(String value) {
        return value.replace("&", "&amp;").replace("\"", "&quot;")
                .replace("<", "&lt;").replace(">", "&gt;");
    }
}
