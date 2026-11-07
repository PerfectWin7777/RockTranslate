"""
RockTranslate — High-Fidelity Geometry-Based HTML Parser and Transformer
Path: src/rocktranslate/core/html_transformer.py

This module executes high-fidelity semantic reconstruction of PDF layouts:
1. Converts PDF documents to raw HTML utilizing local pdf2htmlEX engines.
2. Parses unscaled CSS transform matrices and dynamic spacer properties.
3. Applies a scaled hybrid grouping algorithm to prevent word fragmentation:
   - Identifies structural table breaks (scaled spaces >= THRESHOLD_PX).
   - Identifies real word spaces (2.5px <= scaled spaces < THRESHOLD_PX).
   - Identifies kerning/accent positioning (scaled spaces < 2.5px or negative),
     merging diacritics (like Moïse, Sébastien) cleanly without injecting gaps.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os, sys
import queue
import re
import subprocess
import threading
import time
import unicodedata
from collections import deque
from typing import Callable, Optional, Dict, Tuple, List, Set, Any
from bs4 import BeautifulSoup, NavigableString
from loguru import logger

from .config_manager import config_db
from .chunker import should_translate
# Safe imports supporting both standard package modules and direct scripts
from .constants import DEFAULT_ASSETS_DIR, ACCENTS_TO_IGNORE, THRESHOLD_PX
from .downloader import check_and_download_pdf2htmlex, pdf2htmlex_data_dir
from .proc import NO_WINDOW, kill_tree, process_cpu_seconds

# Seconds without any stderr output before the conversion is considered hung.
# A total time limit would kill legitimate long conversions of large documents,
# so only inactivity is punished: a healthy conversion always emits progress.
STALL_TIMEOUT_SECONDS = 30.0
# Before its FIRST output line pdf2htmlEX may legitimately stay silent for a
# long time (Windows: font cache build on a cold start).
STARTUP_GRACE_SECONDS = 120.0
# Bumped when the raw conversion options change (cached raw HTML is redone)
RAW_LAYOUT_VERSION = 3
# Liveness while pdf2htmlEX is silent: CPU time is sampled every few seconds;
# a busy process is given more time, up to a hard cap of silence.
CPU_CHECK_SECONDS = 5.0
MAX_BUSY_SILENCE_SECONDS = 900.0

# Last pdf2htmlEX failure reason (stderr tail), surfaced to the UI/CLI.
LAST_CONVERSION_ERROR: Dict[str, str] = {"message": ""}

def _remove_quietly(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def convert_pdf_to_html(
    pdf_path: str,
    assets_dir: str = DEFAULT_ASSETS_DIR,
    on_progress: Optional[Callable[[int, int], None]] = None,
    stall_timeout: float = STALL_TIMEOUT_SECONDS,
    startup_grace: float = STARTUP_GRACE_SECONDS,
    timeout: Optional[float] = None,
    output_dir: Optional[str] = None,
    check_cancelled: Optional[Callable[[], bool]] = None,
    env: Optional[Dict[str, str]] = None,
    first_page: Optional[int] = None,
    last_page: Optional[int] = None,
    user_password: Optional[str] = None,
) -> Optional[str]:
    """
    Converts a source PDF into raw HTML using the local pdf2htmlEX executable.
    Streams execution output in real-time to report compilation progress per page.

    Robustness is enforced through an inactivity watchdog rather than a total
    timeout: if pdf2htmlEX stops emitting output for `stall_timeout` seconds
    (infinite loop on complex LaTeX/arXiv mathematical fonts), the process is
    killed and None is returned. An optional global `timeout` can still cap the
    whole conversion for callers that need a hard budget.

    Args:
        pdf_path: The filesystem path to the target PDF file.
        assets_dir: Assets folder storing the external pdf2htmlEX compiler.
        on_progress: Optional callback progress tracker (current_page, total_pages).
        stall_timeout: Max seconds of silence from pdf2htmlEX before it is killed.
        startup_grace: Max silence allowed before the FIRST output line (cold start).
        timeout: Optional hard cap in seconds for the entire conversion.
        output_dir: Optional directory where the raw HTML (and its assets) are
            written. Defaults to the PDF's own directory.
        check_cancelled: Optional polling callback; when it returns True the
            conversion is aborted and the process killed immediately.
        user_password: Password of PDFs that require one to be opened.

    Copy/print permission flags ("DRM") are ignored (--no-drm 1): the user can
    already read the document, and pdf2htmlEX would otherwise refuse to convert
    perfectly readable publisher PDFs.

    Returns:
        Optional[str]: Absolute path to the generated raw HTML, or None if failed.
    """
    pdf2htmlex_exe = check_and_download_pdf2htmlex(assets_dir)
    if not pdf2htmlex_exe:
        logger.error("pdf2htmlEX executable could not be resolved.")
        return None

    pdf_dir: str = os.path.dirname(os.path.abspath(pdf_path))
    pdf_filename: str = os.path.basename(pdf_path)
    html_filename: str = f"{os.path.splitext(pdf_filename)[0]}_raw.html"

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        output_dir_abs: str = os.path.abspath(output_dir)
        output_html_path = os.path.join(output_dir_abs, html_filename)
        cmd_pdf_ref: str = os.path.abspath(pdf_path)
        # Legacy pdf2htmlEX Windows builds prefix the output with "./" and cannot
        # open absolute output paths: the output name must stay relative to cwd.
        cmd_output_ref: str = html_filename
    else:
        output_html_path = os.path.join(pdf_dir, html_filename)
        cmd_pdf_ref = pdf_filename
        cmd_output_ref = html_filename

    # Page images are written as separate files next to the HTML (only inside a
    # dedicated output folder): base64-embedded images made the HTML up to ~95%
    # images, i.e. hundreds of MB for image-heavy papers, which every later step
    # (parsing, geometry, the GUI pane, printing) had to load again.
    external_images = bool(output_dir)
    layout_marker = os.path.join(os.path.dirname(output_html_path),
                                 f".{os.path.splitext(html_filename)[0]}.layout-v{RAW_LAYOUT_VERSION}")

    # Bypass compilation ONLY if raw HTML is already generated, not empty, and
    # was produced with the current conversion options.
    if (os.path.exists(output_html_path) and os.path.getsize(output_html_path) > 0
            and (not external_images or os.path.exists(layout_marker))):
        logger.info(f"Raw HTML already exists and is valid. Skipping compilation for: {pdf_filename}")
        return output_html_path

    # pdf2htmlEX writes to a temporary name that is atomically renamed on
    # success, so a killed/cancelled run never leaves a truncated HTML behind
    # that the "already converted" fast path above would reuse.
    partial_filename = f"{os.path.splitext(html_filename)[0]}.partial.html"
    partial_html_path = os.path.join(os.path.dirname(output_html_path), partial_filename)
    cmd_output_ref = partial_filename
    if os.path.exists(partial_html_path):
        try:
            os.remove(partial_html_path)
        except OSError:
            pass

    cmd: List[str] = [os.path.abspath(pdf2htmlex_exe), "--zoom", "1.3", "--no-drm", "1"]
    if external_images:
        cmd += ["--embed-image", "0"]
    if sys.platform == "win32":
        # Windows build: the Splash raster background renderer (png/jpg) crashes
        # on some machines; the Cairo SVG renderer is stable and vector-sharp.
        cmd += ["--bg-format", "svg"]
    if user_password:
        cmd += ["--user-password", user_password]
    data_dir = pdf2htmlex_data_dir(pdf2htmlex_exe)
    if data_dir:
        cmd += ["--data-dir", data_dir]
    # Page-range conversion on the ORIGINAL file: parallel workers convert
    # disjoint ranges without any PDF extraction step (extracting pages with
    # pypdf produces resource-truncated PDFs this legacy binary crashes on).
    if first_page is not None:
        cmd += ["-f", str(int(first_page))]
    if last_page is not None:
        cmd += ["-l", str(int(last_page))]
    # Options first, positional arguments last
    cmd += [cmd_pdf_ref, cmd_output_ref]

    LAST_CONVERSION_ERROR["message"] = ""
    logger.info(f"Starting high-fidelity conversion of PDF: {pdf_filename}")

    # ── WINDOWS CRASH PROTECTION ──
    if sys.platform == "win32":
        import ctypes
        # Disable Windows GPF error dialog popups ("Application has stopped working").
        # This ensures that if the process crashes, it terminates immediately
        # instead of hanging in memory waiting for a user click.
        ctypes.windll.kernel32.SetErrorMode(0x0002)

    process = subprocess.Popen(
        cmd,
        cwd=output_dir or pdf_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,                  # Line buffered output
        universal_newlines=True,    # Translates carriage returns (\r) to newlines (\n)
        env=env,                    # Parallel workers pass an isolated TEMP/TMP here
        **NO_WINDOW,                # no console window popping up from the GUI (Windows)
    )

    # ── NON-BLOCKING PIPE READER ──
    # stderr is consumed on a dedicated thread and forwarded through a queue so
    # the main loop can wait with a timeout (select() is unreliable on Windows
    # pipes) instead of blocking forever on readline().
    stderr_queue: "queue.Queue[Optional[str]]" = queue.Queue()

    def _read_stderr() -> None:
        try:
            for line in process.stderr:  # type: ignore[union-attr]
                stderr_queue.put(line)
        finally:
            stderr_queue.put(None)  # EOF sentinel

    threading.Thread(target=_read_stderr, name="pdf2htmlex-stderr", daemon=True).start()

    deadline: Optional[float] = (time.monotonic() + timeout) if timeout else None
    last_progress: Tuple[int, int] = (0, 0)
    stderr_tail: "deque" = deque(maxlen=40)

    seen_output = False
    while True:
        wait_budget = stall_timeout if seen_output else max(stall_timeout, startup_grace)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error(f"pdf2htmlEX conversion exceeded the {timeout}s total budget on: {pdf_filename}")
                kill_tree(process)
                return None
            wait_budget = min(wait_budget, remaining)

        # Poll in short slices so cancellation stays responsive while the queue
        # is idle; silence across the whole budget still means the process hung.
        line: Optional[str] = None
        stalled = True
        silence_start = time.monotonic()
        stall_deadline = silence_start + wait_budget
        cpu_seen = process_cpu_seconds(process.pid)
        next_cpu_check = silence_start + CPU_CHECK_SECONDS
        while time.monotonic() < stall_deadline:
            # Silent but still burning CPU = working (a huge page image can take
            # minutes to encode without a progress line), not hung.
            now = time.monotonic()
            if now >= next_cpu_check:
                next_cpu_check = now + CPU_CHECK_SECONDS
                cpu_now = process_cpu_seconds(process.pid)
                if cpu_now is not None and cpu_seen is not None and cpu_now - cpu_seen >= 0.5:
                    if now - silence_start < MAX_BUSY_SILENCE_SECONDS:
                        stall_deadline = max(stall_deadline, now + stall_timeout)
                cpu_seen = cpu_now if cpu_now is not None else cpu_seen
            if check_cancelled is not None and check_cancelled():
                logger.info("pdf2htmlEX conversion cancelled by caller. Terminating the process.")
                kill_tree(process)
                _remove_quietly(partial_html_path)
                return None
            try:
                line = stderr_queue.get(timeout=1.0)
                stalled = False
                seen_output = True
                break
            except queue.Empty:
                continue

        if stalled:
            wait_budget = time.monotonic() - silence_start
            logger.error(
                f"pdf2htmlEX stalled for {wait_budget:.0f}s without output on: {pdf_filename}. "
                "Terminating the hung process."
            )
            kill_tree(process)
            _remove_quietly(partial_html_path)
            LAST_CONVERSION_ERROR["message"] = f"pdf2htmlEX stalled for {wait_budget:.0f}s (no progress, no CPU activity)"
            # TODO: If local compilation fails or times out, implement an automatic fallback
            # to a remote serverless cloud-rendering API to convert complex LaTeX documents.
            return None

        if line is None:
            break  # EOF: process stderr stream terminated

        stderr_tail.append(line.rstrip())
        # Parse progress metrics (Format: "Working: 12/30")
        match = re.search(r"Working:\s*(\d+)/(\d+)", line)
        if match:
            last_progress = (int(match.group(1)), int(match.group(2)))
            if on_progress:
                on_progress(last_progress[0], last_progress[1])

    process.wait()

    if last_progress != (0, 0) and on_progress:
        on_progress(last_progress[0], last_progress[1])

    if process.returncode == 0 and os.path.exists(partial_html_path) and os.path.getsize(partial_html_path) > 0:
        os.replace(partial_html_path, output_html_path)
        if external_images:
            try:
                with open(layout_marker, "w", encoding="utf-8") as f:
                    f.write("external page images\n")
            except OSError:
                pass
        logger.info("Raw HTML file generated successfully.")
        return output_html_path

    try:
        if os.path.exists(partial_html_path):
            os.remove(partial_html_path)
    except OSError:
        pass

    logger.error(f"pdf2htmlEX exited with error code: {process.returncode}")
    for tail_line in list(stderr_tail)[-5:]:
        logger.error(f"pdf2htmlEX stderr | {tail_line}")
    LAST_CONVERSION_ERROR["message"] = " | ".join(
        l for l in list(stderr_tail)[-3:] if l and not l.startswith(("Working", "Preprocessing"))
    )[:400]

    # TODO: In the main UI window, handle the None return value by displaying a clear
    # and friendly error message explaining that this PDF contains unsupported fonts.
    return None




def parse_matrix_classes(soup: BeautifulSoup) -> Dict[str, Tuple[float, float]]:
    """
    Parses unscaled CSS transform matrix properties from style tags.
    Robust pattern tolerating spaces, negative signs, and multiple rules.
    (e.g., .m0 { transform: matrix(0.125, 0, 0, 0.125, 0, 0); } -> {'m0': (0.125, 0.125)})
    
    Args:
        soup: BeautifulSoup object parsed from raw HTML.

    Returns:
        Dict[str, Tuple[float, float]]: Mapping of matrix classes to (scaleX, scaleY) factors.
    """
    matrix_map: Dict[str, Tuple[float, float]] = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.string or ""
        # Improved pattern capturing scaleX and scaleY with sign and spacing tolerance
        for m in re.finditer(r'\.(m\w+)\s*\{[^}]*transform\s*:\s*matrix\s*\(\s*(-?[\d\.]+)\s*,\s*-?[\d\.]+\s*,\s*-?[\d\.]+\s*,\s*(-?[\d\.]+)\s*,', text):
            cls: str = m.group(1)
            sx: float = float(m.group(2))
            sy: float = float(m.group(3))
            matrix_map[cls] = (sx, sy)
    return matrix_map


def parse_spacer_widths(soup: BeautifulSoup) -> Dict[str, float]:
    """
    Parse horizontal spacer widths from CSS style tags inside the HTML document.

    This function dynamically scans all <style> tags to extract horizontal offset
    properties (such as margin-left, margin-right, left, right, and width)
    generated by pdf2htmlEX. It converts different CSS units (pt, em, rem) 
    into standard virtual pixels (px) to prevent layout breakages.

    Args:
        soup (BeautifulSoup): The parsed BeautifulSoup object of the HTML page.

    Returns:
        Dict[str, float]: A mapping of spacer class names to their width in pixels.
    """
    spacer_map: Dict[str, float] = {}
    
    # Generic regex pattern matching horizontal spacing properties and their units
    pattern = re.compile(
        r'\._([a-fA-F0-9\w]+)\s*\{[^}]*?\b(margin-left|margin-right|left|right|width)\s*:\s*(-?[\d\.]+)\s*(px|pt|em|rem|%)'
    )

    for style_tag in soup.find_all("style"):
        text = style_tag.get_text()
        for match in pattern.finditer(text):
            class_name = match.group(1)
            raw_value = float(match.group(3))
            unit = match.group(4)
            
            # Normalize units to standard virtual pixels (px)
            if unit == "pt":
                pixel_value = raw_value * 1.333333
            elif unit in ("em", "rem"):
                pixel_value = raw_value * 16.0
            else:
                pixel_value = raw_value
                
            spacer_map[class_name] = pixel_value
            
    return spacer_map


def parse_color_classes(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Parse font color classes from CSS style tags inside the HTML document.

    This utility extracts color declarations mapped to class names starting 
    with '.fc' (e.g. .fc0 { color: #1a1a1a; }) and normalizes hex/rgb values 
    into standard hex codes (without the '#' symbol) for XML tagging.
    Features robust error handling to prevent pipeline failures.

    Args:
        soup (BeautifulSoup): The parsed BeautifulSoup object of the HTML page.

    Returns:
        Dict[str, str]: A mapping of CSS classes (like 'fc0') to their Hex codes.
    """
    color_map: Dict[str, str] = {}
    try:
        pattern = re.compile(
            r'\.(fc\w+)\s*\{[^}]*?color\s*:\s*([^;}]+)'
        )

        for style_tag in soup.find_all("style"):
            text = style_tag.get_text()
            for match in pattern.finditer(text):
                class_name = match.group(1)
                color_value = match.group(2).strip()
                
                hex_color = ""
                if color_value.startswith("#"):
                    hex_color = color_value.replace("#", "").strip()
                    if len(hex_color) == 3:
                        hex_color = "".join([c * 2 for c in hex_color])
                elif "rgb" in color_value:
                    rgb_nums = re.findall(r'\d+', color_value)
                    if len(rgb_nums) >= 3:
                        r, g, b = int(rgb_nums[0]), int(rgb_nums[1]), int(rgb_nums[2])
                        hex_color = f"{r:02x}{g:02x}{b:02x}"
                        
                if hex_color:
                    color_map[class_name] = hex_color
    except Exception:
        # Fail silently to guarantee core pipeline extraction never crashes
        pass
        
    return color_map


