"""Embed do relatório HTML no Streamlit (sem iframe duplo / navegação quebrada)."""

from __future__ import annotations

import re

# Estilos para integrar o relatório escuro ao layout Streamlit (iframe sem borda).
EMBED_STYLES = """
<style id="depara-streamlit-embed">
  html, body {
    margin: 0;
    max-width: none;
    padding: 0.5rem 0.25rem 1rem;
  }
</style>
"""

# Ancoras #sec-* rolam dentro do iframe; auto-altura evita scroll duplo.
EMBED_SCRIPT = """
<script>
(function () {
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener("click", function (e) {
      var id = a.getAttribute("href").slice(1);
      var el = document.getElementById(id);
      if (el) {
        e.preventDefault();
        el.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  function sendHeight() {
    var h = Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight,
      document.documentElement.offsetHeight
    );
    window.parent.postMessage(
      { type: "streamlit:setFrameHeight", height: h + 24 },
      "*"
    );
  }

  sendHeight();
  window.addEventListener("load", sendHeight);
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(sendHeight).observe(document.documentElement);
  }
  setTimeout(sendHeight, 400);
  setTimeout(sendHeight, 1200);
})();
</script>
"""

IFRAME_CHROME_CSS = """
<style>
  [data-testid="stHtml"] iframe,
  [data-testid="stIFrame"] iframe {
    border: none !important;
    width: 100% !important;
    display: block;
    background: #0f1419;
    border-radius: 8px;
  }
</style>
"""


def artifact_url(base_url: str, job_id: str, name: str) -> str:
    return f"{base_url.rstrip('/')}/v1/jobs/{job_id}/artifacts/{name}"


def prepare_html_for_embed(html: str) -> str:
    """Injeta CSS/JS para embed seamless no Streamlit."""
    if 'id="depara-streamlit-embed"' in html:
        return html

    if "</head>" in html:
        html = html.replace("</head>", EMBED_STYLES + "</head>", 1)
    else:
        html = EMBED_STYLES + html

    if "</body>" in html:
        return html.replace("</body>", EMBED_SCRIPT + "</body>", 1)
    return html + EMBED_SCRIPT


def estimate_report_height(html: str, *, default: int = 1200, maximum: int = 4800) -> int:
    """Estimativa inicial antes do postMessage ajustar a altura."""
    sections = html.count("<section")
    rows = len(re.findall(r"<tr[^>]*>", html))
    tall = 600 + sections * 320 + min(rows, 80) * 28
    return max(default, min(tall, maximum))
