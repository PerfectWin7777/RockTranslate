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
    // Immediate pass: what a full browser's --dump-dom captures (no virtual
    // time there); refined once fonts settle when virtual time is available.
    var old = document.getElementById('rt-geometry'); if (old) old.remove();
    measure();
    var go = function () { setTimeout(function () {
      var prev = document.getElementById('rt-geometry'); if (prev) prev.remove();
      measure();
    }, 50); };
    if (document.fonts && document.fonts.ready) {
      document.fonts.forEach(function (f) { try { f.load(); } catch (e) {} });
      document.fonts.ready.then(go);
    } else { go(); }
  });
})();
</script>
"""


def _is_headless_shell(path: str) -> bool:
    return "headless" in os.path.basename(path).lower()


_PROBE_PAGE = ("<html><body><div id=x style='width:123px'>x</div><script>"
               "window.addEventListener('load',function(){var p=document.createElement('pre');"
               "p.id='rt-probe';p.textContent=document.getElementById('x').offsetWidth;"
               "document.body.appendChild(p);});</script></body></html>")


def _probe_full_browser(browser: str, timeout: float = 10.0) -> bool:
    """
    A desktop browser (Edge, Chrome) is used for measuring if it answers a tiny
    page through the DevTools protocol within a few seconds. The verdict is
    remembered per executable (and version, via its mtime).
    """
    try:
        from .config_manager import config_db
        verdicts = config_db.get("SystemConfig", "geometry_browser_ok_cdp", {}) or {}
    except Exception:
        config_db, verdicts = None, {}
    key = f"{browser}|{int(os.path.getmtime(browser)) if os.path.exists(browser) else 0}"
    if key in verdicts:
        return bool(verdicts[key])
    ok = False
    tmp = tempfile.mkdtemp(prefix="rocktranslate-probe-")
    try:
        page = os.path.join(tmp, "probe.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write("<html><body><div id=x style='width:123px'>x</div></body></html>")
        from .cdp import evaluate_in_page
        url = "file:///" + os.path.abspath(page).replace(os.sep, "/").lstrip("/")
        value = evaluate_in_page(browser, url,
                                 "location.href.startsWith('file:') ? document.getElementById('x').offsetWidth : null",
                                 timeout)
        ok = value == 123
    except Exception:
        ok = False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    logger.info(f"Geometry browser probe: {browser} -> {'usable' if ok else 'unusable'}")
    if config_db is not None:
        verdicts[key] = ok
        config_db.set("SystemConfig", "geometry_browser_ok_cdp", verdicts)
    return ok


def _cmd(browser: str, page: str, profile: str) -> List[str]:
    shell = _is_headless_shell(browser)
    cmd = [browser, "--headless" if shell else "--headless=new", "--disable-gpu", "--no-first-run",
           "--no-default-browser-check", "--disable-extensions", f"--user-data-dir={profile}",
           "--window-size=1600,1200", "--dump-dom", "file://" + os.path.abspath(page).replace(os.sep, "/")]
    if shell:
        # Virtual time is reliable in the headless shell only: in a desktop
        # browser's new headless mode it can stall --dump-dom indefinitely.
        cmd.insert(-2, "--virtual-time-budget=20000")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    return cmd


def _browser() -> Optional[str]:
    """
    Measuring engine, in order: ROCKTRANSLATE_BROWSER, the downloaded
    chrome-headless-shell, then an installed browser (Edge first on Windows,
    Chrome / Chromium / Brave, macOS apps) that passes a quick probe.
    Nothing usable -> None, callers use estimates. Never downloads anything.
    """
    env = os.environ.get("ROCKTRANSLATE_BROWSER")
    if env and os.path.isfile(env):
        return env
    try:
        from .downloader import find_downloaded_headless_shell
        shell = find_downloaded_headless_shell()
        if shell:
            return shell
    except Exception:
        pass
    try:
        from .renderer import _candidate_browser_paths
        candidates = [p for p in _candidate_browser_paths() if p and os.path.isfile(p)]
    except Exception:
        candidates = []
    # Edge first: present on every Windows 10/11
    candidates.sort(key=lambda p: 0 if "edge" in p.lower() else 1)
    for path in candidates:
        if path not in _FAILED_BROWSERS and _probe_full_browser(path):
            return path
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
    if _is_headless_shell(browser):
        result = _measure_with(browser, raw_html_path, timeout)
    else:
        result = _measure_via_devtools(browser, raw_html_path, timeout)
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
            cmd = _cmd(browser, page, os.path.join(tmp, "profile"))
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


_CDP_MEASURE = r"""
(async () => {
  if (!location.href.startsWith('file:')) return null;
  if (document.readyState !== 'complete') await new Promise(r => window.addEventListener('load', r, {once: true}));
  if (document.fonts && document.fonts.ready) {
    document.fonts.forEach(f => { try { f.load(); } catch (e) {} });
    await document.fonts.ready;
  }
  await new Promise(r => setTimeout(r, 50));
  document.querySelectorAll('.pc').forEach(p => { p.style.display = 'block'; });
  const out = [];
  document.querySelectorAll('.pf').forEach(pf => {
    const pr = pf.getBoundingClientRect();
    const k = (pf.offsetWidth && pr.width) ? pr.width / pf.offsetWidth : 1;
    const boxes = [];
    pf.querySelectorAll('div.t').forEach(d => {
      const r = d.getBoundingClientRect();
      boxes.push([((r.left - pr.left) / k).toFixed(2), ((r.right - pr.left) / k).toFixed(2),
                  ((r.top - pr.top) / k).toFixed(2), ((r.bottom - pr.top) / k).toFixed(2)].join(','));
    });
    out.push(boxes.join(';'));
  });
  return out.join('|');
})()
"""


def _parse_blob(blob: str) -> List[List[Box]]:
    pages: List[List[Box]] = []
    for page_blob in blob.split("|"):
        boxes: List[Box] = []
        for item in filter(None, page_blob.split(";")):
            l, r, t, b = (float(v) for v in item.split(","))
            boxes.append((l, r, t, b))
        pages.append(boxes)
    return pages


def _measure_via_devtools(browser: str, raw_html_path: str, timeout: float) -> Optional[List[List[Box]]]:
    """Desktop Chrome / Edge, driven through the DevTools protocol."""
    from .cdp import evaluate_in_page
    url = "file:///" + os.path.abspath(raw_html_path).replace(os.sep, "/").lstrip("/")
    blob = evaluate_in_page(browser, url, _CDP_MEASURE, timeout)
    if not isinstance(blob, str):
        logger.warning(f"Geometry pass via DevTools failed ({os.path.basename(browser)}); using estimates.")
        return None
    return _parse_blob(blob)
