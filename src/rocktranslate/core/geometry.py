"""
RockTranslate — Measured text geometry
Path: src/rocktranslate/core/geometry.py

Renders the raw pdf2htmlEX document ONCE in headless Chromium and records the
exact box of every text line (div.t): left, right, top, bottom in page CSS
pixels. Layout decisions (same visual line, table cells, paragraph ends,
columns) are then taken from REAL geometry instead of estimates such as
"average glyph width", which hold for one document and break on the next.

Returns None when no Chromium is available: callers fall back to the
estimate-based heuristics.

License: MIT License
"""

import os
import re
import subprocess
import tempfile
from typing import List, Optional, Tuple

from loguru import logger

Box = Tuple[float, float, float, float]  # left, right, top, bottom

_PROBE = """
<script>
(function () {
  function measure() {
    document.querySelectorAll('.pc').forEach(function (p) { p.style.display = 'block'; });
    var out = [];
    document.querySelectorAll('.pf').forEach(function (pf) {
      var pr = pf.getBoundingClientRect();
      var k = (pf.offsetWidth && pr.width) ? pr.width / pf.offsetWidth : 1;
      var boxes = [];
      pf.querySelectorAll('div.t').forEach(function (d) {
        var r = d.getBoundingClientRect();
        boxes.push([((r.left - pr.left) / k).toFixed(2), ((r.right - pr.left) / k).toFixed(2),
                    ((r.top - pr.top) / k).toFixed(2), ((r.bottom - pr.top) / k).toFixed(2)].join(','));
      });
      out.push(boxes.join(';'));
    });
    var pre = document.createElement('pre');
    pre.id = 'rt-geometry';
    pre.textContent = out.join('|');
    document.body.appendChild(pre);
  }
  window.addEventListener('load', function () {
    var go = function () { setTimeout(measure, 50); };
    if (document.fonts && document.fonts.ready) {
      document.fonts.forEach(function (f) { try { f.load(); } catch (e) {} });
      document.fonts.ready.then(go);
    } else { go(); }
  });
})();
</script>
"""


def _browser() -> Optional[str]:
    """
    Only a dedicated, already-present headless engine is used: an installed
    desktop Chrome may hang in headless mode (seen on Windows and Linux) and a
    download must never delay a translation. No engine -> estimates are used.
    """
    env = os.environ.get("ROCKTRANSLATE_BROWSER")
    if env and os.path.isfile(env):
        return env
    try:
        from .downloader import find_downloaded_headless_shell
        return find_downloaded_headless_shell()
    except Exception:
        return None


# Browsers that failed to measure in this process (e.g. a full Chrome that
# hangs in headless mode): never retried, the pinned headless shell is used.
_FAILED_BROWSERS: set = set()


def measure_line_boxes(raw_html_path: str, timeout: Optional[float] = None) -> Optional[List[List[Box]]]:
    """
    Exact boxes of every div.t, per page, in document order.
    Returns None if measuring is unavailable or fails (callers then fall back).
    """
    if os.environ.get("ROCKTRANSLATE_NO_GEOMETRY"):
        return None
    browser = _browser()
    if not browser or browser in _FAILED_BROWSERS:
        return None
    if timeout is None:
        try:
            with open(raw_html_path, "r", encoding="utf-8", errors="ignore") as f:
                pages = f.read().count('class="pf ')
        except OSError:
            pages = 10
        timeout = min(120.0, 20.0 + 1.5 * pages)
    result = _measure_with(browser, raw_html_path, timeout)
    if result is None:
        _FAILED_BROWSERS.add(browser)
    return result


def _measure_with(browser: str, raw_html_path: str, timeout: float) -> Optional[List[List[Box]]]:
    try:
        with open(raw_html_path, "r", encoding="utf-8") as f:
            html = f.read()
        idx = html.rfind("</body>")
        probe_html = (html[:idx] + _PROBE + html[idx:]) if idx != -1 else html + _PROBE
        with tempfile.TemporaryDirectory(prefix="rocktranslate-geo-") as tmp:
            # Same directory as the raw HTML is not required: pdf2htmlEX embeds assets
            page = os.path.join(tmp, "probe.html")
            with open(page, "w", encoding="utf-8") as f:
                f.write(probe_html)
            cmd = [browser, "--headless" if "headless-shell" in os.path.basename(browser).lower() else "--headless=new",
                   "--disable-gpu", "--no-first-run", f"--user-data-dir={os.path.join(tmp, 'profile')}",
                   "--virtual-time-budget=20000", "--window-size=1600,1200", "--dump-dom",
                   "file://" + os.path.abspath(page).replace(os.sep, "/")]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                cmd.insert(1, "--no-sandbox")
            from .proc import run_with_timeout
            code, out, _err = run_with_timeout(cmd, timeout)
            if code is None:
                logger.warning(f"Geometry pass timed out after {timeout:.0f}s; using estimates.")
                return None
        dom = out.decode("utf-8", "replace")
        m = re.search(r'<pre id="rt-geometry">([^<]*)</pre>', dom)
        if not m:
            logger.warning("Geometry pass produced no measurements; using estimates.")
            return None
        pages: List[List[Box]] = []
        for page_blob in m.group(1).split("|"):
            boxes: List[Box] = []
            for item in filter(None, page_blob.split(";")):
                l, r, t, b = (float(v) for v in item.split(","))
                boxes.append((l, r, t, b))
            pages.append(boxes)
        return pages
    except Exception as e:
        logger.warning(f"Geometry pass failed ({e}); using estimates.")
        return None
