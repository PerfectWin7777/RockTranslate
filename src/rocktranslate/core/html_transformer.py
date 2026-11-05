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
# Safe imports supporting both standard package modules and direct scripts
from .constants import DEFAULT_ASSETS_DIR, ACCENTS_TO_IGNORE, THRESHOLD_PX
from .downloader import check_and_download_pdf2htmlex, pdf2htmlex_data_dir

# Seconds without any stderr output before the conversion is considered hung.
# A total time limit would kill legitimate long conversions of large documents,
# so only inactivity is punished: a healthy conversion always emits progress.
STALL_TIMEOUT_SECONDS = 30.0

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

    # Bypass compilation ONLY if raw HTML is already generated and is not empty
    if os.path.exists(output_html_path) and os.path.getsize(output_html_path) > 0:
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
        env=env                     # Parallel workers pass an isolated TEMP/TMP here
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
    stderr_tail: "deque" = deque(maxlen=8)

    while True:
        wait_budget = stall_timeout
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error(f"pdf2htmlEX conversion exceeded the {timeout}s total budget on: {pdf_filename}")
                process.kill()
                process.wait(timeout=5)
                return None
            wait_budget = min(wait_budget, remaining)

        # Poll in short slices so cancellation stays responsive while the queue
        # is idle; silence across the whole budget still means the process hung.
        line: Optional[str] = None
        stalled = True
        stall_deadline = time.monotonic() + wait_budget
        while time.monotonic() < stall_deadline:
            if check_cancelled is not None and check_cancelled():
                logger.info("pdf2htmlEX conversion cancelled by caller. Terminating the process.")
                process.kill()
                process.wait(timeout=5)
                _remove_quietly(partial_html_path)
                return None
            try:
                line = stderr_queue.get(timeout=1.0)
                stalled = False
                break
            except queue.Empty:
                continue

        if stalled:
            logger.error(
                f"pdf2htmlEX stalled for {stall_timeout}s without output on: {pdf_filename}. "
                "Terminating the hung process."
            )
            process.kill()
            process.wait(timeout=5)
            _remove_quietly(partial_html_path)
            LAST_CONVERSION_ERROR["message"] = f"pdf2htmlEX stalled for {stall_timeout:.0f}s (unsupported fonts?)"
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
PIPELINE_VERSION = 4


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
    pages_list = soup.find_all("div", class_="pf")
    symbol_fonts: Set[str] = detect_symbol_font_classes(soup)
    font_size_map: Dict[str, float] = parse_font_sizes(soup)

    # Retrieve configuration directly from JSON storage, falling back to constant if undefined
    threshold_px = float(config_db.get("TranslationConfig", "threshold_px", THRESHOLD_PX))

    original_texts_map: Dict[str, str] = {}
    tid_to_page: Dict[str, int] = {}
    idx: List[int] = [0]

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


        for div_t in sorted_div_t:
            # Determine line scaling factors (scaleX, scaleY)
            classes = div_t.get("class", [])
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
                        current_classes.extend(element.get("class"))
                    for child_node in list(element.contents):
                        flatten_element(child_node, current_classes)
                else:
                    flattened_children.append(element)

            for child in children:
                flatten_element(child, [])

            # Re-bind processing contents to our perfectly flattened line nodes
            children = flattened_children
            div_t.clear()

            current_group_text: List[str] = []
            current_group_elements: List[Any] = []

            def commit_group() -> None:
                nonlocal current_group_text, current_group_elements
                if not current_group_elements:
                    return

                # Fuse the textual values gathered in the current group
                merged_text = "".join(current_group_text).strip()
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
                    idx[0] += 1
                else:
                    # Fallback for empty spaces or layout floats
                    for el in current_group_elements:
                        div_t.append(el)

                current_group_text.clear()
                current_group_elements.clear()

            # Iterate through DOM elements to apply scaled grouping
            for child in children:
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

                    if abs(scaled_width) >= threshold_px:  # Uses the user-defined threshold px
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
                        
                        color_hex = None
                        for cls in child_classes:
                            # Ignore default color class (fc0) to keep normal text clean
                            if cls == "fc0":
                                continue
                            if cls in color_map:
                                color_hex = color_map[cls]
                                break
                        
                        # Wrap text in style XML tag if a special color is detected
                        if color_hex and text_content.strip():
                            styled_text = f"<color_{color_hex}>{text_content}</color_{color_hex}>"
                        else:
                            styled_text = text_content
                            
                        current_group_text.append(styled_text)
                        current_group_elements.append(child)

            commit_group()

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
                "display: flex; "
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
            0% {
                background-position: -150px 0;
            }
            100% {
                background-position: 150px 0;
            }
        }
        
        .shimmer-line {
            display: inline-block !important;
            background: #f1f5f9 !important;
            background-image: linear-gradient(
                90deg, 
                #f1f5f9 0px, 
                #cbd5e1 40px, 
                #f1f5f9 80px
            ) !important;
            background-size: 250px 100% !important;
            background-repeat: no-repeat !important;
            animation: loading-shimmer 1.5s infinite linear !important;

            will-change: background-position !important;
            transform: translateZ(0) !important;

            border-radius: 4px !important;
            color: transparent !important;
            min-width: 30px;
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
        window.applyTranslation = function(transId, translatedText) {
            try {
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
                    divT.style.transform = 'matrix(' + newSx + ',0,0,' + sy + ',0,0)';
                    divT.setAttribute('data-fit', String(newSx / sx));
                }
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
                        d.style.transform = 'matrix(' + (sx * ratio) + ',0,0,' + sy + ',0,0)';
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
                text_p.textContent = "Waiting for translation...";
                
                inner.appendChild(loader);
                inner.appendChild(text_p);
                glass.appendChild(inner);
                page.appendChild(glass);
            } else {
                glass.style.display = 'flex';
                glass.style.opacity = '1';
            }
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
        tooltip.style.cssText = "position: absolute; display: none; background: rgba(15, 23, 42, 0.96); backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px); color: #ffffff; padding: 10px 14px; border-radius: 6px; font-size: 11px; max-width: 320px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); z-index: 5000; border: 1px solid rgba(255,255,255,0.15); line-height: 1.5; pointer-events: none; transition: opacity 0.1s ease; opacity: 0; font-family: 'Segoe UI', -apple-system, sans-serif; white-space: pre-line;";
        document.body.appendChild(tooltip);

        document.addEventListener('mouseover', function(e) {
            var span = e.target.closest('span[data-trans-id]');
            if (span && e.ctrlKey) {
                hoveredSpan = span;
                showTooltip(span);
            }
        });

        document.addEventListener('mousemove', function(e) {
            if (hoveredSpan && e.ctrlKey) {
                positionTooltip(e);
            } else if (hoveredSpan && !e.ctrlKey) {
                hideTooltip();
            }
        });

        document.addEventListener('mouseout', function(e) {
            var span = e.target.closest('span[data-trans-id]');
            if (span && span === hoveredSpan) {
                hideTooltip();
            }
        });

        // Handle situations where the user presses or releases Control while hovering
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Control' && hoveredSpan) {
                showTooltip(hoveredSpan);
            }
        });

        document.addEventListener('keyup', function(e) {
            if (e.key === 'Control') {
                hideTooltip();
            }
        });

        function showTooltip(span) {
            var origHtml = span.getAttribute('data-orig-html');
            if (!origHtml) return;

            // Create a temporary container to extract raw, unstyled text from original HTML
            // DOMParser documents are inert: no script or onerror handler can run
            var parsed = new DOMParser().parseFromString(origHtml, 'text/html');
            var cleanText = (parsed.body && parsed.body.textContent) || "";
            cleanText = cleanText.trim();

            if (!cleanText) return;

            tooltip.textContent = "🔍 Original : " + cleanText;
            tooltip.style.display = 'block';
            setTimeout(function() { tooltip.style.opacity = '1'; }, 10);
        }

        function positionTooltip(e) {
            // Smoothly position the tooltip near the active mouse pointer
            tooltip.style.left = (e.pageX + 15) + 'px';
            tooltip.style.top = (e.pageY - tooltip.offsetHeight - 15) + 'px';
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