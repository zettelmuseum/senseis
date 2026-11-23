(function () {
"use strict";

var LOCAL = "https://senseis.local/";
var active = null;
var besogoPromise = null;

function localUrl(raw, base) {
    try {
        if (raw.charAt(0) === "?") return LOCAL + raw;
        var url = new URL(raw, base || document.baseURI);
        if (!/^(senseis\.xmp\.net|www\.senseis\.xmp\.net|senseis\.local)$/i.test(url.hostname)) return null;
        url.protocol = "https:";
        url.hostname = "senseis.local";
        url.port = "";
        if (url.pathname === "/" && url.search.length > 1) return LOCAL + url.search + url.hash;
        return url.href;
    } catch (error) {
        return null;
    }
}

function mapInternalUrls() {
    document.querySelectorAll("a[href],script[src],link[href],source[src],img[src]").forEach(function (element) {
        var attribute = element.tagName === "A" || element.tagName === "LINK" ? "href" : "src";
        var raw = element.getAttribute(attribute);
        if (!raw || /^(#|mailto:|tel:|javascript:|data:|blob:)/i.test(raw)) return;
        var mapped = localUrl(raw);
        if (mapped) element.setAttribute(attribute, mapped);
    });

    document.querySelectorAll("[data-senseis-sgf]").forEach(function (element) {
        var mapped = localUrl(element.getAttribute("data-senseis-sgf"));
        if (mapped) element.setAttribute("data-senseis-sgf", mapped);
    });

    document.querySelectorAll("img[src]").forEach(function (image) {
        image.loading = "lazy";
        image.decoding = "async";
        image.setAttribute("fetchpriority", "low");
    });

    document.querySelectorAll("base").forEach(function (base) {
        base.remove();
    });
}

function loadBesogo() {
    if (!besogoPromise) {
        besogoPromise = new Promise(function (resolve, reject) {
            var css = document.createElement("link");
            css.rel = "stylesheet";
            css.href = LOCAL + "__app/besogo.css";
            document.head.appendChild(css);

            var theme = document.createElement("link");
            theme.rel = "stylesheet";
            theme.href = LOCAL + "__app/board-sensei.css";
            document.head.appendChild(theme);

            var script = document.createElement("script");
            script.src = LOCAL + "__app/besogo.all.js";
            script.onload = resolve;
            script.onerror = function () {
                reject(new Error("BesoGo could not be loaded"));
            };
            document.head.appendChild(script);
        }).catch(function (error) {
            besogoPromise = null;
            throw error;
        });
    }
    return besogoPromise;
}

function restoreActive() {
    if (!active) return;
    var old = active;
    active = null;

    if (old.abortController) {
        try { old.abortController.abort(); } catch (ignored) { }
    }
    if (old.board) {
        old.board.textContent = "";
        old.board.besogoEditor = null;
    }
    if (old.panel.parentNode) old.panel.replaceWith(old.placeholder);

    old.panel = null;
    old.board = null;
    old.placeholder = null;
    old.abortController = null;
}

function openDiagram(placeholder) {
    var sgfUrl = placeholder.getAttribute("data-senseis-sgf");
    if (!sgfUrl) return;

    restoreActive();

    var panel = document.createElement("div");
    panel.className = "senseis-sgf-panel";

    var close = document.createElement("button");
    close.type = "button";
    close.className = "senseis-sgf-close";
    close.textContent = "Close diagram";
    close.setAttribute("aria-label", "Close interactive Go diagram");

    var board = document.createElement("div");
    board.className = "senseis-sgf-board";
    board.setAttribute("aria-label", "Go diagram");

    panel.appendChild(close);
    panel.appendChild(board);
    placeholder.replaceWith(panel);

    var controller = typeof window.AbortController === "function" ? new AbortController() : null;
    var current = {
        panel: panel,
        board: board,
        placeholder: placeholder,
        abortController: controller
    };
    active = current;

    close.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (active === current) restoreActive();
    });

    board.textContent = "Loading diagram…";

    var fetchOptions = { credentials: "same-origin" };
    if (controller) fetchOptions.signal = controller.signal;

    Promise.all([
        loadBesogo(),
        fetch(sgfUrl, fetchOptions).then(function (response) {
            if (!response.ok) throw new Error("SGF not found");
            return response.text();
        })
    ]).then(function (results) {
        if (active !== current) return;
        var sgf = results[1];
        if (!/\(\s*;/.test(sgf.slice(0, 1200))) throw new Error("Invalid SGF");

        board.textContent = sgf;
        window.besogo.create(board, {
            panels: ["control", "comment"],
            tool: "navOnly",
            orient: "portrait",
            nowheel: true,
            nokeys: true,
            resize: "fixed",
            shadows: "off"
        });
        board.setAttribute("aria-label", "Interactive Go diagram");
    }).catch(function () {
        if (active !== current) return;
        board.className = "senseis-sgf-error";
        board.textContent = "SGF diagram unavailable. ";
        var retry = document.createElement("button");
        retry.type = "button";
        retry.textContent = "Retry";
        retry.addEventListener("click", function () {
            if (active !== current) return;
            restoreActive();
            openDiagram(placeholder);
        });
        board.appendChild(retry);
    });
}

function enforceDarkPage() {
    if (document.documentElement.getAttribute("data-senseis-dark") !== "1") return;
    function apply(node) {
        if (!node || node.nodeType !== 1 || !node.style) return;
        var tag = node.tagName;
        if (/^(IMG|SVG|CANVAS|VIDEO|IFRAME)$/i.test(tag)) return;
        node.removeAttribute("bgcolor");
        node.style.removeProperty("background");
        node.style.removeProperty("background-color");
        if (node === document.documentElement || node === document.body) {
            node.style.setProperty("background-color", "#17191c", "important");
        } else {
            node.style.setProperty("background-color", "transparent", "important");
        }
    }
    apply(document.documentElement);
    apply(document.body);
    function scan(root) {
        if (!root || !root.querySelectorAll) return;
        var all = root.querySelectorAll("*");
        for (var i = 0; i < all.length; i++) apply(all[i]);
    }
    scan(document.body);
    if (!window.__senseisDarkObserver && window.MutationObserver) {
        window.__senseisDarkObserver = new MutationObserver(function (records) {
            records.forEach(function (record) {
                if (record.type === "attributes") apply(record.target);
                for (var i = 0; i < record.addedNodes.length; i++) {
                    var node = record.addedNodes[i];
                    if (node.nodeType === 1) { apply(node); scan(node); }
                }
            });
        });
        window.__senseisDarkObserver.observe(document.documentElement, {
            subtree: true, childList: true, attributes: true,
            attributeFilter: ["style", "bgcolor"]
        });
    }
}

function enhance() {
    var style = document.createElement("style");
    style.textContent =
        "body{max-width:100%;margin:0 auto;padding:12px;line-height:1.45;overflow-wrap:anywhere}" +
        "img,video,svg{max-width:100%;height:auto}" +
        "table{max-width:100%;border-collapse:collapse;display:block;overflow-x:auto}" +
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere}" +
        ".besogo-container{max-width:100%;margin:14px auto!important}" +
        ".besogo-panels{max-width:100%}.besogo-comment{max-height:180px;overflow:auto}";
    if (document.documentElement.getAttribute("data-senseis-dark") === "1") {
        style.textContent +=
            "html,html body{background:#17191c!important;color:#e5e5e5!important;color-scheme:dark}" +
            "html body *:not(img):not(svg):not(canvas):not(video):not(iframe){color:#e5e5e5!important;background-color:transparent!important;border-color:#555!important}" +
            "html body a,html body a *{color:#8ab4f8!important}" +
            "html body a:visited,html body a:visited *{color:#c6a5e8!important}" +
            "html body h1,html body h2,html body h3,html body h4,html body h5,html body h6{color:#f0f0f0!important}" +
            "html body table,html body th,html body td{background:#24282d!important;color:#e5e5e5!important;border-color:#555!important}" +
            "html body input,html body textarea,html body select,html body button{background:#292d33!important;color:#eee!important;border:1px solid #666!important}" +
            "html body pre,html body code,html body blockquote{background:#25292e!important;color:#e5e5e5!important}" +
            "html body .senseis-sgf-placeholder{background:#34302a!important;color:#f2dfbd!important}" +
            "html body .senseis-sgf-panel{background:#25282c!important;border-color:#555!important}";
    }
    document.head.appendChild(style);
    mapInternalUrls();
    enforceDarkPage();
}

document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var placeholder = target.closest("[data-senseis-sgf]");
    if (!placeholder) return;
    event.preventDefault();
    event.stopPropagation();
    openDiagram(placeholder);
}, true);

document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && active) {
        event.preventDefault();
        restoreActive();
    }
}, true);

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", enhance);
} else {
    enhance();
}
})();