def parse_position_classes(soup: BeautifulSoup) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Parses unscaled CSS coordinates from style tags to understand visual layout.
    Extracts x classes (.x1 { left: 85px; }) and y classes (.y1 { bottom: 234px; })
    """
    x_map: Dict[str, float] = {}
    y_map: Dict[str, float] = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.get_text()
        for m in re.finditer(r'\.(x\w+)\s*\{\s*(?:left|margin-left)\s*:\s*([\d\.-]+)\s*px', text):
            x_map[m.group(1)] = float(m.group(2))
        for m in re.finditer(r'\.(y\w+)\s*\{\s*(?:bottom|top|margin-bottom|margin-top)\s*:\s*([\d\.-]+)\s*px', text):
            y_map[m.group(1)] = float(m.group(2))
    return x_map, y_map


# Glyphs that broken symbol fonts (no ToUnicode map) expose instead of math signs.
SYMBOL_GLYPH_FIXES = str.maketrans({"ð": "(", "Þ": ")", "¼": "=", "þ": "+"})

# Bump whenever instrument_html output changes: cached workspaces built by an
# older pipeline are then re-instrumented from the cached raw HTML.
PIPELINE_VERSION = 20


def parse_font_sizes(soup: BeautifulSoup) -> Dict[str, float]:
    """Screen font sizes of pdf2htmlEX fsN classes, in px (first definition wins)."""
    sizes: Dict[str, float] = {}
    for style_tag in soup.find_all("style"):
        for m in re.finditer(r"\.(fs[0-9a-f]+)\{font-size:([\d.]+)px;\}", style_tag.get_text()):
            sizes.setdefault(m.group(1), float(m.group(2)))
    return sizes


def detect_symbol_font_classes(soup: BeautifulSoup) -> Set[str]:
    """
    Detects pdf2htmlEX font classes (ffN) that use a broken symbol encoding.

    A font class is considered "symbolic" when it renders at least one of the
    suspicious glyphs (ð Þ ¼ þ) while containing almost no Latin letters: real
    prose fonts (e.g. Icelandic text) are dominated by letters and are left intact.
    """
    suspicious = set("ðÞ¼þ")
    stats: Dict[str, List[int]] = {}  # cls -> [suspicious, letters, total]
    for tag in soup.find_all(class_=re.compile(r"^ff\w+")):
        ff_classes = [c for c in tag.get("class", []) if c.startswith("ff")]
        if not ff_classes:
            continue
        own_text = "".join(str(t) for t in tag.find_all(string=True, recursive=False))
        if not own_text.strip():
            continue
        entry = stats.setdefault(ff_classes[0], [0, 0, 0])
        for ch in own_text:
            if ch.isspace():
                continue
            entry[2] += 1
            if ch in suspicious:
                entry[0] += 1
            elif ch.isalpha():
                entry[1] += 1
    return {
        cls for cls, (sus, letters, total) in stats.items()
        if sus > 0 and total > 0 and letters / total < 0.3
    }


_LIST_START_RE = re.compile(r"^\s*(?:[•●▪◦·∙‣\-–—]|\(?\d{1,2}[.)]|\(?[a-zA-Z][.)])\s")
# "[12] ..." starts a new entry only inside a reference list (a citation at
# the start of a prose line, e.g. "[36] to show ...", must not break the paragraph)
_REF_START_RE = re.compile(r"^\s*\[\d+\]\s")


def group_lines_into_paragraphs(lines: List[Dict[str, Any]], texts: Dict[str, str]) -> List[List[Dict[str, Any]]]:
    """Paragraph grouping: from MEASURED geometry when available, else estimates."""
    if lines and all(l.get("box") for l in lines):
        return _group_measured(lines, texts)
    return _group_estimated(lines, texts)


def _group_measured(lines: List[Dict[str, Any]], texts: Dict[str, str]) -> List[List[Dict[str, Any]]]:
    """
    Paragraph grouping from the exact rendered boxes of the lines. Only
    geometric facts are used, expressed in em of the text itself:

    - same visual line: boxes overlap vertically and the horizontal gap from
      the end of the text already on that line is at most 1 em (a table cell
      or another column is further away, so it is never absorbed);
    - next line of the same paragraph: same font size and vertical scale,
      regular baseline step, same left edge (first line may be indented);
    - a paragraph ends when a line stops clearly before the block's right
      edge, or at a list marker; a short first line is a heading.
    """
    for l in lines:
        left, right, top, bottom = l["box"]
        l.update({"x": left, "right": right, "end": right, "top": top, "bottom": bottom, "y": -bottom})

    def eligible(line: Dict[str, Any]) -> bool:
        return (len(line["spans"]) == 1 and line["em"] > 0
                and bool(texts.get(line["spans"][0][0], "").strip()))

    def has_text(line: Dict[str, Any]) -> bool:
        return line["em"] > 0 and any(texts.get(g, "").strip() for g, _ in line["spans"])

    closed: List[Dict[str, Any]] = []
    active: List[Dict[str, Any]] = []
    recent: List[Dict[str, Any]] = []      # recent slot lines (absorption hosts)

    def same_column(block: Dict[str, Any], line: Dict[str, Any]) -> bool:
        ref = block["lines"][-1]
        horizontal_overlap = min(ref["end"], line["right"]) - max(ref["x"], line["x"])
        return horizontal_overlap > 0

    def close(block: Dict[str, Any]) -> None:
        active.remove(block)
        closed.append(block)

    def continues(block: Dict[str, Any], line: Dict[str, Any]) -> bool:
        prev = block["lines"][-1]
        em = line["em"]
        dy = line["bottom"] - prev["bottom"]
        if not (line["fs"] == prev["fs"] and _same_scale(line, prev) and abs(line["em"] - prev["em"]) < 0.05 * em):
            return False
        if not (0.9 * em <= dy <= 1.9 * em and (block["step"] is None or abs(dy - block["step"]) <= 0.2 * em)):
            return False
        if block["left"] is None:
            if not (-0.6 * em <= prev["x"] - line["x"] <= 4.0 * em):
                return False
        elif abs(line["x"] - block["left"]) > 0.6 * em:
            return False
        text = texts.get(line["spans"][0][0], "")
        first_text = texts.get(block["lines"][0]["spans"][0][0], "")
        if _LIST_START_RE.match(text) or (_REF_START_RE.match(text) and _REF_START_RE.match(first_text)):
            return False
        if len(block["lines"]) == 1:
            prev_text = texts.get(prev["spans"][0][0], "").strip()
            if re.fullmatch(r"<color_[0-9a-fA-F]{6}>.*</color_[0-9a-fA-F]{6}>", prev_text) and not re.match(r"<color_", text.strip()):
                return False
            # A first line ending clearly before the next one is a heading
            if abs(prev["x"] - line["x"]) <= 0.3 * em and prev["end"] < line["end"] - 3.0 * em:
                return False
        else:
            # The previous line stopped before the block's right edge: paragraph end
            block_right = max(l["end"] for l in block["lines"][:-1])
            if prev["end"] < block_right - 2.0 * em:
                return False
        return True

    for line in lines:
        if not has_text(line):
            continue
        host = None
        for cand in reversed(recent[-6:]):
            overlap = min(cand["bottom"], line["bottom"]) - max(cand["top"], line["top"])
            gap = line["x"] - cand["end"]
            if (overlap >= 0.4 * min(cand["bottom"] - cand["top"], line["bottom"] - line["top"])
                    and -1.0 * cand["em"] <= gap <= 1.0 * cand["em"]
                    and line["em"] <= cand["em"] * 1.05):
                host = cand
                break
        if host is not None:
            smaller = line["em"] < 0.85 * host["em"]
            line["sup"] = smaller and line["bottom"] <= host["bottom"] - 0.1 * host["em"]
            line["sub"] = smaller and not line["sup"] and line["top"] >= host["top"] + 0.25 * host["em"]
            host.setdefault("pieces", []).append(line)
            host["end"] = max(host["end"], line["right"])
            continue

        # Formula fragments (fractions, symbol runs) that are not inline pieces
        # keep their original rendering: never a paragraph line.
        if not should_translate("".join(texts.get(g, "") for g, _ in line["spans"])):
            continue

        if not eligible(line):
            for block in [b for b in active if same_column(b, line)]:
                close(block)
            continue

        target = next((b for b in reversed(active) if continues(b, line)), None)
        if target is not None:
            prev = target["lines"][-1]
            if target["step"] is None:
                target["step"] = line["bottom"] - prev["bottom"]
            if target["left"] is None:
                target["left"] = line["x"]
            target["lines"].append(line)
        else:
            for block in [b for b in active if same_column(b, line)]:
                close(block)
            active.append({"lines": [line], "step": None, "left": None})
        recent.append(line)

    closed.extend(active)
    paragraphs = [b["lines"] for b in closed if len(b["lines"]) >= 2]
    paragraphs.sort(key=lambda para: lines.index(para[0]))
    prose = []
    for para in paragraphs:
        lens = sorted(_visual_len(l, texts) for l in para)
        if lens[len(lens) // 2] >= 30:
            prose.append(para)
    return prose


def _group_estimated(lines: List[Dict[str, Any]], texts: Dict[str, str]) -> List[List[Dict[str, Any]]]:
    """
    Groups single-segment lines of a page into paragraphs, from geometry only:

    - same font size and vertical scale (justified lines may each have their
      own horizontal stretch matrix),
    - regular baseline step between 0.9 and 1.9 em, consistent inside a block,
    - common left edge (the first line may be indented, up to 4 em),
    - a new paragraph starts at list markers or after a clearly short line.

    Several paragraphs stay open at once (one per column), so documents whose
    lines pdf2htmlEX emits row by row across columns are handled too. Pieces on
    the same baseline right after a line (footnote markers, text after an
    inline formula) are absorbed into it. Returns prose blocks of 2+ lines.
    """
    # Only starts of long prose lines define columns (table cells are short).
    xs = [l["x"] for l in lines if l.get("x") is not None
          and len(re.sub(r"</?[a-z_0-9]+>", "", "".join(texts.get(g, "") for g, _ in l["spans"]))) >= 30]
    column_edges = sorted({round(x, 1) for x in xs if sum(1 for o in xs if abs(o - x) <= 1.5) >= 4})

    # Table columns: cell starts aligned to the pixel on 3+ lines of the page
    all_xs = [l["x"] for l in lines if l.get("x") is not None and not _ACCENT_ONLY_RE.match(
        re.sub(r"</?[a-z_0-9]+>", "", "".join(texts.get(g, "") for g, _ in l["spans"])))]
    aligned_edges = sorted({round(x, 1) for x in all_xs if sum(1 for o in all_xs if abs(o - x) <= 1.0) >= 3})

    def on_other_column_edge(line: Dict[str, Any], prev: Dict[str, Any]) -> bool:
        tol = 0.5 * max(line["em"], 1.0)
        if any(abs(line["x"] - e) <= tol and abs(prev["x"] - e) > tol for e in column_edges):
            return True
        return any(abs(line["x"] - e) <= 1.0 and abs(prev["x"] - e) > 1.0 for e in aligned_edges)

    def eligible(line: Dict[str, Any]) -> bool:
        return (len(line["spans"]) == 1 and line["x"] is not None and line["y"] is not None
                and line["em"] > 0 and bool(texts.get(line["spans"][0][0], "").strip()))

    closed: List[Dict[str, Any]] = []
    active: List[Dict[str, Any]] = []      # {"lines", "step", "left"}
    last_slot: Optional[Dict[str, Any]] = None

    def close(block: Dict[str, Any]) -> None:
        active.remove(block)
        closed.append(block)

    def same_column(block: Dict[str, Any], line: Dict[str, Any]) -> bool:
        ref = block["left"] if block["left"] is not None else block["lines"][0]["x"]
        return -4.0 * line["em"] <= line["x"] - ref <= 4.0 * line["em"]

    def continues(block: Dict[str, Any], line: Dict[str, Any]) -> bool:
        prev = block["lines"][-1]
        em = line["em"]
        dy = prev["y"] - line["y"]
        if not (line["fs"] == prev["fs"] and _same_scale(line, prev) and abs(line["em"] - prev["em"]) < 0.05 * em):
            return False
        if not (0.9 * em <= dy <= 1.9 * em and (block["step"] is None or abs(dy - block["step"]) <= 0.2 * em)):
            return False
        if block["left"] is None:
            if not (-0.6 * em <= prev["x"] - line["x"] <= 4.0 * em):
                return False
        elif abs(line["x"] - block["left"]) > 0.6 * em:
            return False
        text = texts.get(line["spans"][0][0], "")
        first_text = texts.get(block["lines"][0]["spans"][0][0], "")
        # Headings glued to the paragraph below: a fully colored line, or a
        # short, non-indented first line (a real first line is full width).
        if len(block["lines"]) == 1:
            prev_text = texts.get(prev["spans"][0][0], "").strip()
            if re.fullmatch(r"<color_[0-9a-fA-F]{6}>.*</color_[0-9a-fA-F]{6}>", prev_text) and not re.match(r"<color_", text.strip()):
                return False
            if (abs(prev["x"] - line["x"]) <= 0.3 * em
                    and _visual_len(prev, texts) < 0.7 * _visual_len(line, texts)
                    and not re.search(r"[,;:]$", re.sub(r"</?[a-z_0-9]+>", "", prev_text))):
                return False
        if _LIST_START_RE.match(text) or (_REF_START_RE.match(text) and _REF_START_RE.match(first_text)):
            return False
        lengths = [_visual_len(l, texts) for l in block["lines"]]
        if len(lengths) >= 2:
            earlier = sorted(lengths[:-1])
            if lengths[-1] < 0.6 * earlier[len(earlier) // 2]:
                return False
        return True

    for line in lines:
        has_text = line.get("x") is not None and line.get("y") is not None and line.get("em", 0) > 0 and any(
            texts.get(g, "").strip() for g, _ in line["spans"])
        if not eligible(line) and not has_text:
            if line.get("x") is not None:
                for block in [b for b in active if same_column(b, line)]:
                    close(block)
            continue

        # A stacked accent drawn as its own glyph box (slightly above the
        # baseline) belongs to the current visual line: it must not end the
        # paragraph and split the word it sits on.
        accent_text = re.sub(r"</?[a-z_0-9]+>", "", "".join(texts.get(g, "") for g, _ in line["spans"]))
        if (last_slot is not None and _ACCENT_ONLY_RE.match(accent_text)
                and line.get("y") is not None and abs(last_slot["y"] - line["y"]) <= 1.2 * last_slot["em"]):
            last_slot.setdefault("pieces", []).append(line)
            continue

        # Same visual line as a recent slot (footnote marker, inline math, text
        # emitted after it): absorbed into that slot instead of breaking the block.
        candidates = ([last_slot] if last_slot is not None else []) + [
            l for blk in active for l in blk["lines"][-3:] if l is not last_slot]
        host = None
        for prev in candidates:
            est_end = prev["x"] + 0.6 * prev["em"] * _visual_len(prev, texts)
            if (abs(prev["y"] - line["y"]) <= 0.6 * prev["em"] and line["x"] > prev["x"]
                    and line["x"] <= est_end + 1.5 * prev["em"]
                    # a word fragment (e.g. "P" + stacked accent) continued by
                    # the rest of the word: its continuation, even if that x
                    # happens to match another column edge
                    and ((_visual_len(prev, texts) <= 4 and line["x"] <= est_end + 0.5 * prev["em"])
                         or not on_other_column_edge(line, prev))
                    # a column starts between the host and this piece: the piece
                    # is in the next column (e.g. its indented first line)
                    and not any(prev["x"] + 2.0 * prev["em"] < e <= line["x"] + 0.5 * prev["em"]
                                for e in column_edges)
                    and line["em"] <= prev["em"] * 1.05):
                host = prev
                break
        if host is not None:
            smaller = line["em"] < 0.85 * host["em"]
            line["sup"] = smaller and line["y"] >= host["y"] - 0.05 * host["em"]
            line["sub"] = smaller and not line["sup"]
            host.setdefault("pieces", []).append(line)
            continue

        if not eligible(line):
            for block in [b for b in active if same_column(b, line)]:
                close(block)
            last_slot = None
            continue

        target = next((b for b in reversed(active) if continues(b, line)), None)
        if target is not None:
            prev = target["lines"][-1]
            if target["step"] is None:
                target["step"] = prev["y"] - line["y"]
            if target["left"] is None:
                target["left"] = line["x"]
            target["lines"].append(line)
        else:
            for block in [b for b in active if same_column(b, line)]:
                close(block)
            active.append({"lines": [line], "step": None, "left": None})
        last_slot = line

    closed.extend(active)
    paragraphs = [b["lines"] for b in closed if len(b["lines"]) >= 2]
    paragraphs.sort(key=lambda para: lines.index(para[0]))

    # Blocks of short lines (author lists, addresses, labels) are not prose:
    # reflowing them would merge items that must stay on separate lines.
    prose = []
    for para in paragraphs:
        lens = sorted(_visual_len(l, texts) for l in para)
        if lens[len(lens) // 2] >= 30:
            prose.append(para)
    return prose


def _same_scale(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return abs(a.get("sy", 1.0) - b.get("sy", 1.0)) <= 0.02 * max(a.get("sy", 1.0), b.get("sy", 1.0))


def _visual_len(line: Dict[str, Any], texts: Dict[str, str]) -> int:
    """Characters on the visual line (slot + absorbed pieces), tags excluded."""
    raw = texts.get(line["spans"][0][0], "") + "".join(
        texts.get(g, "") for p in line.get("pieces", []) for g, _ in p["spans"])
    return len(re.sub(r"</?[a-z_0-9]+>", "", raw))


def merge_color_runs(text: str) -> str:
    """
    "<color_X>Saaty,</color_X> <color_X>1977;</color_X>" -> "<color_X>Saaty, 1977;</color_X>".
    Word-by-word color tags (link annotations) drown the model in markup: it
    then tends to stop translating halfway and copy the rest verbatim.
    """
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"</color_([0-9a-fA-F]{6})>(\s*)<color_\1>", r"\2", text)
    return text


# Spacing accents that some PDFs (TeX) draw as separate glyphs over a letter
_SPACING_ACCENTS = {"´": "\u0301", "`": "\u0300", "ˆ": "\u0302", "^": "\u0302", "˜": "\u0303",
                    "¨": "\u0308", "¸": "\u0327", "ˇ": "\u030c", "˘": "\u0306", "˙": "\u0307",
                    "˚": "\u030a", "˝": "\u030b", "¯": "\u0304"}
_ACCENT_CHARS = "".join(_SPACING_ACCENTS)
_ACCENT_ONLY_RE = re.compile(r"^\s*[" + re.escape(_ACCENT_CHARS) + r"]+\s*$")
_ACCENT_LETTER_RE = re.compile(r"\s?([" + re.escape(_ACCENT_CHARS) + r"])\s*([A-Za-z])")


def compose_stacked_accents(text: str) -> str:
    """"P ´ erez-Pe ˜ na" -> "Pérez-Peña": a stacked accent glyph is merged into
    the letter it sits on, so the translator sees the real word."""
    def repl(m: "re.Match") -> str:
        return unicodedata.normalize("NFC", m.group(2) + _SPACING_ACCENTS[m.group(1)])
    return _ACCENT_LETTER_RE.sub(repl, text)


def join_paragraph_lines(lines: List[str]) -> str:
    """Joins line texts, repairing end-of-line hyphenation ("trans-" + "lation")."""
    out = ""
    for raw in lines:
        text = raw.strip()
        if not out:
            out = text
        elif re.search(r"[A-Za-zÀ-ÿ]-$", out) and text[:1].islower():
            out = out[:-1] + text
        else:
            out = out + " " + text
    return out


def instrument_html(raw_html_path: str, output_html_path: str) -> Tuple[Dict[str, str], Dict[str, int]]:
    """
    Instruments the raw HTML layout by applying the high-fidelity scaled grouping algorithm.
    Groups words into sentences, segregates table columns, and embeds loading screens.

    Args:
        raw_html_path: Path to the raw compiled HTML file.
        output_html_path: Path where the instrumented HTML should be saved.

    Returns:
        Tuple[Dict[str, str], Dict[str, int]]:
            - original_texts_map: Map of unique translation IDs to unified text strings.
            - tid_to_page: Map of unique translation IDs to their zero-based page index.
    """
    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    matrix_map: Dict[str, Tuple[float, float]] = parse_matrix_classes(soup)
    spacer_map: Dict[str, float] = parse_spacer_widths(soup)
    color_map:  Dict[str, str] = parse_color_classes(soup)
    x_map, y_map = parse_position_classes(soup)

    # Exact rendered geometry of every line (None -> estimate-based fallback)
    from .geometry import measure_line_boxes
    measured_boxes = measure_line_boxes(raw_html_path)
    pages_list = soup.find_all("div", class_="pf")
    symbol_fonts: Set[str] = detect_symbol_font_classes(soup)
    font_size_map: Dict[str, float] = parse_font_sizes(soup)

    # Retrieve configuration directly from JSON storage, falling back to constant if undefined
    threshold_px = float(config_db.get("TranslationConfig", "threshold_px", THRESHOLD_PX))

    original_texts_map: Dict[str, str] = {}
    tid_to_page: Dict[str, int] = {}
    idx: List[int] = [0]
    para_idx: List[int] = [0]

    for page_idx, page_el in enumerate(pages_list):
        # 1. Collect all raw line containers on this page
        div_t_elements = page_el.find_all("div", class_="t")
        
        # 2. Extract real geometric positions for layout sorting
        # def get_div_sort_key(div_t_node: Any) -> Tuple[float, float]:
        #     classes = div_t_node.get("class", [])
        #     x_val = 0.0
        #     y_val = 0.0
        #     for cls in classes:
        #         if cls in x_map:
        #             x_val = x_map[cls]
        #         if cls in y_map:
        #             y_val = y_map[cls]
        #     # pdf2htmlEX uses 'bottom' for Y coordinates. Larger values are at the top.
        #     return -y_val, x_val

        # 3. Sort line containers visually from top-to-bottom and left-to-right
        # sorted_div_t = sorted(div_t_elements, key=get_div_sort_key)

        # 3. Preserve the native DOM reading order from pdf2htmlEX to support multi-column layouts
        sorted_div_t = div_t_elements
        page_lines: List[Dict[str, Any]] = []
        page_boxes = None
        if measured_boxes is not None and page_idx < len(measured_boxes) \
                and len(measured_boxes[page_idx]) == len(sorted_div_t):
            page_boxes = measured_boxes[page_idx]

        for line_idx, div_t in enumerate(sorted_div_t):
            # Determine line scaling factors (scaleX, scaleY)
            classes = div_t.get("class", [])
            line_spans: List[Tuple[str, Any]] = []
            sx_orig, sy_orig = 1.0, 1.0
            for cls in classes:
                if cls in matrix_map:
                    sx_orig, sy_orig = matrix_map[cls]
                    break

            children = list(div_t.contents)

            # Word-space threshold relative to the rendered font size: a fixed
            # 2.5px merged real word spaces of small fonts (footnotes, author
            # blocks) into kerning ("AshishVaswani"). Kerning stays < ~0.1em.
            line_fs_cls = next((c for c in classes if c.startswith("fs")), None)
            em_px = font_size_map.get(line_fs_cls, 0.0) * abs(sy_orig or 1.0) if line_fs_cls else 0.0
            word_space_px = min(2.5, max(0.8, 0.15 * em_px)) if em_px > 0 else 2.5
            
            # ── 4. RECURSIVE DOM FLATTENING (Surgically exposes nested spacers inside styled spans) ──
            flattened_children: List[Any] = []
            
            def flatten_element(element: Any, active_classes: List[str]) -> None:
                if isinstance(element, NavigableString):
                    if str(element).strip():
                        # Wrap raw text nodes in a cloned span with inherited classes (ff2, fc0, etc.)
                        new_span = soup.new_tag("span", attrs={"class": " ".join(active_classes)})
                        new_span.string = str(element)
                        flattened_children.append(new_span)
                    else:
                        flattened_children.append(element)
                elif element.name == "span" and element.get("class") and any(cls.startswith("_") for cls in element.get("class")):
                    # Spacers are kept flat without wrapping
                    flattened_children.append(element)
                elif element.name in ["span", "b", "i", "sup", "sub", "em", "strong"]:
                    current_classes = list(active_classes)
                    if element.get("class"):
                        own = element.get("class")
                        # The innermost style wins: a black span (fc0) inside a
                        # blue line (fc1) is black. Inherited classes of the same
                        # kind are dropped instead of accumulating.
                        own_kinds = {re.match(r"[a-z]+", c).group(0) for c in own if re.match(r"(fc|ff|fs|sc)\d", c)}
                        current_classes = [c for c in current_classes
                                           if not (re.match(r"(fc|ff|fs|sc)\d", c) and re.match(r"[a-z]+", c).group(0) in own_kinds)]
                        current_classes.extend(own)
                    for child_node in list(element.contents):
                        flatten_element(child_node, current_classes)
                else:
                    flattened_children.append(element)

            for child in children:
                # Bare text inherits the LINE's font/size/color explicitly: the
                # translation span placed around it may carry another font
                # (e.g. the line font is a math font whose 'ð' glyph draws '(').
                flatten_element(child, [c for c in classes if c.startswith(("ff", "fs", "fc"))])

            # Re-bind processing contents to our perfectly flattened line nodes
            children = flattened_children
            div_t.clear()

            div_t_text_preview = " ".join(
                (c.get_text() if hasattr(c, "get_text") else str(c)) for c in children
                if not (getattr(c, "name", None) == "span" and c.get("class") and any(k.startswith("_") for k in c.get("class")))
            )
            # Justified-line detection: several wide gaps of near-equal width on
            # one line are stretched word spaces, not table column cuts.
            wide_gaps: List[float] = []
            for ch in children:
                ch_classes = ch.get("class") if hasattr(ch, "get") else None
                if isinstance(ch_classes, str):
                    ch_classes = ch_classes.split()
                if getattr(ch, "name", None) == "span" and ch_classes and any(c.startswith("_") for c in ch_classes):
                    w = next((spacer_map[c[1:]] for c in ch_classes if c.startswith("_") and c[1:] in spacer_map), 0.0)
                    w *= sx_orig
                    if w >= min(threshold_px, 0.8 * em_px if em_px else threshold_px):
                        wide_gaps.append(w)
            line_words = div_t_text_preview.split()
            wordy = bool(line_words) and sum(1 for w in line_words if re.search(r"[A-Za-zÀ-ÿ]{2,}", w)) >= 0.8 * len(line_words)
            justified_line = (
                em_px > 0 and len(wide_gaps) >= 3 and wordy
                and max(wide_gaps) <= 1.3 * min(wide_gaps) and max(wide_gaps) < 2.5 * em_px
            )

            current_group_text: List[str] = []
            current_group_elements: List[Any] = []

            def commit_group() -> None:
                nonlocal current_group_text, current_group_elements
                if not current_group_elements:
                    return

                # Fuse the textual values gathered in the current group
                merged_text = merge_color_runs("".join(current_group_text).strip())
                if merged_text:
                    # --- UNIVERSAL ACCENT NORMALIZATION (NFC) ---
                    # Merges split floating accents (like e + ´) into standard unicode characters (like é)
                    normalized_text = unicodedata.normalize('NFC', merged_text)
                    
                    gid = f"g-{idx[0]}"
                    original_texts_map[gid] = normalized_text
                    tid_to_page[gid] = page_idx

                    # Copy font styles from the children, but DO NOT inherit fc (font color) classes.
                    # This prevents the parent translation span from bleeding a single color over the entire line.
                    # Inherit ONE font family and ONE font size: the ones carrying the
                    # most characters. Inheriting every ff/fs of the group let the
                    # stylesheet's last rule win (e.g. a monospace e-mail font taking
                    # over a whole translated paragraph line).
                    line_ff = next((c for c in classes if c.startswith("ff")), None)
                    line_fs = next((c for c in classes if c.startswith("fs")), None)
                    ff_weight: Dict[str, int] = {}
                    fs_weight: Dict[str, int] = {}
                    for el in current_group_elements:
                        if not hasattr(el, "get"):
                            continue
                        el_classes = el.get("class", []) or []
                        weight = len(el.get_text().strip())
                        if weight == 0:
                            continue
                        ff = next((c for c in el_classes if c.startswith("ff")), line_ff)
                        fs = next((c for c in el_classes if c.startswith("fs")), line_fs)
                        if ff:
                            ff_weight[ff] = ff_weight.get(ff, 0) + weight
                        if fs:
                            fs_weight[fs] = fs_weight.get(fs, 0) + weight
                    inherited_classes = ["trans-span"]
                    if ff_weight:
                        inherited_classes.append(max(ff_weight, key=ff_weight.get))
                    if fs_weight:
                        inherited_classes.append(max(fs_weight, key=fs_weight.get))
                    # Wrap the unified group in a single localizable span
                    group_span = soup.new_tag("span", attrs={
                        "class": " ".join(inherited_classes),
                        "data-trans-id": gid,
                        "data-sx": str(sx_orig),
                        "data-sy": str(sy_orig),
                        "style": "display:inline;"
                    })
                    for el in current_group_elements:
                        group_span.append(el)
                    
                    # --- GEOMETRIC RESTORATION FIX ---
                    # Cache the exact original styled inner HTML inside the DOM.
                    # This ensures we can restore the pristine English text and fonts
                    # without causing layout metrics or scale calculation drift.
                    group_span["data-orig-html"] = group_span.decode_contents()

                    div_t.append(group_span)
                    line_spans.append((gid, group_span))
                    idx[0] += 1
                else:
                    # Fallback for empty spaces or layout floats
                    for el in current_group_elements:
                        div_t.append(el)

                current_group_text.clear()
                current_group_elements.clear()

            # Iterate through DOM elements to apply scaled grouping
            for child_pos, child in enumerate(children):
                # child_text = child.get_text().strip() if hasattr(child, "get_text") else str(child).strip()
                
                # Silently skip legacy PDF floating accents
                # if child_text in ACCENTS_TO_IGNORE:
                #     continue

                is_spacer = False
                width = 0.0

                # --- FIX : Systematic and defensive initialization of child_classes ---
                raw_classes = child.get("class") if hasattr(child, "get") else None
                if isinstance(raw_classes, str):
                    child_classes = raw_classes.split()
                elif isinstance(raw_classes, list):
                    child_classes = [str(cls) for cls in raw_classes]
                else:
                    child_classes = []

                # Now that it's initialized, we can use it safely
                if child.name == "span" and any(cls.startswith("_") for cls in child_classes):
                    is_spacer = True
                    known_width = False
                    for cls in child_classes:
                        if cls.startswith("_") and len(cls) > 1 and cls[1:] in spacer_map:
                            width = spacer_map[cls[1:]]
                            known_width = True
                            break
                    # pdf2htmlEX writes plain word spaces as <span class="_"> </span>
                    # (no width class): a literal blank is always a real word space.
                    if not known_width and child.get_text() and not child.get_text().strip():
                        current_group_elements.append(child)
                        current_group_text.append(" ")
                        continue

                if is_spacer:
                    # --- SCALED WIDTH CALCULATION (Core geometry fix) ---
                    scaled_width = width * sx_orig

                    # A wide gap right after a sentence end inside prose is the
                    # double space of justified (LaTeX) text, not a table column:
                    # splitting there broke paragraphs and sentences mid-way.
                    # Double space after a sentence end inside PROSE: the text before
                    # ends with . ? ! (not ")" "]" "," — table cells like "(dev)" or
                    # "top-1 err.") and the next word starts a sentence (capital).
                    next_text = ""
                    for nxt in children[child_pos + 1:]:
                        n_cls = nxt.get("class") if hasattr(nxt, "get") else None
                        if isinstance(n_cls, str):
                            n_cls = n_cls.split()
                        if getattr(nxt, "name", None) == "span" and n_cls and any(c.startswith("_") for c in n_cls):
                            continue
                        next_text = (nxt.get_text() if hasattr(nxt, "get_text") else str(nxt)).strip()
                        if next_text:
                            break
                    before = "".join(current_group_text)
                    sentence_gap = (
                        em_px > 0 and 0 < scaled_width < 2.0 * em_px
                        and re.search(r"[a-zà-ÿ]{2,}[.?!]\s*$", before) is not None
                        and re.match(r"[A-ZÀ-Þ][a-zà-ÿ]", next_text) is not None
                        and len(re.findall(r"[A-Za-zÀ-ÿ]{2,}", before)) >= 3
                    )
                    # Gaps narrower than 1 em, or regular gaps of a justified line,
                    # are word spaces whatever the column threshold.
                    word_gap = em_px > 0 and 0 < scaled_width and (
                        scaled_width < 1.0 * em_px or (justified_line and scaled_width < 2.5 * em_px))
                    if sentence_gap or word_gap:
                        current_group_elements.append(child)
                        current_group_text.append(" ")
                    elif abs(scaled_width) >= threshold_px:  # Uses the user-defined threshold px
                        # Case 1: Structural spacing -> Commit active group and append Red Cut marker
                        commit_group()
                        div_t.append(child)
                    elif scaled_width >= word_space_px:
                        # Case 2: Real word spacing -> Accumulate space and continue
                        current_group_elements.append(child)
                        current_group_text.append(" ")
                    else:
                        # Case 3: Kerning / Accent adjustments -> Accumulate elements WITHOUT any space!
                        current_group_elements.append(child)
                else:
                    # Normal styled text spans or strings
                    if isinstance(child, str):
                        current_group_text.append(str(child))
                        current_group_elements.append(child)
                    else:
                        # Extract raw text content
                        text_content = child.get_text()
                        # --- NORMALIZATION FIX: broken symbol-font encodings (Elsevier MT/Adv fonts) ---
                        # Only applied to font classes detected as symbol fonts, so real text
                        # such as Icelandic 'Þór' or the fraction '¼' is never corrupted.
                        own_ff = [c for c in child_classes if c.startswith("ff")]
                        effective_ff = own_ff or [c for c in classes if c.startswith("ff")]
                        if symbol_fonts and any(cls in symbol_fonts for cls in effective_ff):
                            text_content = text_content.translate(SYMBOL_GLYPH_FIXES)
                        
                        # Effective color = the LAST (innermost) fc class
                        color_hex = None
                        fc_classes = [c for c in child_classes if re.fullmatch(r"fc\d+", c)]
                        if fc_classes and fc_classes[-1] != "fc0":
                            color_hex = color_map.get(fc_classes[-1])
                        # Near-black is body text, not a color run
                        if color_hex and all(int(color_hex[i:i + 2], 16) < 0x40 for i in (0, 2, 4)):
                            color_hex = None
                        
                        # Wrap text in style XML tag if a special color is detected
                        if color_hex and text_content.strip():
                            styled_text = f"<color_{color_hex}>{text_content}</color_{color_hex}>"
                        else:
                            styled_text = text_content
                            
                        current_group_text.append(styled_text)
                        current_group_elements.append(child)

            commit_group()

            page_lines.append({
                "spans": line_spans,
                "x": next((x_map[c] for c in classes if c in x_map), None),
                "y": next((y_map[c] for c in classes if c in y_map), None),
                "fs": line_fs_cls,
                "m": next((c for c in classes if c in matrix_map), None),
                "sy": abs(sy_orig or 1.0),
                "em": em_px,
                "box": page_boxes[line_idx] if page_boxes else None,
            })

        # ── PARAGRAPH RECONSTRUCTION (DeepL-style reflow) ──
        for para in group_lines_into_paragraphs(page_lines, original_texts_map):
            pid = f"p-{para_idx[0]}"
            para_idx[0] += 1
            texts = []
            for line_no, line in enumerate(para):
                gid, span = line["spans"][0]
                line_text = original_texts_map.pop(gid)
                tid_to_page.pop(gid, None)
                span["data-para"] = pid
                span["data-para-line"] = str(line_no)
                for piece in line.get("pieces", []):
                    piece_texts = []
                    for p_gid, p_span in piece["spans"]:
                        piece_texts.append(original_texts_map.pop(p_gid, "").strip())
                        tid_to_page.pop(p_gid, None)
                        p_span["data-para"] = pid
                        p_span["data-para-line"] = str(line_no)
                        p_span["data-para-absorbed"] = "1"
                    p_text = " ".join(t for t in piece_texts if t)
                    if piece.get("sup"):
                        line_text = line_text.rstrip() + f"<sup>{p_text}</sup>"
                    elif piece.get("sub"):
                        line_text = line_text.rstrip() + f"<sub>{p_text}</sub>"
                    elif p_text[:1] in ",.;:)]":
                        line_text = line_text.rstrip() + p_text
                    else:
                        line_text = line_text.rstrip() + " " + p_text
                texts.append(line_text)
            original_texts_map[pid] = compose_stacked_accents(merge_color_runs(join_paragraph_lines(texts)))
            tid_to_page[pid] = page_idx

    # ── 2. EMBED GLASS OVERLAYS ON ALL PAGES ──
    for p_idx, page in enumerate(pages_list):
        glass_div = soup.new_tag("div", attrs={
            "id": f"glass-overlay-t-{p_idx}",
            "style": (
                "position: absolute; "
                "top: 5%; "
                "left: 5%; "
                "width: 90%; "
                "height: 90%; "
                "background: rgba(250, 250, 252, 0.98); "
                "border: 3px solid rgba(255,255,255,0.8); "
                "border-radius: 16px; "
                "box-shadow: 0 8px 32px rgba(31,38,135,0.15), 0 0 1px rgba(255,255,255,0.8); "
                "z-index: 1000; "
                "display: none; "
                "justify-content: center; "
                "align-items: center; "
                "pointer-events: none; "
                "transform: translate3d(0, 0, 0); "
                "backface-visibility: hidden; "
                "-webkit-backface-visibility: hidden;"
            )
        })

        inner_div = soup.new_tag("div", attrs={
            "style": (
                "background: rgba(255,255,255,0.92); "
                "padding: 24px 40px; "
                "border-radius: 12px; "
                "text-align: center; "
                "box-shadow: 0 10px 30px rgba(0,0,0,0.15); "
                "display: flex; "
                "flex-direction: column; "
                "align-items: center;"
            )
        })

        loader_div = soup.new_tag("div", attrs={"class": "circular-loader"})
        inner_div.append(loader_div)

        text_p = soup.new_tag("p", attrs={
            "style": "color:#1e293b; font-size:14px; font-weight:600; margin:0; font-family: sans-serif;"
        })
        text_p.string = "Waiting for translation..."
        inner_div.append(text_p)

        glass_div.append(inner_div)
        page.append(glass_div)

    # ── 3. INJECT STYLESHEET RULES (Shimmers, Spinners) ──
    style_tag = soup.new_tag("style")
    style_tag.string = """
        #sidebar { display: none !important; }
        /* pdf2htmlEX lazily hides off-screen pages (display:none): their lines
           would have no geometry for the paragraph reflow. Keep them rendered. */
        .pc { display: block !important; }
        #page-container { left: 0 !important; margin: 0 auto !important; }

        span[data-trans-id].translated {
            word-spacing: 0.25em !important;
            /* justified source lines carry letter-spacing that does not apply to new text */
            letter-spacing: normal !important;
        }

        div.t {
            white-space: nowrap !important;
        }

        /* pdf2htmlEX writes some word spaces as <span class="_"> </span>: nowrap would
           collapse that lone blank (inline-block) and glue words ("KaimingHe"). */
        div.t span._ {
            white-space: pre !important;
        }

       @keyframes loading-shimmer {
            0% { background-position: 100% 0; }
            100% { background-position: 0% 0; }
        }

        /* Skeleton bars: the highlight sweeps the WHOLE line (it used to stop
           after 300 px), with soft, page-neutral tones and rounded ends. */
        .shimmer-line {
            display: inline-block !important;
            background-color: rgba(148, 163, 184, 0.22) !important;
            background-image: linear-gradient(90deg,
                rgba(148, 163, 184, 0) 35%,
                rgba(148, 163, 184, 0.45) 50%,
                rgba(148, 163, 184, 0) 65%) !important;
            background-size: 300% 100% !important;
            background-repeat: no-repeat !important;
            animation: loading-shimmer 1.6s infinite ease-in-out !important;
            will-change: background-position !important;
            transform: translateZ(0) !important;
            border-radius: 999px !important;
            color: transparent !important;
            min-width: 30px;
        }
        @media (prefers-reduced-motion: reduce) {
            .shimmer-line { animation: none !important; }
        }
        .shimmer-line * { color: transparent !important; }

        .circular-loader {
            border: 4px solid #f3f4f6 !important;
            border-top: 4px solid #4f8ef7 !important;
            border-radius: 50% !important;
            width: 36px !important; height: 36px !important;
            animation: spin 1s linear infinite !important;
            margin-bottom: 12px !important;
        }
        @keyframes spin {
            0%   { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    """
    soup.head.append(style_tag)

    # ── 4. INJECT CLIENT JAVASCRIPT ACTIONS (DOM streams & dynamic page resets) ──
    script_tag = soup.new_tag("script")
    script_tag.string = r"""

        // ══════════════════════════════════════════════════════════════════
        // PARAGRAPH REFLOW (DeepL-style): a paragraph is translated as ONE text,
        // then its words are redistributed over the ORIGINAL line slots with a
        // single horizontal compression for the whole block, justified when the
        // source paragraph was justified. Inline <color_HEX>, <sup>, <sub>,
        // <b>, <i> tags are rendered as styled runs (never parsed as HTML).
        // ══════════════════════════════════════════════════════════════════
        var rtCanvas = null;
        function rtCtx() {
            if (!rtCanvas) rtCanvas = document.createElement('canvas');
            return rtCanvas.getContext('2d');
        }

        // Original geometry of a line, in PAGE coordinates (unzoomed CSS px).
        // pdf2htmlEX nests lines in clip boxes (div.c) for many publisher PDFs,
        // so offsetLeft is relative to the clip box: page rects are used instead.
        function rtCacheGeometry(divT) {
            if (!divT.hasAttribute('data-orig-sw')) {
                var span = divT.querySelector('span[data-trans-id]');
                var sx0 = parseFloat((span && span.getAttribute('data-sx')) || '1');
                var sy0 = parseFloat((span && span.getAttribute('data-sy')) || '1');
                divT.style.transform = 'matrix(' + sx0 + ',0,0,' + sy0 + ',0,0)';
                divT.setAttribute('data-orig-sw', divT.scrollWidth);
                divT.setAttribute('data-sx-orig', sx0);
                divT.setAttribute('data-sy-orig', sy0);
            }
            if (!divT.hasAttribute('data-orig-pleft')) {
                var page = divT.closest('.pf') || document.body;
                var pr = page.getBoundingClientRect();
                var k = (page.offsetWidth && pr.width) ? pr.width / page.offsetWidth : 1;
                var r = divT.getBoundingClientRect();
                divT.setAttribute('data-orig-pleft', (r.left - pr.left) / k);
                divT.setAttribute('data-orig-left', divT.offsetLeft);
            }
            var sw = parseFloat(divT.getAttribute('data-orig-sw'));
            var sxo = parseFloat(divT.getAttribute('data-sx-orig'));
            var pleft = parseFloat(divT.getAttribute('data-orig-pleft'));
            return { left: pleft, right: pleft + sw * sxo, sw: sw, offsetLeft: parseFloat(divT.getAttribute('data-orig-left')),
                     sx: sxo, sy: parseFloat(divT.getAttribute('data-sy-orig')) };
        }

        // Splits translated text into styled words: [{parts:[{t, st}], space}]
        function rtTokenize(text) {
            var tokens = [], cur = null, style = {}, stack = [];
            var re = /<(\/?)(color_([0-9a-fA-F]{6})|color(?:_\w+)?|sup|sub|b|i)>/g, last = 0, m;
            var pieces = [];
            while ((m = re.exec(text)) !== null) {
                if (m.index > last) pieces.push({ t: text.slice(last, m.index), st: Object.assign({}, style) });
                var closing = m[1] === '/', tag = m[2];
                if (!closing) {
                    stack.push(Object.assign({}, style));
                    if (m[3]) style.color = '#' + m[3];
                    else if (tag === 'sup') style.sup = true;
                    else if (tag === 'sub') style.sub = true;
                    else if (tag === 'b') style.b = true;
                    else if (tag === 'i') style.i = true;
                } else {
                    style = stack.length ? stack.pop() : {};
                }
                last = re.lastIndex;
            }
            if (last < text.length) pieces.push({ t: text.slice(last), st: Object.assign({}, style) });

            var pendingSpace = false;
            pieces.forEach(function (p) {
                p.t.split(/(\s+)/).forEach(function (chunk) {
                    if (!chunk) return;
                    if (/^\s+$/.test(chunk)) { pendingSpace = true; cur = null; return; }
                    if (!cur || pendingSpace) {
                        cur = { parts: [], space: pendingSpace && tokens.length > 0 };
                        tokens.push(cur);
                        pendingSpace = false;
                    }
                    cur.parts.push({ t: chunk, st: p.st });
                });
            });
            return tokens;
        }

        function rtFontFor(span, st) {
            var cs = getComputedStyle(span);
            var size = parseFloat(cs.fontSize) * ((st && (st.sup || st.sub)) ? 0.7 : 1);
            var weight = (st && st.b) ? '700' : cs.fontWeight;
            var fstyle = (st && st.i) ? 'italic' : cs.fontStyle;
            return fstyle + ' ' + weight + ' ' + size + 'px ' + cs.fontFamily;
        }

        function rtRenderTokens(span, tokens) {
            while (span.firstChild) span.removeChild(span.firstChild);
            tokens.forEach(function (tok, k) {
                if (k > 0 && tok.space) span.appendChild(document.createTextNode(' '));
                tok.parts.forEach(function (p) {
                    var st = p.st || {};
                    if (!st.color && !st.sup && !st.sub && !st.b && !st.i) {
                        span.appendChild(document.createTextNode(p.t));
                        return;
                    }
                    var el = document.createElement('span');
                    if (st.color) el.style.color = st.color;
                    if (st.b) el.style.fontWeight = '700';
                    if (st.i) el.style.fontStyle = 'italic';
                    if (st.sup || st.sub) {
                        el.style.fontSize = '70%';
                        el.style.verticalAlign = st.sup ? 'super' : 'sub';
                        el.style.lineHeight = '0';
                    }
                    el.textContent = p.t;
                    span.appendChild(el);
                });
            });
        }

        var rtRelayoutTimer = null;
        function rtRelayoutAll() {
            clearTimeout(rtRelayoutTimer);
            rtRelayoutTimer = setTimeout(function () {
                var paras = window.__rtParas || {};
                Object.keys(paras).forEach(function (pid) { window.reflowParagraph(pid, paras[pid]); });
                if (window.harmonizeAllPages) window.harmonizeAllPages();
            }, 30);
        }
        if (document.fonts && document.fonts.addEventListener) {
            document.fonts.addEventListener('loadingdone', rtRelayoutAll);
        }

        window.reflowParagraph = function (paraId, translatedText) {
            var all = Array.prototype.slice.call(document.querySelectorAll('[data-para="' + paraId + '"]'));
            if (!all.length) return;
            translatedText = String(translatedText).replace(/\s*\n\s*/g, ' ').trim();
            var lineNo = function (s) { return parseInt(s.getAttribute('data-para-line') || '0', 10); };
            var slots = all.filter(function (s) { return !s.hasAttribute('data-para-absorbed'); })
                           .sort(function (a, b) { return lineNo(a) - lineNo(b); });
            if (!slots.length) return;

            // Original geometry: left edge of each slot, right edge of each visual line
            var rights = {}, paraRight = -Infinity, sxs = [];
            all.forEach(function (s) {
                var g = rtCacheGeometry(s.closest('div.t'));
                var n = lineNo(s);
                rights[n] = Math.max(rights[n] || -Infinity, g.right);
                paraRight = Math.max(paraRight, g.right);
            });
            var geo = slots.map(function (s) {
                var g = rtCacheGeometry(s.closest('div.t'));
                sxs.push(g.sx);
                return g;
            });
            var sorted = sxs.slice().sort(function (a, b) { return a - b; });
            var sxBase = sorted[Math.floor(sorted.length / 2)];

            // Common right edge = median of the full lines' right edges (all but
            // the last line). The max was fooled by lines ending with an
            // invisible trailing spacer, which widened the whole block.
            // Never extend past text of ANOTHER column on the same line (tables,
            // side-by-side columns): clamp the block's right edge before it.
            (function () {
                var page = slots[0].closest('.pf');
                if (!page) return;
                var own = new Set(all.map(function (s) { return s.closest('div.t'); }));
                var pr = page.getBoundingClientRect();
                var k = (page.offsetWidth && pr.width) ? pr.width / page.offsetWidth : 1;
                var limit = Infinity;
                var rects = slots.map(function (s) { return s.closest('div.t').getBoundingClientRect(); });
                page.querySelectorAll('div.t').forEach(function (d) {
                    if (own.has(d) || !d.textContent.trim()) return;
                    var r = d.getBoundingClientRect();
                    var left = (r.left - pr.left) / k;
                    for (var i = 0; i < rects.length; i++) {
                        var a = rects[i];
                        var overlapV = Math.min(a.bottom, r.bottom) - Math.max(a.top, r.top);
                        // A neighbour column starts AFTER this line's own text:
                        // stacked accents (separate glyph boxes over a letter)
                        // lie inside the line and must not shrink the block.
                        var ownRight = (a.right - pr.left) / k;
                        if (overlapV > 0.5 * Math.min(a.height, r.height) && left > ownRight - 2) {
                            limit = Math.min(limit, left - 4);
                        }
                    }
                });
                // A "neighbour" that would leave less than half of the typical
                // line width is the paragraph's own continuation (a word split
                // around a stacked accent), not another column.
                var widths = geo.map(function (g) { return g.right - g.left; }).sort(function (a, b) { return a - b; });
                var typicalWidth = widths[Math.floor(widths.length / 2)] || 0;
                var minLeft = Math.min.apply(null, geo.map(function (g) { return g.left; }));
                if (limit - minLeft < 0.5 * typicalWidth) limit = Infinity;
                if (limit < Infinity && limit < paraRight) paraRight = Math.max(limit, Math.max.apply(null, geo.map(function (g) { return g.left; })) + 20);
            })();

            var lineRights = slots.map(function (s) { return rights[lineNo(s)]; });
            var fullRights = (lineRights.length > 1 ? lineRights.slice(0, -1) : lineRights).slice().sort(function (a, b) { return a - b; });
            var medianRight = fullRights[Math.floor(fullRights.length / 2)];
            paraRight = Math.min(paraRight, Math.max(medianRight, lineRights[lineRights.length - 1] || medianRight));
            var paraLeft = Math.min.apply(null, geo.map(function (g) { return g.left; }));
            var paraWidth = Math.max(1, paraRight - paraLeft);

            // Justified source? (non-last lines reach the common right edge)
            var full = 0;
            for (var i = 0; i < slots.length - 1; i++) {
                if (rights[lineNo(slots[i])] >= paraRight - 0.02 * paraWidth) full++;
            }
            var justified = slots.length >= 2 && full >= Math.max(1, Math.ceil(0.6 * (slots.length - 1)));

            // One font for the whole block: the font carrying the most characters
            // in the source paragraph (not the first line's, which may start
            // with an italic or bold word).
            var ffWeight = {}, ffSpan = {};
            all.forEach(function (s) {
                var cls = (s.getAttribute('data-orig-class') || s.className);
                var ff = (cls.match(/\bff[0-9a-f]+\b/) || ['_'])[0];
                var tmp = new DOMParser().parseFromString(s.getAttribute('data-orig-html') || '', 'text/html');
                var n = ((tmp.body && tmp.body.textContent) || '').length;
                ffWeight[ff] = (ffWeight[ff] || 0) + n;
                if (!ffSpan[ff] && !s.hasAttribute('data-para-absorbed')) ffSpan[ff] = s;
            });
            var bestFf = Object.keys(ffWeight).sort(function (a, b) { return ffWeight[b] - ffWeight[a]; })[0];
            var fontSpan = ffSpan[bestFf] || slots[0];
            var ctx = rtCtx();
            var tokens = rtTokenize(translatedText);
            var fontPx = parseFloat(getComputedStyle(fontSpan).fontSize) || 16;
            ctx.font = rtFontFor(fontSpan, null);
            // Embedded fonts load lazily and document.fonts.check() is not
            // reliable for them: every laid-out paragraph is recorded and laid
            // out again whenever a font finishes loading (see rtFontsSettled).
            window.__rtParas = window.__rtParas || {};
            window.__rtParas[paraId] = translatedText;
            var spaceW = ctx.measureText(' ').width;
            var gap = Math.max(spaceW, 0.25 * fontPx);
            tokens.forEach(function (tok) {
                tok.w = 0;
                tok.parts.forEach(function (p) {
                    ctx.font = rtFontFor(fontSpan, p.st);
                    p.w = ctx.measureText(p.t).width;
                    tok.w += p.w;
                });
            });

            // Largest uniform compression c (<= 1) letting the words fit in the slots
            function layout(c) {
                var lines = [], idx = 0;
                for (var s = 0; s < slots.length; s++) {
                    var cap = (paraRight - geo[s].left) / (sxBase * c) * 0.995;
                    var line = { tokens: [], width: 0, cap: cap };
                    while (idx < tokens.length) {
                        var tok = tokens[idx];
                        var add = (line.tokens.length && tok.space ? gap : 0) + tok.w;
                        if (line.tokens.length && line.width + add > cap) break;
                        line.tokens.push(tok);
                        line.width += add;
                        idx++;
                    }
                    lines.push(line);
                }
                return { lines: lines, rest: tokens.slice(idx) };
            }
            var c = 1.0, plan = layout(c);
            while (plan.rest.length && c > 0.6) {
                c = Math.round((c - 0.02) * 100) / 100;
                plan = layout(c);
            }
            if (plan.rest.length) {      // still too long: keep every word, last line overflows
                var lastLine = plan.lines[plan.lines.length - 1];
                lastLine.tokens = lastLine.tokens.concat(plan.rest);
            }
            var lastUsed = -1;
            plan.lines.forEach(function (l, k) { if (l.tokens.length) lastUsed = k; });

            var commonFfs = bestFf && bestFf !== '_' ? bestFf : null;
            // Shrink proportionally (like a smaller font) rather than squeezing
            // glyphs horizontally; below 0.82 the extra reduction is horizontal only.
            var cy = Math.max(c, 0.82);
            slots.forEach(function (span, s) {
                var divT = span.closest('div.t');
                var line = plan.lines[s];
                if (!span.hasAttribute('data-orig-class')) span.setAttribute('data-orig-class', span.className);
                if (commonFfs) {
                    span.className = span.className.replace(/\bff[0-9a-f]+\b/g, '').trim() + ' ' + commonFfs;
                }
                rtRenderTokens(span, line.tokens);
                span.classList.add('translated');
                span.classList.remove('shimmer-line');
                var ws = gap - spaceW;
                var gaps = 0;
                line.tokens.forEach(function (t, k) { if (k > 0 && t.space) gaps++; });
                if (justified && s < lastUsed && gaps > 0) {
                    var extra = (line.cap - line.width) / gaps;
                    if (extra > 0 && extra < 1.6 * fontPx) ws += extra;
                }
                span.style.setProperty('word-spacing', ws + 'px', 'important');
                span.style.setProperty('letter-spacing', 'normal', 'important');
                divT.style.transform = 'matrix(' + (sxBase * c) + ',0,0,' + (geo[s].sy * cy) + ',0,0)';
                divT.removeAttribute('data-fit');
                // Safety: never spill past the paragraph's right edge
                var shown = divT.scrollWidth * sxBase * c;
                var allowed = paraRight - geo[s].left;
                if (shown > allowed * 1.01 && shown > 0) {
                    divT.style.transform = 'matrix(' + (sxBase * c * allowed / shown) + ',0,0,' + (geo[s].sy * cy) + ',0,0)';
                }
            });
            all.forEach(function (span) {
                if (span.hasAttribute('data-para-absorbed')) {
                    while (span.firstChild) span.removeChild(span.firstChild);
                    span.classList.add('translated');
                    span.classList.remove('shimmer-line');
                }
            });
        };

        // Single lines: re-center a translated line that was centered on its page
        // (titles, headings, captions), instead of leaving it flush left.
        function rtRecenterIfCentered(divT, span) {
            var page = divT.closest('.pf');
            if (!page) return;
            // Only lone lines (titles, headings): never a table row or a line with several cells
            if (divT.querySelectorAll('span[data-trans-id]').length !== 1) return;
            var g = rtCacheGeometry(divT);
            var pageW = page.offsetWidth;
            var origW = g.sw * g.sx;
            var center = g.left + origW / 2;
            if (origW > 0.85 * pageW || Math.abs(center - pageW / 2) > 0.02 * pageW) return;
            var m = /matrix\(([-\d.e]+)/.exec(divT.style.transform || '');
            var curSx = m ? parseFloat(m[1]) : g.sx;
            var newW = divT.scrollWidth * curSx;
            divT.style.left = (g.offsetLeft + (origW - newW) / 2) + 'px';
        }

        // A page that receives text is no longer "waiting": drop its overlay
        // even if the 'preparePage' signal was missed (iframe reload race).
        window.rtRevealPageOf = function(el) {
            var pf = el && el.closest ? el.closest('.pf') : null;
            if (!pf) return;
            var pages = document.querySelectorAll('.pf');
            var idx = Array.prototype.indexOf.call(pages, pf);
            var glass = document.getElementById('glass-overlay-t-' + idx);
            if (glass && glass.style.display !== 'none') glass.style.display = 'none';
        };

        window.applyTranslation = function(transId, translatedText) {
            try {
                window.rtRevealPageOf(document.querySelector('[data-trans-id="' + transId + '"]'));
                // Empty = untranslatable segment (number, formula): keep the original
                if (translatedText === '' || translatedText === null || translatedText === undefined) {
                    var keep = document.querySelector('[data-trans-id="' + transId + '"]');
                    if (keep) keep.classList.remove('shimmer-line');
                    return;
                }
                // Unchanged by the translator (author names, affiliations, codes):
                // the original line stays untouched, so its superscripts and
                // exact glyph positions are preserved.
                var srcEls = document.querySelectorAll('[data-trans-id="' + transId + '"], [data-para="' + transId + '"]');
                if (srcEls.length) {
                    var parser = new DOMParser(), src = '';
                    srcEls.forEach(function (e) {
                        var h = e.getAttribute('data-orig-html');
                        src += ' ' + (h !== null ? (parser.parseFromString(h, 'text/html').body.textContent || '') : e.textContent);
                    });
                    var norm = function (t) { return String(t).replace(/<[^>]+>/g, '').replace(/[\s\u00ad-]+/g, ''); };
                    if (norm(src) === norm(translatedText)) {
                        srcEls.forEach(function (e) { e.classList.remove('shimmer-line'); });
                        window.rtRevealPageOf(srcEls[0]);
                        return;
                    }
                }
                if (String(transId).indexOf('p-') === 0) {
                    window.reflowParagraph(transId, translatedText);
                    return;
                }
                // Find the target translation span using its unique routing ID
                var span = document.querySelector('[data-trans-id="' + transId + '"]');
                if (!span) return;
                // A layout line cannot hold line breaks
                translatedText = String(translatedText).replace(/\s*\n\s*/g, ' ');

                // Performance optimization: Skip DOM updates if the translated text is identical to current content
                if (span.textContent.trim() === translatedText.trim()) {
                    span.classList.remove('shimmer-line');
                    return;
                }

                // Locate the closest text block container. pdf2htmlEX wraps lines in 'div.t' wrappers.
                var divT = span.closest('div.t');
                if (!divT) return;

                // Cache original geometric matrix scaling values (scaleX, scaleY)
                var sxOrig = parseFloat(span.getAttribute('data-sx') || '1');
                var syOrig = parseFloat(span.getAttribute('data-sy') || '1');

                // Initialize metrics backup on the first translation pass to prevent multi-pass calculation drift
                if (!divT.hasAttribute('data-orig-sw')) {
                    // Temporarily restore the original scale matrix to measure the true native scrollWidth
                    divT.style.transform = 'matrix(' + sxOrig + ',0,0,' + syOrig + ',0,0)';
                    divT.setAttribute('data-orig-sw', divT.scrollWidth);
                    divT.setAttribute('data-sx-orig', sxOrig);
                    divT.setAttribute('data-sy-orig', syOrig);
                }

                // Retrieve cached metric baselines
                var origSW = parseFloat(divT.getAttribute('data-orig-sw'));
                var sx     = parseFloat(divT.getAttribute('data-sx-orig'));
                var sy     = parseFloat(divT.getAttribute('data-sy-orig'));

                // Robust Color Formatting: Transform <color_HEX>...</color_HEX> tags into visual inline spans.
                // Uses [\s\S]*? to handle line breaks, and allows lazy LLM formatting variations (e.g. simplified </color> closure) [1.2.6].
                // SECURITY: the translation is untrusted (LLM output fed by PDF text).
                // It is NEVER parsed as HTML: only <color_HEX> tags are rebuilt via DOM nodes,
                // every other character is inserted as plain text.
                while (span.firstChild) span.removeChild(span.firstChild);
                var colorRe = /<color_([0-9a-fA-F]{6})>([\s\S]*?)<\/color(?:_\w+)?>/g;
                var lastIdx = 0, m;
                while ((m = colorRe.exec(translatedText)) !== null) {
                    if (m.index > lastIdx) {
                        span.appendChild(document.createTextNode(translatedText.slice(lastIdx, m.index)));
                    }
                    var colored = document.createElement('span');
                    colored.style.color = '#' + m[1];
                    colored.textContent = m[2];
                    span.appendChild(colored);
                    lastIdx = colorRe.lastIndex;
                }
                if (lastIdx < translatedText.length) {
                    span.appendChild(document.createTextNode(translatedText.slice(lastIdx)));
                }

                span.classList.add('translated');

                // Clear skeletal loading animations once real DOM content is injected [1.2.6]
                span.classList.remove('shimmer-line');

                // Compute adaptive horizontal scaling to fit the translated text within physical boundaries
                var newSW = divT.scrollWidth;

                if (newSW > 0 && origSW > 0) {
                    var newSx = sx * (origSW / newSW);
                    // Cap horizontal scaling to prevent unnecessary stretching of short text
                    newSx = Math.min(newSx, sx);
                    var ratio = newSx / sx;
                    divT.style.transform = 'matrix(' + newSx + ',0,0,' + (sy * Math.max(ratio, 0.82)) + ',0,0)';
                    divT.setAttribute('data-fit', String(newSx / sx));
                }
                rtRecenterIfCentered(divT, span);
                var pageEl = divT.closest('.pf');
                if (pageEl) window.scheduleHarmonize(pageEl);
            } catch (e) {
                console.error("Error in applyTranslation:", e);
            }
        };

        // ── PARAGRAPH HARMONIZATION ──
        // Each translated line is fitted to its original width on its own, so a
        // paragraph used to alternate compressed and full-size lines. Lines of
        // the same column/font/matrix share one compression level: lines that
        // need more than the group's 20th-percentile ratio keep their own fit
        // (never overflow); all others are aligned on it.
        window.harmonizePage = function(page) {
            try {
                var groups = {};
                page.querySelectorAll('div.t[data-fit]').forEach(function(d) {
                    var cls = d.className;
                    var key = ((cls.match(/\bx[0-9a-f]+\b/) || [''])[0]) + '|' +
                              ((cls.match(/\bfs[0-9a-f]+\b/) || [''])[0]) + '|' +
                              ((cls.match(/\bm[0-9a-f]+\b/) || [''])[0]);
                    (groups[key] = groups[key] || []).push(d);
                });
                Object.keys(groups).forEach(function(key) {
                    var lines = groups[key];
                    if (lines.length < 3) return;
                    var ratios = lines.map(function(d) { return parseFloat(d.getAttribute('data-fit')); })
                                      .sort(function(a, b) { return a - b; });
                    var target = ratios[Math.floor(0.2 * (ratios.length - 1))];
                    lines.forEach(function(d) {
                        var own = parseFloat(d.getAttribute('data-fit'));
                        var ratio = Math.min(own, target);
                        var sx = parseFloat(d.getAttribute('data-sx-orig'));
                        var sy = parseFloat(d.getAttribute('data-sy-orig'));
                        d.style.transform = 'matrix(' + (sx * ratio) + ',0,0,' + (sy * Math.max(ratio, 0.82)) + ',0,0)';
                    });
                });
            } catch (e) { console.error('harmonizePage', e); }
        };

        var harmonizeTimers = new Map();
        window.scheduleHarmonize = function(page) {
            if (harmonizeTimers.has(page)) clearTimeout(harmonizeTimers.get(page));
            harmonizeTimers.set(page, setTimeout(function() {
                harmonizeTimers.delete(page);
                window.harmonizePage(page);
            }, 60));
        };

        window.harmonizeAllPages = function() {
            document.querySelectorAll('.pf').forEach(function(p) { window.harmonizePage(p); });
        };

        window.preparePageForTranslation = function(pageIdx) {
            var pages = document.querySelectorAll('.pf');
            var page = pages[pageIdx];
            if (!page) return;

            // Smoothly fade out and hide the waiting overlay to reveal the underlying page structure [1.2.6]
            var glass = document.getElementById('glass-overlay-t-' + pageIdx);
            if (glass) {
                glass.style.transition = 'opacity 0.3s ease-out';
                glass.style.opacity = '0';
                setTimeout(function() { glass.style.display = 'none'; }, 300);
            }

            // Apply shimmer skeletal loaders to all targeted translation units on this page [1.2.6]
            page.querySelectorAll('span[data-trans-id]').forEach(function(span) {
                span.classList.add('shimmer-line');
            });
        };

        window.resetPageToWaiting = function(pageIdx) {
            var pages = document.querySelectorAll('.pf');
            var page = pages[pageIdx];
            if (!page) return;

            // Remove shimmering animation states to clean up DOM rendering [1.2.6]
            page.querySelectorAll('span[data-trans-id]').forEach(function(span) {
                span.classList.remove('shimmer-line');
            });

            // Reconstruct the waiting overlay if missing, or restore its visibility.
            // This prevents unrendered pages from displaying blank gaps if translation halts midway.
            var glass = document.getElementById('glass-overlay-t-' + pageIdx);
            if (!glass) {
                glass = document.createElement('div');
                glass.id = 'glass-overlay-t-' + pageIdx;
                glass.style.cssText = "position: absolute; top: 5%; left: 5%; width: 90%; height: 90%; background: linear-gradient(135deg, rgba(255,255,255,0.45), rgba(255,255,255,0.15)); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); border: 1px solid rgba(255,255,255,0.5); border-radius: 16px; box-shadow: 0 8px 32px rgba(31,38,135,0.25), 0 0 1px rgba(255,255,255,0.5); z-index: 1000; display: flex; justify-content: center; align-items: center; pointer-events: none;";
                
                var inner = document.createElement('div');
                inner.style.cssText = "background: rgba(255,255,255,0.92); padding: 24px 40px; border-radius: 12px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.15); display: flex; flex-direction: column; align-items: center;";
                
                var loader = document.createElement('div');
                loader.className = 'circular-loader';
                
                var text_p = document.createElement('p');
                text_p.style.cssText = "color:#1e293b; font-size:14px; font-weight:600; margin:0; font-family: sans-serif;";
                text_p.textContent = window.RT_WAITING_TEXT || "Waiting for translation...";
                
                inner.appendChild(loader);
                inner.appendChild(text_p);
                glass.appendChild(inner);
                page.appendChild(glass);
            }
            // The page shows its original text until translated (no overlay)
            glass.style.display = 'none';
        };

        // Secure message bus routing to receive events and updates from parent window contexts
        window.addEventListener('message', function(event) {
            var msg = event.data;
            if (!msg) return;

            if (msg.action === 'applyTranslation') {
                window.applyTranslation(msg.transId, msg.translatedText);
            } else if (msg.action === 'preparePage') {
                window.preparePageForTranslation(msg.pageIdx);
            } else if (msg.action === 'resetPage') {
                window.resetPageToWaiting(msg.pageIdx);
            }
        });



        // ── FEATURE : BILINGUAL HOVER PEEK WITH CTRL KEY (High Performance Event Delegation) ──
        var hoveredSpan = null;

        // Create and append the dynamic tooltip box on document load
        var tooltip = document.createElement('div');
        tooltip.id = 'rt-bilingual-tooltip';
        tooltip.style.cssText = "position: absolute; display: none; background: rgba(15, 23, 42, 0.96); backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px); color: #ffffff; padding: 10px 14px; border-radius: 6px; font-size: 11px; max-width: 420px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); z-index: 5000; border: 1px solid rgba(255,255,255,0.15); line-height: 1.5; pointer-events: none; transition: opacity 0.1s ease; opacity: 0; font-family: 'Segoe UI', -apple-system, sans-serif; white-space: pre-line;";
        document.body.appendChild(tooltip);

        // Shown while Ctrl is held, or always when "Show the original text on
        // hover" is enabled in the settings (window.RT_HOVER_ORIGINAL, set by
        // the app). Only translated text shows a bubble.
        var peekOn = function (e) { return e.ctrlKey || window.RT_HOVER_ORIGINAL === true; };
        var peekTarget = function (el) {
            var span = el && el.closest ? el.closest('span[data-trans-id]') : null;
            if (!span) return null;
            var pid = span.getAttribute('data-para');
            var translated = pid
                ? document.querySelector('[data-para="' + pid + '"].translated, [data-para="' + pid + '"] .translated, [data-para="' + pid + '"][data-rt-reflowed]')
                : (span.classList.contains('translated') ? span : null);
            return (translated || (pid && window.__rtParas && window.__rtParas[pid])) ? span : null;
        };

        document.addEventListener('mouseover', function(e) {
            var span = peekTarget(e.target);
            if (span && peekOn(e)) {
                hoveredSpan = span;
                showTooltip(span);
                positionTooltip(e);
            }
        });

        document.addEventListener('mousemove', function(e) {
            if (hoveredSpan && peekOn(e)) {
                positionTooltip(e);
            } else if (hoveredSpan) {
                hideTooltip();
            }
        });

        document.addEventListener('mouseout', function(e) {
            var span = e.target.closest('span[data-trans-id]');
            if (span && span === hoveredSpan) {
                hideTooltip();
                hoveredSpan = null;
            }
        });

        // Handle situations where the user presses or releases Control while hovering
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Control' && hoveredSpan) {
                showTooltip(hoveredSpan);
            }
        });

        document.addEventListener('keyup', function(e) {
            if (e.key === 'Control' && window.RT_HOVER_ORIGINAL !== true) {
                hideTooltip();
            }
        });

        function showTooltip(span) {
            // A reflowed paragraph shows its WHOLE original text, in line order
            var pid = span.getAttribute('data-para');
            var parts = pid
                ? Array.prototype.slice.call(document.querySelectorAll('[data-para="' + pid + '"]'))
                    .sort(function (a, b) { return (+a.getAttribute('data-para-line') || 0) - (+b.getAttribute('data-para-line') || 0); })
                : [span];
            var parser = new DOMParser();
            // DOMParser documents are inert: no script or onerror handler can run
            var cleanText = parts.map(function (el) {
                var h = el.getAttribute('data-orig-html');
                return h ? ((parser.parseFromString(h, 'text/html').body || {}).textContent || '') : '';
            }).join(' ').replace(/\s+/g, ' ').replace(/(\w)- (\w)/g, '$1$2').trim();

            if (!cleanText) return;

            tooltip.textContent = (window.RT_ORIGINAL_LABEL || "Original") + " : " + cleanText;
            tooltip.style.display = 'block';
            setTimeout(function() { tooltip.style.opacity = '1'; }, 10);
        }

        function positionTooltip(e) {
            // Smoothly position the tooltip near the active mouse pointer
            // Fixed to the viewport; the app zooms <body>, so viewport
            // coordinates are divided by that zoom.
            var z = parseFloat(document.body.style.zoom) || 1;
            tooltip.style.position = 'fixed';
            var x = (e.clientX + 15) / z, y = (e.clientY - 15) / z - tooltip.offsetHeight;
            var maxX = window.innerWidth / z - tooltip.offsetWidth - 8;
            tooltip.style.left = Math.max(4, Math.min(x, maxX)) + 'px';
            tooltip.style.top = (y < 4 ? (e.clientY + 20) / z : y) + 'px';
        }

        function hideTooltip() {
            tooltip.style.opacity = '0';
            tooltip.style.display = 'none';
            hoveredSpan = null;
        }
    """
    soup.body.append(script_tag)

    # ── 5. SAVE INSTRUMENTED HTML ──
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    return original_texts_map, tid_to_page