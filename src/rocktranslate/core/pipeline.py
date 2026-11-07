"""
RockTranslate — Headless translation pipeline (shared by the CLI and the library)
Path: src/rocktranslate/core/pipeline.py

PDF -> pdf2htmlEX (isolated temp dir) -> instrumented HTML -> concurrent LLM
batches -> translated HTML -> headless Chromium vector PDF.

License: MIT License
"""

import contextlib
import os
import re
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

from .chunker import Batch, build_batches, should_translate
from .constants import DEFAULT_ASSETS_DIR, DEFAULT_PARALLEL_REQUESTS
from .html_transformer import LAST_CONVERSION_ERROR, convert_pdf_to_html, instrument_html
from .llm_client import LLMClient
from .renderer import apply_translations_offline, print_html_with_fallback, resolve_pdf_renderer


ProgressCallback = Callable[[int, int], None]


@dataclass
class TranslationReport:
    """Outcome of a headless translation run."""
    success: bool
    output_path: Optional[str] = None
    pages: List[int] = field(default_factory=list)
    segments_total: int = 0
    segments_translated: int = 0
    batches_total: int = 0
    batches_failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    error: str = ""


def parse_page_range(range_str: Optional[str], max_pages: int) -> Optional[List[int]]:
    """'1-3, 5' -> [0, 1, 2, 4] (0-based, clamped). None/empty -> None (all pages)."""
    if not range_str or not str(range_str).strip():
        return None
    pages = set()
    for part in str(range_str).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = (int(x.strip()) for x in part.split("-", 1))
                lo, hi = max(1, min(a, b)), min(max_pages, max(a, b))
                pages.update(p - 1 for p in range(lo, hi + 1))
            else:
                p = int(part)
                if 1 <= p <= max_pages:
                    pages.add(p - 1)
        except ValueError:
            continue
    return sorted(pages)


def build_source_contexts(
    original_texts: Dict[str, str], batches: List[Batch], context_size: int = 5
) -> List[Optional[str]]:
    """
    Sliding context made of the SOURCE paragraphs preceding each batch.
    Unlike a context built from previous translations, it is known upfront,
    so every batch is independent and batches can run concurrently.
    """
    ordered_ids = list(original_texts.keys())
    position = {seg_id: i for i, seg_id in enumerate(ordered_ids)}
    contexts: List[Optional[str]] = []
    for batch in batches:
        first_pos = position.get(batch.ids[0], 0)
        window = [
            original_texts[ordered_ids[i]]
            for i in range(max(0, first_pos - context_size * 3), first_pos)
            if should_translate(original_texts[ordered_ids[i]])
        ][-context_size:] if context_size > 0 else []
        contexts.append("\n".join(window) if window else None)
    return contexts


def run_batches_concurrently(
    client: LLMClient,
    batches: List[Batch],
    contexts: List[Optional[str]],
    parallel: int = DEFAULT_PARALLEL_REQUESTS,
    cancelled: Optional[Callable[[], bool]] = None,
    on_batch_done: Optional[Callable[[int, Optional[Dict[str, str]]], None]] = None,
) -> Tuple[Dict[str, str], int]:
    """
    Translates batches with at most `parallel` requests in flight.

    Returns:
        (translations by segment id, number of failed batches)
    """
    translations: Dict[str, str] = {}
    failed = 0
    parallel = max(1, int(parallel))
    is_cancelled = cancelled or (lambda: False)

    executor = ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="rocktranslate-llm")
    in_flight = {}
    next_idx = 0
    try:
        def submit(idx: int) -> None:
            fut = executor.submit(client.translate_batch, batches[idx].segments, contexts[idx], is_cancelled)
            in_flight[fut] = idx

        while next_idx < len(batches) and len(in_flight) < parallel:
            submit(next_idx)
            next_idx += 1

        while in_flight and not is_cancelled():
            finished, _ = wait(list(in_flight), timeout=0.25, return_when=FIRST_COMPLETED)
            for fut in finished:
                idx = in_flight.pop(fut)
                try:
                    results = fut.result()
                except Exception as e:  # pragma: no cover - defensive
                    logger.error(f"Batch {idx + 1} crashed: {e}")
                    results = None
                items = {r["id"]: r["translated"] for r in results} if results else None
                if items is None:
                    failed += 1
                else:
                    translations.update(items)
                if on_batch_done:
                    on_batch_done(idx, items)
                if next_idx < len(batches) and not is_cancelled():
                    submit(next_idx)
                    next_idx += 1
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return translations, failed


