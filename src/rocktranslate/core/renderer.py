"""
RockTranslate — Headless Browser PDF Vector Renderer
Path: src/rocktranslate/core/renderer.py

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import sys
import shutil
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Optional

if sys.platform == "win32":
    import winreg
else:
    winreg = None



def _is_confined_package(path: str) -> bool:
    """Snap/Flatpak browsers cannot read our temp files: never use them headless."""
    real = os.path.realpath(path)
    return real.startswith(("/snap/", "/var/lib/snapd/")) or "/flatpak/" in real or real.endswith("/snap")


def _candidate_browser_paths() -> list:
    """Well-known install locations per OS (checked in order)."""
    candidates = []
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        rel_paths = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",   # always present on Windows 10/11
            r"Chromium\Application\chrome.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
        for root in roots:
            if root:
                candidates += [os.path.join(root, rel) for rel in rel_paths]
    elif sys.platform == "darwin":
        apps = [
            "Google Chrome.app/Contents/MacOS/Google Chrome",
            "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "Chromium.app/Contents/MacOS/Chromium",
            "Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
        for root in ("/Applications", os.path.expanduser("~/Applications")):
            candidates += [os.path.join(root, app) for app in apps]
    else:
        candidates += [
            "/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/opt/google/chrome/chrome",
            "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/lib/chromium/chromium",
            "/usr/bin/microsoft-edge", "/usr/bin/brave-browser",
        ]
    return candidates


def find_system_chromium_browser() -> Optional[str]:
    """
    Finds an installed Chromium-based browser usable for headless printing.

    Order: ROCKTRANSLATE_BROWSER env / settings override -> PATH commands ->
    well-known install paths -> Windows registry. Firefox is never used (its
    headless print-to-PDF has no equivalent CLI), snap/flatpak builds are
    skipped (sandboxed: cannot read temp files).
    """
    override = os.environ.get("ROCKTRANSLATE_BROWSER") or ""
    if not override:
        try:
            from .config_manager import config_db
            override = str(config_db.get("SystemConfig", "browser_path_override", "") or "")
        except Exception:
            override = ""
    if override and os.path.isfile(override):
        return override

    for cmd in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "chrome", "microsoft-edge", "msedge", "brave-browser"):
        resolved = shutil.which(cmd)
        if resolved and not _is_confined_package(resolved):
            return resolved

    for path in _candidate_browser_paths():
        if os.path.isfile(path) and not _is_confined_package(path):
            return path

    if sys.platform == "win32" and winreg:
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for exe in ("chrome.exe", "msedge.exe", "brave.exe"):
                try:
                    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
                    with winreg.OpenKey(hive, key_path) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                        if value and os.path.isfile(value.strip('"')):
                            return value.strip('"')
                except OSError:
                    continue
    return None


def build_page_size_css(html_content: str) -> str:
    """
    Builds print rules giving EVERY page its own physical size.

    pdf2htmlEX's print stylesheet sizes each page box (.pf.wN.hM) in pt at 4/3
    of the real PDF size; Chromium then shrinks the content to the paper. A
    single @page size (the old behaviour, from page 1 only) therefore broke
    documents mixing portrait and landscape pages. Named pages fix that.
    """
    def print_dims(prefix: str, prop: str) -> Dict[str, float]:
        dims: Dict[str, float] = {}
        for m in re.finditer(r"\.(" + prefix + r"[0-9a-f]+)\{" + prop + r":([\d.]+)pt;\}", html_content):
            dims[m.group(1)] = float(m.group(2)) * 0.75
        return dims

    widths, heights = print_dims("w", "width"), print_dims("h", "height")
    combos = []
    for m in re.finditer(r'<div[^>]+class="pf ([^"]+)"', html_content):
        classes = m.group(1).split()
        w = next((c for c in classes if c in widths), None)
        h = next((c for c in classes if c in heights), None)
        if w and h and (w, h) not in combos:
            combos.append((w, h))

    if not combos:
        return "<style>@page { margin: 0; } body { margin: 0; padding: 0; }</style>"

    # Chromium rounds page boxes down to whole device units: a fractional page
    # height (e.g. 793.70pt for A4 at 1/72") made the content overflow by a
    # fraction of a point and produced one blank page after every page.
    # A 0.5pt height tolerance (invisible, <0.07%) prevents it.
    heights = {k: v + 0.5 for k, v in heights.items()}

    # Default size = the most frequent page size (not the first page's: a
    # rotated landscape table page must not set the size of the whole document)
    counts = {}
    for m in re.finditer(r'<div[^>]+class="pf ([^"]+)"', html_content):
        classes = m.group(1).split()
        w = next((c for c in classes if c in widths), None)
        h = next((c for c in classes if c in heights), None)
        if w and h:
            counts[(w, h)] = counts.get((w, h), 0) + 1
    main_w, main_h = max(counts, key=counts.get) if counts else combos[0]

    rules = []
    rules.append(f"@page {{ size: {widths[main_w]:.3f}pt {heights[main_h]:.3f}pt; margin: 0; }}")
    # Named pages only apply to boxes in normal flow: pdf2htmlEX's absolutely
    # positioned page container silently disabled them (mixed portrait/landscape
    # documents were printed at a single size, overflowing onto extra pages).
    rules.append("@media print { #page-container { position: static !important; } }")
    # pdf2htmlEX's loading indicator and our tooltip sit after the last page:
    # printed, they produced an extra (almost) blank page.
    rules.append("@media print { .loading-indicator, #rt-bilingual-tooltip { display: none !important; } }")
    for w, h in combos:
        name = f"rt-{w}-{h}"
        rules.append(f"@page {name} {{ size: {widths[w]:.3f}pt {heights[h]:.3f}pt; margin: 0; }}")
        rules.append(f"@media print {{ .pf.{w}.{h} {{ page: {name}; }} }}")
    rules.append("body { margin: 0; padding: 0; }")
    return "<style>\n" + "\n".join(rules) + "\n</style>"


def apply_translations_offline(
    input_html_path: str,
    output_html_path: str,
    translations: Dict[str, str],
    page_size_css: Optional[str] = None,
) -> None:
    """Injects the translations into the instrumented HTML for headless printing.

    The translations are applied on 'load' through the same applyTranslation()
    used live in the GUI (same geometry fitting), then overlays/shimmers are
    removed. Page sizes come from the document itself (see build_page_size_css).

    Args:
        input_html_path: Instrumented workspace HTML.
        output_html_path: Where the printable HTML is written.
        translations: Segment id -> translated text.
        page_size_css: Optional explicit CSS size for every page (e.g. 'A4').
    """
    with open(input_html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # "</" must not appear raw inside a <script> block
    translations_json = json.dumps(translations, ensure_ascii=False).replace("</", "<\\/")

    if page_size_css:
        page_size_style = (f"<style>@page {{ size: {page_size_css}; margin: 0; }} "
                           f"body {{ margin: 0; padding: 0; }}</style>")
    else:
        page_size_style = build_page_size_css(html_content)

    # Translations are applied page by page, yielding to the browser between
    # pages, and the progress is published in window.__rtExportProgress so the
    # DevTools client (cdp.print_to_pdf) can report "pages prepared: 12/37".
    # window.__rtExportReady turns true once fonts are loaded and paragraphs
    # laid out again with their real metrics: the page is then printable.
    automated_hook_script = """
    <script>
    var cliTranslations = __RT_TRANSLATIONS__;
    window.__rtExportProgress = { stage: 'loading', done: 0, total: 0 };
    window.__rtExportReady = false;
    window.addEventListener('load', function () {
        document.querySelectorAll('[id^="glass-overlay-t-"]').forEach(function (glass) {
            glass.style.display = 'none';
        });
        // Segment ids of each page, in page order (paragraph ids once each)
        var pages = Array.prototype.slice.call(document.querySelectorAll('.pf'));
        var perPage = pages.map(function (page) {
            var ids = [], seen = {};
            page.querySelectorAll('[data-trans-id]').forEach(function (span) {
                var id = span.getAttribute('data-para') || span.getAttribute('data-trans-id');
                if (!seen[id] && Object.prototype.hasOwnProperty.call(cliTranslations, id)) {
                    seen[id] = true;
                    ids.push(id);
                }
            });
            return ids;
        });
        var progress = window.__rtExportProgress;
        progress.stage = 'pages';
        progress.total = pages.length;

        function finish() {
            document.querySelectorAll('.shimmer-line').forEach(function (el) {
                el.classList.remove('shimmer-line');
            });
            if (window.harmonizeAllPages) window.harmonizeAllPages();
            var tip = document.getElementById('rt-bilingual-tooltip');
            if (tip) tip.remove();
            progress.stage = 'fonts';
            // Load every embedded face, then lay paragraphs out again with real metrics
            var fontsReady = document.fonts ? (function () {
                document.fonts.forEach(function (f) { try { f.load(); } catch (e) {} });
                return document.fonts.ready;
            })() : Promise.resolve();
            fontsReady.then(function () {
                var paras = window.__rtParas || {};
                Object.keys(paras).forEach(function (pid) { window.reflowParagraph(pid, paras[pid]); });
                if (window.harmonizeAllPages) window.harmonizeAllPages();
                progress.stage = 'ready';
                window.__rtExportReady = true;
            });
        }

        var k = 0;
        (function nextPage() {
            if (k >= perPage.length) { finish(); return; }
            perPage[k].forEach(function (id) {
                if (window.applyTranslation) window.applyTranslation(id, cliTranslations[id]);
            });
            k += 1;
            progress.done = k;
            setTimeout(nextPage, 0);   // let the browser breathe (and the client poll)
        })();
    });
    </script>
    """.replace("__RT_TRANSLATIONS__", translations_json)

    optimized_html = html_content.replace("</head>", f"{page_size_style}\n</head>", 1)
    idx = optimized_html.rfind("</body>")
    if idx != -1:
        optimized_html = optimized_html[:idx] + automated_hook_script + "\n" + optimized_html[idx:]
    else:
        optimized_html += automated_hook_script

    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(optimized_html)


def resolve_pdf_renderer() -> Optional[str]:
    """
    Resolves the headless PDF renderer.

    1. Explicit override (ROCKTRANSLATE_BROWSER / settings).
    2. A previously downloaded chrome-headless-shell (pinned version: the most
       reproducible output, independent of the user's browser updates).
    3. An installed Chrome / Edge / Chromium / Brave.
    4. Automatic download of chrome-headless-shell into the user runtime dir.
    """
    from .downloader import check_and_download_headless_shell, find_downloaded_headless_shell

    override = os.environ.get("ROCKTRANSLATE_BROWSER")
    if override and os.path.isfile(override):
        return override

    cached = find_downloaded_headless_shell()
    if cached:
        return cached

    system_browser = find_system_chromium_browser()
    if system_browser:
        return system_browser

    try:
        return check_and_download_headless_shell()
    except Exception:
        return None


PRINT_TIMEOUT_SECONDS = 300


def print_html_to_vector_pdf(browser_path: str, input_html_path: str, output_pdf_path: str,
                             timeout: float = PRINT_TIMEOUT_SECONDS) -> bool:
    """Prints an HTML file to a vector PDF with a headless Chromium.

    Robustness: isolated temporary profile (no clash with the user's open
    browser), --no-sandbox when running as root (Docker/CI), hard timeout, and
    a check that the PDF was really written.

    Returns:
        True if the PDF was generated successfully, False otherwise.
    """
    import tempfile
    from loguru import logger

    if not os.path.exists(input_html_path):
        return False

    output_abs = os.path.abspath(output_pdf_path)
    out_dir = os.path.dirname(output_abs)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(output_abs):
        try:
            os.remove(output_abs)
        except OSError:
            pass

    is_shell = "headless-shell" in os.path.basename(browser_path).lower()
    with tempfile.TemporaryDirectory(prefix="rocktranslate-chrome-") as profile_dir:
        cmd = [
            browser_path,
            "--headless" if is_shell else "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--user-data-dir={profile_dir}",
            "--no-margins",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            # Let deferred work finish (font loading, paragraph re-layout) before printing
            "--virtual-time-budget=15000",
            f"--print-to-pdf={output_abs}",
        ]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.append("--no-sandbox")
        cmd.append(Path(os.path.abspath(input_html_path)).as_uri())

        from .proc import run_with_timeout
        try:
            code, _out, err = run_with_timeout(cmd, timeout)
        except OSError as e:
            logger.error(f"Could not start the headless browser '{browser_path}': {e}")
            return False
        if code is None:
            logger.error(f"Headless browser timed out after {timeout:.0f}s while printing.")
            return False

    ok = os.path.exists(output_abs) and os.path.getsize(output_abs) > 0
    if not ok:
        tail = (err or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
        logger.error(f"Headless printing failed (exit {code}): {' | '.join(tail)}")
    return ok


def _devtools_browsers() -> list:
    """Installed Edge / Chrome / Chromium usable through the DevTools protocol (Edge first)."""
    override = os.environ.get("ROCKTRANSLATE_BROWSER")
    paths = [override] if override and os.path.isfile(override) else []
    paths += [p for p in _candidate_browser_paths() if p and os.path.isfile(p)]
    system = find_system_chromium_browser()
    if system:
        paths.append(system)
    seen, ordered = set(), []
    for p in sorted(paths, key=lambda p: 0 if "edge" in p.lower() else 1):
        if p not in seen and "headless-shell" not in os.path.basename(p).lower():
            seen.add(p)
            ordered.append(p)
    return ordered


def print_html_with_fallback(input_html_path: str, output_pdf_path: str,
                             browser_path: Optional[str] = None,
                             timeout: Optional[float] = None,
                             progress: Optional[Callable[[str, int, int], None]] = None) -> bool:
    """
    Prints to a vector PDF, most reliable route first:

    1. The installed Edge / Chrome driven through the DevTools protocol
       (Page.printToPDF). Desktop browsers stall in the --print-to-pdf
       command-line mode, never through DevTools.
    2. chrome-headless-shell in command-line mode (downloaded if needed).

    progress(stage, done, total), when given, follows route 1: 'pages' while
    the translations are applied page by page, 'fonts', then 'print'.
    """
    from loguru import logger
    from .cdp import print_to_pdf
    from .downloader import check_and_download_headless_shell, find_downloaded_headless_shell

    if timeout is None:
        # Page count drives the cost (backgrounds are separate files now, so
        # the HTML size no longer reflects the work): ~6 s per page, capped.
        try:
            with open(input_html_path, encoding="utf-8", errors="ignore") as f:
                pages = f.read().count('class="pf ')
        except OSError:
            pages = 20
        timeout = min(900.0, 90.0 + 6.0 * max(pages, 1))

    output_abs = os.path.abspath(output_pdf_path)
    if os.path.dirname(output_abs):
        os.makedirs(os.path.dirname(output_abs), exist_ok=True)

    candidates = ([browser_path] if browser_path and "headless-shell" not in os.path.basename(browser_path).lower()
                  else []) + _devtools_browsers()
    import time as _time
    for browser in dict.fromkeys(candidates):
        started = _time.monotonic()
        if print_to_pdf(browser, input_html_path, output_abs, timeout, progress=progress):
            logger.info(f"PDF printed with {os.path.basename(browser)} (DevTools) in "
                        f"{_time.monotonic() - started:.0f}s.")
            return True
        if _time.monotonic() - started > 0.8 * timeout:
            # It worked but ran out of time: another engine would be as slow
            logger.warning(f"Printing timed out with {browser}.")
            return False
        logger.warning(f"Printing through DevTools failed with {browser}; trying the next engine.")

    shell = find_downloaded_headless_shell() or check_and_download_headless_shell()
    if not shell:
        return False
    return print_html_to_vector_pdf(shell, input_html_path, output_abs, timeout=timeout)
