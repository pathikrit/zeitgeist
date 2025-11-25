<%!
    from markdown_it import MarkdownIt
%>
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.classless.min.css">
    <title>Report ${today.strftime("%d-%b-%Y")}</title>
</head>
<body>
<main>
    <a href="https://github.com/pathikrit/zeitgeist" target="_blank" rel="noopener" style="float: right;">
        <img src="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png" alt="GitHub" width="30" height="30">
    </a>
    <a href="https://pathikrit.github.io/zeitgeist/" style="float: right; text-decoration: none; font-size: 28px; margin-right: 10px;">
        🔄
    </a>
    ${MarkdownIt().render(report) | n}
</main>
<script>
document.addEventListener("DOMContentLoaded", () => {
    // Force all markdown-generated links to open in a new tab
    // TODO: In the future, experiment with CSS target-new once browser support improves.
    document.querySelectorAll("a[href]").forEach(a => {
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener noreferrer");
    });
});
</script>
</body>
</html>