def _translation_cache_path(input_pdf: str, client: LLMClient,
                            first_page: Optional[int], last_page: Optional[int]) -> Optional[str]:
    try:
        import hashlib
        from .config_manager import config_db
        sha = hashlib.sha256()
        with open(input_pdf, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(chunk)
        span = f"p{first_page or 'all'}-{last_page or 'all'}"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{client.target_lang}__{client.model}__{span}")
        folder = os.path.join(str(config_db.get_cache_dir()), sha.hexdigest())
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f"headless.{safe}.json")
    except OSError:
        return None


def _load_cache(path: Optional[str], original_texts: Dict[str, str]) -> Dict[str, str]:
    if not path or not os.path.exists(path):
        return {}
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Only reuse entries whose source text is unchanged
        return {k: v["t"] for k, v in data.get("items", {}).items()
                if k in original_texts and v.get("s") == original_texts[k]
                and should_translate(original_texts[k])}
    except (OSError, ValueError, AttributeError, KeyError):
        return {}


_cache_lock = threading.Lock()


def _save_cache(path: Optional[str], items: Dict[str, str], sources: Dict[str, str]) -> None:
    if not path:
        return
    import json
    from .html_transformer import PIPELINE_VERSION
    src = sources
    with _cache_lock:
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"pipeline_version": PIPELINE_VERSION,
                           "items": {k: {"s": src.get(k, ""), "t": v} for k, v in items.items()}},
                          f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            logger.warning(f"Could not save the translation cache: {e}")


@contextlib.contextmanager
def _work_dir(input_pdf: str, span: str = "all"):
    """
    Persistent conversion folder (cache/<sha256>/headless_work), reused across
    runs: a fresh temp dir per run made pdf2htmlEX redo its cold-start work on
    Windows (long silent phase). Falls back to a temp dir if the cache fails.
    """
    folder = None
    try:
        import hashlib
        from .config_manager import config_db
        sha = hashlib.sha256()
        with open(input_pdf, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(chunk)
        # One folder per page span: the raw HTML of pages 1-2 must never be
        # reused for another range (it would translate the wrong pages)
        folder = os.path.join(str(config_db.get_cache_dir()), sha.hexdigest(), "headless_work", span)
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = None
    if folder is None:
        with tempfile.TemporaryDirectory(prefix="rocktranslate-") as tmp:
            yield tmp
    else:
        yield folder


def _layout_key(raw_html: str) -> Optional[str]:
    try:
        from .html_transformer import PIPELINE_VERSION
        st = os.stat(raw_html)
        return f"{PIPELINE_VERSION}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return None


def _load_layout_cache(work_dir: str, raw_html: str) -> Optional[Tuple[Dict[str, str], Dict[str, int]]]:
    """Instrumented workspace + segment maps of a previous run on the same raw HTML."""
    import json
    path = os.path.join(work_dir, "layout.json")
    key = _layout_key(raw_html)
    try:
        if not (key and os.path.exists(path) and os.path.exists(os.path.join(work_dir, "workspace.html"))):
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("key") != key or not data.get("original_texts"):
            return None
        return data["original_texts"], {k: int(v) for k, v in data["tid_to_page"].items()}
    except (OSError, ValueError, KeyError):
        return None


def _save_layout_cache(work_dir: str, raw_html: str, original_texts: Dict[str, str],
                       tid_to_page: Dict[str, int]) -> None:
    import json
    key = _layout_key(raw_html)
    if not key:
        return
    path = os.path.join(work_dir, "layout.json")
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"key": key, "original_texts": original_texts, "tid_to_page": tid_to_page}, f,
                      ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError as e:
        logger.warning(f"Could not cache the layout analysis: {e}")


