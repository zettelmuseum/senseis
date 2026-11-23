package de.zettelmuseum.senseis;

public final class SgfHtmlPreprocessorTest {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        String html = "<html><head></head><body>"
                + "<div class='diagram'><p>Killing Shapes</p>"
                + "<a class='sl-s4-sgf' href='files/shape.sgf?download=1'>"
                + "<img src='preview.svg' alt='diagram preview'></a></div>"
                + "<a href='files/readme.txt'>Text file</a>"
                + "<img src='images/logo.png' alt='logo'>"
                + "</body></html>";
        String prepared = SgfHtmlPreprocessor.prepare(
                html, "https://senseis.local/__app/senseis-page.js");

        check(prepared.contains("data-senseis-sgf=\"files/shape.sgf?download=1\""),
                "SGF link URL was not preserved");
        check(prepared.contains("class=\"senseis-sgf-placeholder\""),
                "SGF link was not replaced by a placeholder");
        check(!prepared.contains("preview.svg"),
                "Embedded preview content was not removed before WebView parsing");
        check(prepared.contains("<p>Killing Shapes</p>"),
                "Diagram caption was not preserved");
        check(prepared.contains("href='files/readme.txt'>Text file</a>"),
                "Non-SGF links must remain unchanged");
        check(prepared.contains("src='images/logo.png' alt='logo' loading=\"lazy\""),
                "Ordinary images must be marked lazy before parsing");
        check(prepared.contains("decoding=\"async\"") && prepared.contains("fetchpriority=\"low\""),
                "Image decode and fetch priority hints are missing");
        check(prepared.contains("senseis-page.js"),
                "The local page script was not injected into the HTML response");

        String twice = SgfHtmlPreprocessor.prepare(
                prepared, "https://senseis.local/__app/senseis-page.js");
        check(count(twice, "class=\"senseis-sgf-placeholder\"") == 1,
                "Preprocessing must be idempotent");
        check(count(twice, "senseis-page.js") == 1,
                "The local page script must not be injected twice");

        String upper = SgfHtmlPreprocessor.replaceSgfAnchors(
                "<a href=\"/FILES/UPPER.SGF#move\">Open</a>");
        check(upper.contains("data-senseis-sgf=\"/FILES/UPPER.SGF#move\""),
                "Uppercase SGF suffix or fragment was not recognized");

        System.out.println("SGF HTML preprocessor tests passed");
    }

    private static int count(String value, String token) {
        int count = 0;
        int at = 0;
        while ((at = value.indexOf(token, at)) >= 0) {
            count++;
            at += token.length();
        }
        return count;
    }
}
