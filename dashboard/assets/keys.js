// Terminal keyboard shortcuts: F1/F2 switch pages, "/" or Ctrl+K focuses the command line.
document.addEventListener("keydown", function (e) {
    var keys = { F1: "fkey-book", F2: "fkey-fed" };
    if (keys[e.key]) {
        var link = document.getElementById(keys[e.key]);
        if (link) { e.preventDefault(); link.click(); }
        return;
    }
    var typing = e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA");
    if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey))) {
        var cmd = document.getElementById("cmd");
        if (cmd) { e.preventDefault(); cmd.focus(); cmd.select(); }
    }
});