def translate_pdf(
    input_pdf: str,
    output_pdf: Optional[str],
    client: LLMClient,
    pages: Optional[str] = None,
    parallel: int = DEFAULT_PARALLEL_REQUESTS,
    context_size: int = 5,
    progress: Optional[ProgressCallback] = None,
    keep_html: Optional[str] = None,
    user_password: Optional[str] = None,
    assets_dir: str = DEFAULT_ASSETS_DIR,
) -> TranslationReport:
    """
    Full headless pipeline. Untranslated pages are left in the original language.

    Args:
        input_pdf: Source PDF.
        output_pdf: Destination PDF (default: '<input>_translated.pdf').
        client: Configured LLMClient.
        pages: Optional page range ('1-3, 5'); default all pages.
        parallel: Concurrent LLM requests.
        context_size: Number of source paragraphs given as context to each batch.
        progress: Callback (batches_done, batches_total).
        keep_html: Optional path where the translated HTML is also written.
        user_password: Password for PDFs that require one to open.
    """
    started = time.monotonic()
    report = TranslationReport(success=False)

    if not os.path.isfile(input_pdf):
        report.error = f"File not found: {input_pdf}"
        return report

    if not output_pdf:
        base, _ = os.path.splitext(os.path.abspath(input_pdf))
        output_pdf = f"{base}_translated.pdf"
    report.output_path = output_pdf

    browser_path = resolve_pdf_renderer()

    page_list: Optional[List[int]] = None
    first_page = last_page = None
    if pages:
        from .pdf_metadata import get_pdf_metadata
        total = int(get_pdf_metadata(input_pdf).get("pages_count") or 0) or 10_000
        page_list = parse_page_range(pages, total)
        if not page_list:
            report.error = f"Invalid page range: {pages}"
            return report
        # Only convert the pages that are needed (contiguous span)
        first_page, last_page = page_list[0] + 1, page_list[-1] + 1
    span = f"p{first_page}-{last_page}" if first_page is not None else "all"

    with _work_dir(input_pdf, span) as work_dir:

        logger.info("Step 1/5: layout extraction (pdf2htmlEX)...")
        raw_html = convert_pdf_to_html(
            input_pdf, assets_dir, output_dir=work_dir,
            first_page=first_page, last_page=last_page, user_password=user_password,
        )
        if not raw_html:
            report.error = "pdf2htmlEX conversion failed: " + (LAST_CONVERSION_ERROR.get("message") or "unknown error")
            return report

        logger.info("Step 2/5: instrumenting the layout...")
        workspace_html = os.path.join(work_dir, "workspace.html")
        maps = _load_layout_cache(work_dir, raw_html)
        if maps:
            original_texts, tid_to_page = maps
            logger.info(f"Layout analysis reused from cache ({len(original_texts)} segments).")
        else:
            original_texts, tid_to_page = instrument_html(raw_html, workspace_html)
            _save_layout_cache(work_dir, raw_html, original_texts, tid_to_page)

        if first_page is not None and page_list is not None:
            # pdf2htmlEX page 0 is document page first_page-1: keep only requested pages
            offset = first_page - 1
            wanted = set(page_list)
            original_texts = {k: v for k, v in original_texts.items() if tid_to_page.get(k, 0) + offset in wanted}
            report.pages = page_list
        else:
            report.pages = sorted(set(tid_to_page.values()))

        report.segments_total = len(original_texts)

        # Translations already paid for (previous run, same file/range/model/language)
        cache_path = _translation_cache_path(input_pdf, client, first_page, last_page)
        cached = _load_cache(cache_path, original_texts)
        if cached:
            logger.info(f"Reusing {len(cached)} cached translations from a previous run.")
        pending_texts = {k: v for k, v in original_texts.items() if k not in cached}

        logger.info("Step 3/5: building batches...")
        batches = build_batches(pending_texts, client.model)
        report.batches_total = len(batches)
        contexts = build_source_contexts(original_texts, batches, context_size)
        translatable = {i for b in batches for i in b.ids}
        # Untranslatable segments (numbers, formulas, symbols) are NOT re-injected:
        # their original rendering (fonts, math glyphs) stays exactly intact.
        translations: Dict[str, str] = {}
        translations.update(cached)

        logger.info(f"Step 4/5: translating {len(translatable)} segments in {len(batches)} batches "
                    f"({parallel} in parallel)...")
        done = [0]

        def on_done(idx: int, items: Optional[Dict[str, str]]) -> None:
            done[0] += 1
            if items:
                cached.update(items)
                _save_cache(cache_path, cached, original_texts)
            if progress:
                progress(done[0], len(batches))

        llm_items, failed = run_batches_concurrently(client, batches, contexts, parallel, on_batch_done=on_done)
        translations.update(llm_items)
        report.batches_failed = failed
        report.segments_translated = len(llm_items) + len(cached.keys() - llm_items.keys())
        report.prompt_tokens = client.usage["prompt_tokens"]
        report.completion_tokens = client.usage["completion_tokens"]
        report.cost_usd = client.usage["cost_usd"]

        # Abort only when NOTHING could be translated (bad key, no network).
        # A batch the model keeps answering incompletely must not discard the
        # rest of the document (cached translations included).
        if batches and failed == len(batches) and not llm_items and not cached:
            report.error = "Every translation request failed (check the API key / network)."
            report.seconds = time.monotonic() - started
            return report

        logger.info("Step 5/5: rendering the translated PDF...")
        translated_html = os.path.join(work_dir, "translated.html")
        apply_translations_offline(workspace_html, translated_html, translations)
        if keep_html:
            import shutil
            shutil.copyfile(translated_html, keep_html)

        if not print_html_with_fallback(translated_html, output_pdf, browser_path):
            report.error = "Headless browser printing failed."
            report.seconds = time.monotonic() - started
            return report

    report.success = failed == 0
    if failed:
        report.error = f"{failed} batch(es) failed; their text stays in the original language."
    report.seconds = time.monotonic() - started
    return report
