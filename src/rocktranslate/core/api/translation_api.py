"""
RockTranslate — Asynchronous Extraction and Translation Web API Mixin
Path: src/rocktranslate/core/api/translation_api.py

Hosts background worker threads managing high-fidelity pdf2htmlEX parsing,
BeautifulSoup tag instrumentation, and asynchronous LiteLLM streaming translations.
Provides robust thread synchronization, page-by-page progress validation, 
graceful error/cancel recoveries, and complete internationalization (i18n) support.

Author: RockTranslate Contributors
License: MIT License
Version: 1.1.0
"""

import os
import json
import hashlib
import shutil
import threading
import tempfile
import re
import time
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from typing import Dict, List, Optional, Any, Set, Tuple
from loguru import logger

import webview
from ..html_transformer import convert_pdf_to_html, instrument_html, PIPELINE_VERSION, LAST_CONVERSION_ERROR
from ..config_manager import config_db
from ..constants import DEFAULT_ASSETS_DIR, DEFAULT_PROVIDERS, DEFAULT_PARALLEL_REQUESTS
from ..chunker import build_batches, should_translate
from ..llm_client import LLMClient
from ..renderer import apply_translations_offline, print_html_with_fallback
from ..pdf_metadata import get_pdf_metadata
from ..local_server import allow_file
from .preferences_api import record_run_usage


class TranslationApiMixin:
    """
    Mixin class driving background PDF layout parsing and LLM translation workers.
    Communicates dynamically with Alpine.js UI controllers using evaluate_js.
    """
    def __init__(self) -> None:
        # File paths tracking current active workspace files
        self._active_pdf_path: Optional[str] = None
        self._active_html_path: Optional[str] = None

        # Mapped original document data structures
        self._original_texts: Dict[str, str] = {}
        self._tid_to_page: Dict[str, int] = {}

        # Structured validation cache: { page_index: { segment_id: translated_text } }
        self._translated_pages: Dict[int, Dict[str, str]] = {}

        # Lazy preparation state: documents are opened instantly (PDF.js only) and
        # the pdf2htmlEX layout pipeline runs once, at the first translation request.
        self._is_prepared: bool = False
        self._metadata_total_pages: int = 0
        self._document_hash: Optional[str] = None

        # Passwords of protected PDFs for this session only (never written to disk)
        self._pdf_passwords: Dict[str, str] = {}

        # Thread synchronization: one cancellation Event per run
        self._cancel_event: threading.Event = threading.Event()
        self._current_translating_page: int = -1
        self._trans_thread: Optional[threading.Thread] = None

        # Mutual exclusion lock to prevent concurrent overlapping translation runs
        self._thread_lock = threading.Lock()

    # ==============================================================================
    # 1. BACKGROUND LAYOUT EXTRACTION WORKER
    # ==============================================================================

    # ==============================================================================
    # 1. BACKGROUND LAYOUT EXTRACTION WORKER
    # ==============================================================================

    def extract_pdf(self, file_path: str) -> None:
        """
        Launches a background daemon thread to convert, parse, and instrument
        the layout structure of a target PDF document. This prevents the main
        GUI thread from freezing during complex compilation runs.

        Args:
            file_path: Absolute filesystem path to the target PDF document.
        """
        # The same file requested twice in a row (double click, drop + dialog):
        # opened once, the duplicate is ignored.
        now = time.monotonic()
        last = getattr(self, "_last_open_request", (None, 0.0))
        if file_path and last[0] == file_path and now - last[1] < 3.0:
            logger.info("Duplicate open request ignored.")
            return
        self._last_open_request = (file_path, now)
        thread = threading.Thread(
            target=self._run_extraction,
            args=(file_path,),
            daemon=True
        )
        thread.start()


    def open_protected_pdf(self, file_path: str, password: str) -> None:
        """Exposed to the UI: retries opening a password-protected PDF."""
        if not file_path or password is None:
            return
        self._pdf_passwords[os.path.abspath(file_path)] = str(password)
        self.extract_pdf(file_path)

    def _run_extraction(self, pdf_path: str) -> None:
        """
        Opens a document instantly without running the pdf2htmlEX pipeline: the
        PDF is served straight to the PDF.js viewer while the heavy geometric
        layout preparation is deferred to the first translation request. If a
        prepared workspace already exists in the hash-keyed cache, it is loaded
        immediately so the dual-pane view is restored without any conversion.
        """
        try:
            # ── DEFENSIVE CHECK (Anti-Crash Guard for Drag and Drop Sandbox limits) ──
            if not pdf_path or not isinstance(pdf_path, str):
                logger.error("Extraction aborted: Received an invalid or empty file path (NoneType).")
                self._send_status_i18n("status_extraction_failed")
                self._send_toast_i18n("toast_extraction_failed", "error")
                # Cleanly return the UI state back to the welcome dashboard
                self._send_js("window.dispatchEvent(new CustomEvent('trigger-close-document'))")
                return

            if not os.path.exists(pdf_path):
                logger.error(f"Extraction aborted: file not found: {pdf_path}")
                self._send_status_i18n("status_extraction_failed")
                self._send_toast_i18n("toast_extraction_failed", "error")
                return

            self._send_status_i18n("status_extraction_start")
            logger.info(f"Opening document (lazy mode): {pdf_path}")

            # Register the document bounds from lightweight metadata (no conversion)
            password = self._pdf_passwords.get(os.path.abspath(pdf_path))
            metadata = get_pdf_metadata(pdf_path, password=password)
            if metadata.get("needs_password"):
                # Ask the UI for the password; open_protected_pdf() resumes the opening.
                self._send_status_i18n("status_pdf_password_required")
                self._send_js(
                    "window.dispatchEvent(new CustomEvent('request-pdf-password', "
                    f"{{ detail: {{ pdfPath: {json.dumps(pdf_path)}, retry: {json.dumps(password is not None)} }} }}))"
                )
                return
            total_pages = metadata.get("pages_count", 1) or 1

            # Reset per-document session state
            allow_file(pdf_path)
            self._active_pdf_path = pdf_path
            self._active_html_path = None
            self._original_texts = {}
            self._tid_to_page = {}
            self._translated_pages = {}
            self._is_prepared = False
            self._metadata_total_pages = int(total_pages)
            self._document_hash = self._compute_document_hash(pdf_path)

            self._add_to_recent_files(pdf_path)

            # Fast path: reuse a previously prepared workspace for this exact file
            cached = self._load_cached_preparation()
            if cached:
                workspace_html_path, original_texts_map, tid_to_page = cached
                self._active_html_path = workspace_html_path
                self._original_texts = original_texts_map
                self._tid_to_page = tid_to_page
                self._is_prepared = True
                total_pages = max(tid_to_page.values()) + 1 if tid_to_page else total_pages
                self._metadata_total_pages = int(total_pages)
                logger.info(f"Cache hit: prepared workspace restored instantly ({len(original_texts_map)} segments).")
            else:
                logger.info("No cached workspace: preparing the layout in the background (no LLM, no cost).")
                threading.Thread(target=self._prepare_in_background, args=(pdf_path,),
                                 name="rocktranslate-prep", daemon=True).start()

            config_db.set("RecentFiles", "active_total_pages", total_pages)

            self._send_status_i18n("status_extraction_success")
            logger.info(f"Document opened: {total_pages} pages, {len(self._original_texts)} segments mapped.")

            # Trigger workspace view transition on the frontend Web SPA.
            # htmlPath is None when the layout is not prepared yet: the right pane
            # then shows a placeholder until 'workspace-html-ready' is emitted.
            total_segments = len(self._original_texts)
            js_call = (
                f"window.dispatchEvent(new CustomEvent('document-ready', {{ "
                f"detail: {{ "
                f"pdfPath: {json.dumps(pdf_path)}, "
                f"htmlPath: {json.dumps(self._active_html_path)}, "
                f"totalPages: {total_pages}, "
                f"totalSegments: {total_segments} "
                f"}} "
                f"}}))"
            )
            self._send_js(js_call)

        except Exception as error:
            logger.error(f"Critical exception raised during background document processing: {error}")
            self._send_status_i18n("status_extraction_error", {"error": str(error)})
            self._send_toast_i18n("toast_extraction_error", "error", variables={"error": str(error)})

    # ==============================================================================
    # 1b. HASH-KEYED WORKSPACE CACHE & LAZY LAYOUT PREPARATION
    # ==============================================================================

    def _compute_document_hash(self, pdf_path: str) -> str:
        """
        Computes a stable SHA-256 content hash of the PDF file. Content hashing
        (instead of basename matching) guarantees that two different documents
        sharing the same filename never collide in the workspace cache.
        """
        sha256 = hashlib.sha256()
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _document_cache_dir(self, document_hash: Optional[str] = None) -> str:
        """
        Resolves the per-document cache directory under the application data
        folder (e.g. %LOCALAPPDATA%/RockTranslate/cache/<sha256>/).
        """
        active_hash = document_hash or self._document_hash or "unknown"
        return str(config_db.get_cache_dir() / active_hash)

    def _load_cached_preparation(self) -> Optional[Tuple[str, Dict[str, str], Dict[str, int]]]:
        """
        Loads a previously prepared workspace (instrumented HTML + segment maps)
        from the hash-keyed cache. Returns None when the cache is incomplete.
        """
        try:
            cache_dir = self._document_cache_dir()
            workspace_html_path = os.path.join(cache_dir, "workspace.html")
            maps_path = os.path.join(cache_dir, "maps.json")

            if not (os.path.exists(workspace_html_path)
                    and os.path.getsize(workspace_html_path) > 0
                    and os.path.exists(maps_path)):
                return None

            with open(maps_path, "r", encoding="utf-8") as f:
                maps = json.load(f)
            if maps.get("pipeline_version") != PIPELINE_VERSION:
                logger.info("Cached workspace built by an older pipeline: it will be re-instrumented.")
                return None
            original_texts = maps.get("original_texts", {})
            tid_to_page = maps.get("tid_to_page", {})
            if not original_texts or not tid_to_page:
                return None
            # Self-healing: segments must be consistent with the document's own
            # raw text (a preparation saved under the wrong document, or an
            # interrupted one, had a handful of segments for dozens of lines).
            raw_lines = maps.get("raw_text_lines")
            if raw_lines is None:
                raw_lines = 0
                for name in os.listdir(cache_dir):
                    if name.endswith("_raw.html"):
                        with open(os.path.join(cache_dir, name), encoding="utf-8", errors="ignore") as f:
                            raw_lines += f.read().count('class="t ')
            if raw_lines >= 20 and len(original_texts) < 0.25 * raw_lines and len(original_texts) < 10:
                logger.warning(f"Cached workspace inconsistent ({len(original_texts)} segments for "
                               f"{raw_lines} text lines): it will be rebuilt.")
                return None

            return workspace_html_path, original_texts, tid_to_page
        except (OSError, ValueError) as e:
            logger.warning(f"Workspace cache unreadable, ignoring: {e}")
            return None

    def _save_preparation_cache(
        self,
        workspace_html_path: str,
        original_texts: Dict[str, str],
        tid_to_page: Dict[str, int],
        cache_dir: Optional[str] = None,
        raw_text_lines: Optional[int] = None,
    ) -> None:
        """
        Persists the segment maps alongside the instrumented workspace HTML so
        the next open of the same document skips pdf2htmlEX entirely.
        """
        try:
            cache_dir = cache_dir or self._document_cache_dir()
            os.makedirs(cache_dir, exist_ok=True)
            maps_path = os.path.join(cache_dir, "maps.json")
            tmp_path = maps_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({
                    "pipeline_version": PIPELINE_VERSION,
                    "original_texts": original_texts,
                    "tid_to_page": tid_to_page,
                    "raw_text_lines": raw_text_lines,
                }, f, ensure_ascii=False)
            os.replace(tmp_path, maps_path)
        except OSError as e:
            logger.warning(f"Could not persist workspace cache maps: {e}")

    def _prepare_document_for_translation(self, cancelled: Optional[Any] = None) -> bool:
        """
        Serialized entry point: the background preparation started at opening
        and a translation run never convert the same document twice; a run
        that arrives during the background preparation simply waits for it.
        """
        lock = self.__dict__.setdefault("_prep_lock", threading.Lock())
        with lock:
            if self._is_prepared:
                return True
            return self._prepare_document_impl(cancelled)

    def _prepare_in_background(self, pdf_path: str) -> None:
        """Layout preparation started right after opening (no LLM, no cost)."""
        self._prep_background = True
        try:
            ok = self._prepare_document_for_translation(cancelled=lambda: self._active_pdf_path != pdf_path)
        except Exception as e:
            logger.error(f"Background layout preparation failed: {e}")
            ok = False
        finally:
            self._prep_background = False
        self._send_js(f"window.dispatchEvent(new CustomEvent('workspace-prep-done', {{ detail: {{ ok: {json.dumps(bool(ok))} }} }}))")

    def _prep_event(self, name: str, detail: str = "") -> str:
        bg = "true" if getattr(self, "_prep_background", False) else "false"
        extra = f", {detail}" if detail else ""
        return f"window.dispatchEvent(new CustomEvent('{name}', {{ detail: {{ background: {bg}{extra} }} }}))"

    def _prepare_document_impl(self, cancelled: Optional[Any] = None) -> bool:
        """
        Runs the deferred heavy pipeline (pdf2htmlEX conversion + BeautifulSoup
        instrumentation) for the active document. Called from the translation
        worker thread so the UI never freezes; progress is streamed to the
        status bar during the conversion.

        Returns:
            bool: True when the workspace is ready for translation.
        """
        if self._is_prepared:
            return True

        pdf_path = self._active_pdf_path
        if not pdf_path or not os.path.exists(pdf_path):
            self._send_toast_i18n("toast_extraction_failed", "error")
            return False

        # Check for custom system overrides, falling back to default directories
        assets_dir = str(config_db.get("SystemConfig", "pdf2htmlex_path_override", "") or "").strip()
        if not assets_dir or not os.path.exists(assets_dir):
            assets_dir = DEFAULT_ASSETS_DIR

        cache_dir = self._document_cache_dir()

        # Announce the preparation phase so the right-pane overlay switches to
        # live progress mode (the UI shows the placeholder in lazy mode).
        self._send_js(self._prep_event('workspace-prep-start'))

        # Thread-safe progress report callback for pdf2htmlEX compilation
        def on_pdf_progress(current: int, total: int):
            self._send_status_i18n("status_extraction_pages", {"current": current, "total": total})
            self._send_js(self._prep_event('workspace-prep-progress', f"current: {current}, total: {total}"))

        self._send_status_i18n("status_extraction_start")
        prepared_for = os.path.abspath(pdf_path)
        # A conversion that stalls (no output, no CPU) is retried automatically:
        # observed hangs on large PDFs succeed on a fresh attempt.
        stop = cancelled or (lambda: self._stop_translation)
        raw_html_path = None
        for attempt in range(1, 4):
            raw_html_path = convert_pdf_to_html(
                pdf_path, assets_dir, on_progress=on_pdf_progress,
                output_dir=cache_dir, check_cancelled=stop,
                user_password=self._pdf_passwords.get(os.path.abspath(pdf_path)),
            )
            if raw_html_path or stop() or "stalled" not in (LAST_CONVERSION_ERROR.get("message") or ""):
                break
            logger.warning(f"pdf2htmlEX stalled: automatic retry {attempt + 1}/3...")
            self._send_status_i18n("status_conversion_retry", {"attempt": attempt + 1, "max": 3})

        # Cancellation requested while converting: exit gracefully
        if (cancelled or (lambda: self._stop_translation))():
            logger.info("Layout preparation cancelled by the user.")
            self._send_status_i18n("status_trans_cancelled")
            return False

        if not raw_html_path or not os.path.exists(raw_html_path):
            reason = LAST_CONVERSION_ERROR.get("message") or ""
            self._send_status_i18n("status_extraction_failed")
            self._send_toast_i18n("toast_conversion_failed_reason", "error", duration=12000,
                                  variables={"reason": reason or "pdf2htmlEX"})
            return False

        self._send_status_i18n("status_extraction_instrumenting")
        self._send_js(self._prep_event('workspace-prep-analysing'))
        logger.info("Executing BeautifulSoup semantic tag compilation...")

        workspace_html_path = os.path.join(cache_dir, "workspace.html")
        try:
            original_texts_map, tid_to_page = instrument_html(raw_html_path, workspace_html_path)
        except Exception as error:
            logger.error(f"Instrumentation failed during lazy preparation: {error}")
            self._send_status_i18n("status_extraction_error", {"error": str(error)})
            self._send_toast_i18n("toast_extraction_error", "error", variables={"error": str(error)})
            return False

        # The user may have opened another document meanwhile: this result
        # belongs to `prepared_for` only (cached under ITS folder, never
        # applied to the now-active document).
        try:
            with open(raw_html_path, encoding="utf-8", errors="ignore") as f:
                raw_lines = f.read().count('class="t ')
        except OSError:
            raw_lines = None
        self._save_preparation_cache(workspace_html_path, original_texts_map, tid_to_page,
                                     cache_dir=cache_dir, raw_text_lines=raw_lines)
        if not self._active_pdf_path or os.path.abspath(self._active_pdf_path) != prepared_for:
            logger.info("Document changed during preparation: result cached, not applied.")
            return False

        self._active_html_path = workspace_html_path
        self._original_texts = original_texts_map
        self._tid_to_page = tid_to_page
        self._is_prepared = True
        self._metadata_total_pages = max(tid_to_page.values()) + 1 if tid_to_page else self._metadata_total_pages

        config_db.set("RecentFiles", "active_total_pages", self._metadata_total_pages)

        # Serve the freshly prepared workspace to the right pane
        self._send_js(
            f"window.dispatchEvent(new CustomEvent('workspace-html-ready', {{ "
            f"detail: {{ htmlPath: {json.dumps(workspace_html_path)} }} "
            f"}}))"
        )
        self._send_status_i18n("status_extraction_success")
        logger.info(f"Lazy preparation completed: {len(original_texts_map)} segments mapped.")
        return True


    # ==============================================================================
    # 2. ASYNCHRONOUS TRANSLATION WORKER
    # ==============================================================================

    def start_full_translation(self) -> None:
        """
        Initiates a translation workflow spanning all pages of the document.
        """
        self.start_range_translation(None)

    @property
    def _stop_translation(self) -> bool:
        """Backward-compatible view of the CURRENT run's cancellation flag."""
        return self._cancel_event.is_set()

    def start_range_translation(self, range_str: Optional[str]) -> None:
        """
        Validates the requested page range and starts ONE translation run.

        Concurrency model: the run lock is acquired here and released by the
        worker thread when it exits, so two runs can never overlap. Every run
        owns its own cancellation Event: stopping run N can never be undone by
        starting run N+1 (the old shared boolean allowed a cancelled thread to
        silently resume when the flag was reset).

        Args:
            range_str: Custom page range input parsed from UI dialogues (e.g., '1-3, 5').
        """
        if not self._active_pdf_path:
            self._send_toast("No document is currently open.", "warning")
            return

        total_pages = self.get_total_pages()
        target_pages: Optional[List[int]] = None
        if range_str:
            target_pages = self._parse_page_range(range_str, max(total_pages, 1))
            if not target_pages:
                self._send_toast_i18n("enter_valid_page_range", "warning")
                return

        if not self._thread_lock.acquire(blocking=False):
            self._send_toast_i18n("status_trans_is_running", "warning")
            return

        try:
            cancel_event = threading.Event()
            self._cancel_event = cancel_event
            self._trans_thread = threading.Thread(
                target=self._run_translation,
                args=(target_pages, cancel_event),
                name="rocktranslate-run",
                daemon=True,
            )
            self._trans_thread.start()
        except Exception:
            self._thread_lock.release()
            raise

    def stop_translation(self, quiet: bool = False) -> None:
        """
        Cancels the active run. The worker abandons in-flight requests and
        exits within a fraction of a second; late API answers are discarded.

        Args:
            quiet: If True, halts the thread without overwriting the status bar message.
        """
        self._cancel_event.set()
        if self._trans_thread and self._trans_thread.is_alive():
            self._trans_thread.join(timeout=3.0)
        if not quiet:
            self._send_status_i18n("status_trans_cancelled")

    def reset_all_translations(self) -> None:
        """Wipes all active translation caches and resets state trackers."""
        self.stop_translation(quiet=True)
        self._current_translating_page = -1
        self.reset_translation_range(None)
        self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")

    def _resolve_llm_client(self) -> Optional[LLMClient]:
        """Builds the LLM client from the saved provider settings (None if no key)."""
        provider = config_db.get("APIConfig", "provider", "Google Gemini")
        keys_dict = config_db.get("APIConfig", "api_keys_by_provider", {})
        if isinstance(keys_dict, str):
            try:
                keys_dict = json.loads(keys_dict)
            except Exception:
                keys_dict = {}
        config = DEFAULT_PROVIDERS.get(provider) or next(iter(DEFAULT_PROVIDERS.values()))
        active_key = keys_dict.get(provider, "") or os.getenv(config.get("key_env", "") or "", "")

        active_model = config_db.get("APIConfig", f"last_model_{provider}", config["models"][0])
        prefix = config.get("prefix", "")
        llm_model_name = active_model
        if prefix and isinstance(prefix, str) and not llm_model_name.startswith(prefix):
            llm_model_name = f"{prefix}{llm_model_name}"

        use_custom_base = config_db.get("APIConfig", "use_custom_base", False)
        active_base_url = config_db.get("APIConfig", "custom_base_url", "") if use_custom_base else None

        if provider != "Ollama (Local)" and not active_key:
            self._send_toast_i18n("toast_trans_missing_key", "error", duration=8000, variables={"provider": provider})
            self._send_js("window.dispatchEvent(new CustomEvent('trigger-show-api-config'))")
            return None

        return LLMClient(
            model=llm_model_name,
            api_key=active_key,
            target_lang=config_db.get("SystemConfig", "target_lang", "French"),
            custom_base_url=active_base_url,
            all_keys=keys_dict,
            custom_glossary=config_db.get("TranslationConfig", "custom_glossary", ""),
            on_status=lambda msg, key=None, variables=None: (
                self._send_status_i18n(key, variables) if key else self._send_status(msg)),
        )

    def _run_translation(self, target_pages: Optional[List[int]], cancel_event: threading.Event) -> None:
        """
        Worker thread of one run: lazy layout preparation, batching, concurrent
        LLM requests, ordered UI streaming and on-disk persistence.
        The run lock (acquired by start_range_translation) is released on exit.
        """
        cancelled = cancel_event.is_set
        prepared_pages: Set[int] = set()
        run_started = time.monotonic()
        client: Optional[LLMClient] = None
        run_segments = 0
        try:
            self._current_translating_page = -1
            self._send_status_i18n("status_trans_init")

            client = self._resolve_llm_client()
            if client is None:
                return

            # ── LAZY LAYOUT PREPARATION ──
            if not self._is_prepared:
                if not self._prepare_document_for_translation(cancelled):
                    return
            if cancelled():
                return

            # Persisted translations of a previous session are restored first
            self._load_persisted_translations(client.model, client.target_lang)

            already_translated_ids: Set[str] = set()
            for page_data in self._translated_pages.values():
                already_translated_ids.update(page_data.keys())
            untranslated_texts = {
                k: v for k, v in self._original_texts.items()
                if k not in already_translated_ids
                and (target_pages is None or self._tid_to_page.get(k, 0) in target_pages)
            }
            total_pages = self.get_total_pages()

            if not untranslated_texts:
                self._send_status_i18n("status_trans_completed")
                return

            if target_pages is not None:
                unselected_pages = [p for p in range(total_pages) if p not in target_pages]
                if unselected_pages:
                    self._send_js(f"window.dispatchEvent(new CustomEvent('hide-glass-overlays', {{ detail: {{ pages: {unselected_pages} }} }}))")

            self._send_status_i18n("status_trans_building_batches")
            batches = build_batches(untranslated_texts, client.model)
            total_batches = len(batches)

            self._send_js(f"window.dispatchEvent(new CustomEvent('trigger-translation-start', {{ detail: {{ totalSegments: {len(untranslated_texts)}, totalPages: {total_pages}, targetPages: {json.dumps(target_pages)} }} }}))")
            self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-batches', {{ detail: {{ done: 0, total: {total_batches} }} }}))")
            already_count = sum(len(p) for p in self._translated_pages.values())
            if already_count > 0:
                self._send_js(f"window.dispatchEvent(new CustomEvent('set-progress-segments', {{ detail: {{ done: {already_count} }} }}))")

            # ── BYPASSED SEGMENTS (numbers, citations, formulas) ──
            translatable_ids: Set[str] = set()
            for batch in batches:
                translatable_ids.update(batch.ids)
            bypassed = {k: v for k, v in untranslated_texts.items() if k not in translatable_ids}
            # Pages with nothing to send to the LLM are complete right away
            pages_with_work = {self._tid_to_page.get(i, 0) for i in translatable_ids}
            # Untranslatable segments keep their original rendering: an empty
            # translation marks them done without touching the DOM.
            bypassed = {k: "" for k in bypassed}
            immediate = {k: v for k, v in bypassed.items() if self._tid_to_page.get(k, 0) not in pages_with_work}
            if immediate:
                self._commit_translations(immediate)
            pending_bypass = {k: v for k, v in bypassed.items() if k not in immediate}

            if not batches:
                self._persist_translations(client.model, client.target_lang)
                self._send_status_i18n("status_trans_completed")
                return

            # Source-text sliding context: known upfront, so batches are independent
            context_size = int(config_db.get("TranslationConfig", "sliding_context_size", 5))
            ordered_ids = list(self._original_texts.keys())
            position = {seg_id: i for i, seg_id in enumerate(ordered_ids)}
            contexts: List[Optional[str]] = []
            for batch in batches:
                first_pos = position.get(batch.ids[0], 0)
                window = [
                    self._original_texts[ordered_ids[i]]
                    for i in range(max(0, first_pos - context_size * 3), first_pos)
                    if should_translate(self._original_texts[ordered_ids[i]])
                ][-context_size:]
                contexts.append("\n".join(window) if window else None)

            parallel = max(1, int(config_db.get("TranslationConfig", "parallel_requests", DEFAULT_PARALLEL_REQUESTS)))
            executor = ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="rocktranslate-llm")
            in_flight: Dict[Any, int] = {}
            next_batch = 0
            done_batches = 0
            failed_batches = 0

            def submit_next() -> None:
                nonlocal next_batch
                idx = next_batch
                next_batch += 1
                batch = batches[idx]
                for page in sorted({self._tid_to_page.get(i, 0) for i in batch.ids}):
                    if page not in prepared_pages:
                        prepared_pages.add(page)
                        self._send_js(f"window.dispatchEvent(new CustomEvent('prepare-page', {{ detail: {{ page: {page} }} }}))")
                future = executor.submit(client.translate_batch, batch.segments, contexts[idx], cancelled)
                in_flight[future] = idx

            try:
                while next_batch < total_batches and len(in_flight) < parallel:
                    submit_next()

                while in_flight:
                    if cancelled():
                        break
                    finished, _ = wait(list(in_flight.keys()), timeout=0.25, return_when=FIRST_COMPLETED)
                    for future in finished:
                        idx = in_flight.pop(future)
                        try:
                            results = future.result()
                        except Exception as e:
                            logger.error(f"Batch {idx + 1} crashed: {e}")
                            results = None
                        if cancelled():
                            break
                        done_batches += 1
                        if results:
                            run_segments += len(results)
                            items = {r["id"]: r["translated"] for r in results}
                            # Bypassed segments of the same pages land together with them
                            pages = {self._tid_to_page.get(i, 0) for i in items}
                            for skip_id, skip_text in list(pending_bypass.items()):
                                if self._tid_to_page.get(skip_id, 0) in pages:
                                    items[skip_id] = skip_text
                                    del pending_bypass[skip_id]
                            self._commit_translations(items)
                            self._persist_translations(client.model, client.target_lang)
                        else:
                            failed_batches += 1
                        first_page = self._tid_to_page.get(batches[idx].ids[0], 0)
                        self._current_translating_page = first_page
                        self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-page', {{ detail: {{ page: {first_page + 1} }} }}))")
                        self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-batches', {{ detail: {{ done: {done_batches}, total: {total_batches} }} }}))")
                        self._send_status_i18n("status_trans_batch_progress", {"current": done_batches, "total": total_batches})
                        self._send_usage_update(client, run_started, done_batches, total_batches, run_segments)
                        if next_batch < total_batches and not cancelled():
                            submit_next()
            finally:
                # Never wait for abandoned HTTP calls: their late results are ignored
                executor.shutdown(wait=False, cancel_futures=True)

            logger.info(
                f"Run finished: {done_batches}/{total_batches} batches, {failed_batches} failed | "
                f"usage: {client.usage['prompt_tokens']} in / {client.usage['completion_tokens']} out tokens, "
                f"~${client.usage['cost_usd']:.4f}"
            )

            if cancelled():
                self._send_status_i18n("reset_success_msg")
                return

            if failed_batches:
                self._send_toast_i18n("toast_api_connection_error", "error", duration=8000)
                return

            self._send_status("Document translation completed successfully.")
            self._send_toast_i18n("toast_trans_success", "success")

        except Exception as error:
            logger.exception(f"Critical exception raised during background translation: {error}")
            self._send_status_i18n("status_trans_error", {"error": str(error)})
            self._send_toast_i18n("toast_trans_error", "error", duration=8000, variables={"error": str(error)})

        finally:
            # Usage accounting (tokens, cost, time) + end-of-run summary for the UI
            if client is not None and getattr(client, "usage", {}).get("requests", 0) > 0:
                try:
                    elapsed = time.monotonic() - run_started
                    last = record_run_usage(client.model, client.usage, elapsed, run_segments)
                    last["cancelled"] = bool(cancel_event.is_set())
                    self._send_js(
                        "window.dispatchEvent(new CustomEvent('translation-summary', "
                        f"{{ detail: {json.dumps(last)} }}))"
                    )
                except Exception as e:
                    logger.warning(f"Usage accounting failed: {e}")
            # Pages that were opened for translation but received nothing go back
            # to the waiting overlay; partially translated pages keep their text.
            for page in prepared_pages:
                if not self._translated_pages.get(page):
                    self._send_js(f"window.dispatchEvent(new CustomEvent('reset-page', {{ detail: {{ page: {page} }} }}))")
            self._current_translating_page = -1
            self._thread_lock.release()
            # Single, guaranteed completion signal for the frontend run state
            self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")

    def _send_usage_update(self, client: Any, run_started: float, done: int, total: int, segments: int) -> None:
        """Live run statistics: elapsed time, ETA, tokens and estimated cost."""
        elapsed = time.monotonic() - run_started
        eta = (elapsed / done) * (total - done) if done else None
        usage = getattr(client, "usage", {}) or {}
        detail = {
            "elapsed": round(elapsed, 1),
            "eta": round(eta, 1) if eta is not None else None,
            "promptTokens": int(usage.get("prompt_tokens", 0)),
            "completionTokens": int(usage.get("completion_tokens", 0)),
            "costUsd": round(float(usage.get("cost_usd", 0.0)), 5),
            "requests": int(usage.get("requests", 0)),
            "batchesDone": done,
            "batchesTotal": total,
            "segments": segments,
            "model": getattr(client, "model", ""),
        }
        self._send_js(f"window.dispatchEvent(new CustomEvent('update-usage', {{ detail: {json.dumps(detail)} }}))")

    def _commit_translations(self, items: Dict[str, str]) -> None:
        """Stores translations page by page and streams them to the UI in ONE call."""
        if not items:
            return
        for seg_id, text in items.items():
            p_idx = self._tid_to_page.get(seg_id, 0)
            self._translated_pages.setdefault(p_idx, {})[seg_id] = text
        payload = [{"id": k, "text": v} for k, v in items.items()]
        self._send_js(
            "window.dispatchEvent(new CustomEvent('stream-translations', "
            f"{{ detail: {{ items: {json.dumps(payload, ensure_ascii=False)} }} }}))"
        )

    def _send_translation_stream(self, trans_id: str, text: str):
        """Backward-compatible single-segment stream (prefer _commit_translations)."""
        self._commit_translations({trans_id: text})

    # ── PERSISTENCE OF TRANSLATIONS (survive app restarts) ──

    def _translations_file(self, model: str, target_lang: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{target_lang}__{model}")
        return os.path.join(self._document_cache_dir(), f"translations.{safe}.json")

    def _persist_translations(self, model: str, target_lang: str) -> None:
        try:
            path = self._translations_file(model, target_lang)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Source text is stored with each translation: entries stay valid across
            # app updates as long as the segment's source text is unchanged.
            flat = {
                seg_id: {"s": self._original_texts.get(seg_id, ""), "t": text}
                for page in self._translated_pages.values() for seg_id, text in page.items()
            }
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"format": 2, "translations": flat}, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            logger.warning(f"Could not persist translations: {e}")

    def _load_persisted_translations(self, model: str, target_lang: str) -> int:
        """Merges translations saved by a previous session (same language + model)."""
        try:
            path = self._translations_file(model, target_lang)
            if not os.path.exists(path):
                return 0
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("format") != 2:
                return 0
            restored = {
                k: v["t"] for k, v in data.get("translations", {}).items()
                if k in self._original_texts
                and v.get("s") == self._original_texts[k]
                and should_translate(self._original_texts[k])
                and k not in self._translated_pages.get(self._tid_to_page.get(k, 0), {})
            }
            if restored:
                self._commit_translations(restored)
                logger.info(f"Restored {len(restored)} translated segments from a previous session.")
            return len(restored)
        except (OSError, ValueError) as e:
            logger.warning(f"Could not load persisted translations: {e}")
            return 0

    def get_session_translations(self) -> Dict[str, Any]:
        """
        Exposed to the UI: all translations known for the active document, so a
        (re)loaded workspace iframe can restore them instantly.
        """
        flat = {seg_id: text for page in self._translated_pages.values() for seg_id, text in page.items()}
        return {"pages": sorted(self._translated_pages.keys()), "items": flat}


    def is_range_translated(self, range_str: Optional[str]) -> bool:
        """
        Checks if any of the target pages in the range (or the entire document
        if range_str is None) have already been translated in the active session.
        """
        if not self._translated_pages:
            return False

        total_pages = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1
        
        if range_str:
            target_pages = self._parse_page_range(range_str, total_pages)
        else:
            target_pages = list(range(total_pages))

        for p_idx in target_pages:
            if p_idx in self._translated_pages and self._translated_pages[p_idx]:
                return True

        return False

    def reset_translation_range(self, range_str: Optional[str]) -> None:
        """
        Clears translation caches for the target range (or the entire document
        if range_str is None) and triggers selective DOM restoration in JS.
        """
        total_pages = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1
        
        if range_str:
            target_pages = self._parse_page_range(range_str, total_pages)
        else:
            target_pages = list(range(total_pages))

        for p_idx in target_pages:
            if p_idx in self._translated_pages:
                del self._translated_pages[p_idx]

        # Trigger DOM restoration on the frontend specifically for these pages
        self._send_js(
            f"window.dispatchEvent(new CustomEvent('trigger-translation-reset', "
            f"{{ detail: {{ pages: {target_pages} }} }}))"
        )
        self._send_status_i18n("status_trans_reset")



    def _parse_page_range(self, range_str: str, max_pages: int) -> List[int]:
        """
        Parses page ranges using commas, hyphens, and integer values.
        """
        pages = set()
        parts = range_str.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                sub_parts = part.split('-')
                if len(sub_parts) == 2:
                    try:
                        start_val = int(sub_parts[0].strip())
                        end_val = int(sub_parts[1].strip())
                        # Clamp partially out-of-bounds ranges ("1-50" on 30 pages -> 1-30)
                        min_val = max(1, min(start_val, end_val))
                        max_val = min(max_pages, max(start_val, end_val))
                        for p in range(min_val, max_val + 1):
                            pages.add(p - 1)
                    except ValueError:
                        continue
            else:
                try:
                    p = int(part)
                    if 1 <= p <= max_pages:
                        pages.add(p - 1)
                except ValueError:
                    continue
        return sorted(list(pages))

    # ── HELPER COMMUNICATION METHODS ──
    def _send_status(self, text: str):
        self._send_js(f"window.showStatusMessage({json.dumps(text)})")

    def _send_toast(self, message: str, type_str: str = "info", duration: int = 5000):
        """
        Sends standard toast notifications.
        """
        self._send_js(f"window.showToast({json.dumps(message)}, '{type_str}', {duration})")

    def _send_js(self, js_code: str):
        """
        Sends a JavaScript command to the frontend.
        Gracefully ignores errors if the window is closing or already destroyed.
        """
        if not getattr(self, "_ui_ready", True):
            return
        if hasattr(self, "_window") and self._window:
            try:
                self._window.evaluate_js(js_code)
            except Exception:
                # The window might be in the process of closing or already destroyed
                pass
    
    def _send_status_i18n(self, key: str, variables: Optional[dict] = None) -> None:
        self._send_js(f"window.showStatusMessage_i18n('{key}', {json.dumps(variables or {})})")

    def _send_toast_i18n(self, key: str, type_str: str = "info", duration: int = 5000, variables: Optional[dict] = None) -> None:
        self._send_js(f"window.showToast_i18n('{key}', '{type_str}', {duration}, {json.dumps(variables or {})})")

    def _add_to_recent_files(self, file_path: str):
        """
        Registers opened files to history.
        """
        try:
            recent_list = config_db.get("RecentFiles", "recent_list", [])
            if not isinstance(recent_list, list):
                recent_list = []

            abs_path = os.path.normpath(os.path.abspath(file_path))
            norm_target = os.path.normcase(abs_path)

            recent_list = [
                p for p in recent_list
                if os.path.normcase(os.path.normpath(p)) != norm_target
            ]

            recent_list.insert(0, abs_path)
            recent_list = recent_list[:20]

            config_db.set("RecentFiles", "recent_list", recent_list)
            self._send_js("window.dispatchEvent(new CustomEvent('refresh-menu-data'))")
        except Exception as e:
            logger.info(f" Error updating history registry: {e}")
    
    def get_total_pages(self) -> int:
        """
        Returns the total number of pages in the currently active document.
        Exposed to the frontend range settings controller.
        """
        if hasattr(self, "_tid_to_page") and self._tid_to_page:
            return max(self._tid_to_page.values()) + 1
        return max(getattr(self, "_metadata_total_pages", 0), 1)


    # ==============================================================================
    # 3. EXPOSED PDF EXPORT ENDPOINT
    # ==============================================================================

    def open_translated_in_browser(self) -> None:
        """
        Opens the translated document in the user's default browser with its
        print dialog ("Save as PDF"): the browser's own, warm print pipeline,
        an alternative to the headless export.
        """
        if not self._active_html_path or not os.path.exists(self._active_html_path):
            self._send_toast_i18n("toast_export_failed_extract", "error")
            return
        try:
            import webbrowser
            from pathlib import Path
            translations = {seg_id: text for page in self._translated_pages.values() for seg_id, text in page.items()}
            out = os.path.join(os.path.dirname(os.path.abspath(self._active_html_path)), "rocktranslate-print.html")
            apply_translations_offline(self._active_html_path, out, translations)
            with open(out, "r", encoding="utf-8") as f:
                html = f.read()
            # Print dialog once fonts are loaded and paragraphs laid out again
            hook = ("<script>window.addEventListener('load',function(){var go=function(){"
                    "setTimeout(function(){window.print();},700);};"
                    "if(document.fonts&&document.fonts.ready){document.fonts.ready.then(go);}else{go();}});</script>")
            idx = html.rfind("</body>")
            html = html[:idx] + hook + html[idx:] if idx != -1 else html + hook
            with open(out, "w", encoding="utf-8") as f:
                f.write(html)
            webbrowser.open(Path(out).as_uri())
            self._send_toast_i18n("toast_opened_in_browser", "info", duration=7000)
        except Exception as e:
            logger.error(f"Could not open the translated document in the browser: {e}")
            self._send_toast_i18n("toast_export_error", "error", variables={"error": str(e)})

    def export_translated_pdf(self) -> None:
        """
        Builds the translated document from the backend state (workspace HTML +
        translation cache) and prints it to a vector PDF. Nothing is pulled back
        from the webview: a 40-page workspace weighs tens of MB of embedded fonts.
        """
        if not self._active_pdf_path or not self._window:
            self._send_toast_i18n("toast_export_no_doc", "warning")
            return
        if not self._active_html_path or not os.path.exists(self._active_html_path):
            self._send_toast_i18n("toast_export_failed_extract", "error")
            return

        original_name = os.path.basename(self._active_pdf_path)
        base_name, _ = os.path.splitext(original_name)
        suggested_name = f"{base_name}_translated.pdf"

        self._send_status_i18n("status_export_waiting_path")
        destination_path = self._window.create_file_dialog(
            getattr(getattr(webview, 'FileDialog', None), 'SAVE', None) or webview.SAVE_DIALOG,
            allow_multiple=False,
            file_types=("PDF Documents (*.pdf)", "All files (*.*)"),
            save_filename=suggested_name,
        )
        if not destination_path:
            self._send_status_i18n("status_export_cancelled")
            return
        if isinstance(destination_path, (tuple, list)):
            if not destination_path:
                return
            destination_path = destination_path[0]

        self._send_status_i18n("status_export_generating_pdf")
        threading.Thread(
            target=self._export_worker, args=(destination_path,), name="rocktranslate-export", daemon=True
        ).start()

    def _export_worker(self, destination_path: str) -> None:
        temp_html_path = None
        self._send_js("window.dispatchEvent(new CustomEvent('app-busy', { detail: { on: true } }))")
        try:
            translations = {seg_id: text for page in self._translated_pages.values() for seg_id, text in page.items()}
            # Written next to the workspace: its page images are relative files
            fd, temp_html_path = tempfile.mkstemp(suffix=".html", prefix="rocktranslate-export-",
                                                  dir=os.path.dirname(os.path.abspath(self._active_html_path)))
            os.close(fd)
            apply_translations_offline(self._active_html_path, temp_html_path, translations)

            if print_html_with_fallback(temp_html_path, destination_path):
                self._send_status_i18n("status_export_success", {"filename": os.path.basename(destination_path)})
                self._send_toast_i18n("toast_export_success", "success", duration=6000)
            else:
                self._send_toast_i18n("toast_export_no_chromium", "error")
                self._send_status_i18n("status_export_failed")
        except Exception as e:
            logger.error(f"Error during PDF export pipeline: {e}")
            self._send_toast_i18n("toast_export_error", "error", variables={"error": str(e)})
        finally:
            self._send_js("window.dispatchEvent(new CustomEvent('app-busy', { detail: { on: false } }))")
            if temp_html_path:
                try:
                    os.unlink(temp_html_path)
                except OSError:
                    pass

    def _cleanup_workspace_files(self) -> None:
        """
        Physically deletes temporary html workspace and raw layout files
        if the clear_cache_on_exit user setting is set to True.
        """
        if config_db.get("SystemConfig", "clear_cache_on_exit", False):
            # 1. Delete the hash-keyed workspace cache folder of this document
            #    (prepared workspace + raw pdf2htmlEX output + segment maps)
            if self._document_hash:
                try:
                    cache_dir = self._document_cache_dir()
                    if os.path.isdir(cache_dir):
                        shutil.rmtree(cache_dir, ignore_errors=True)
                        logger.info(f"Cleaned up workspace cache directory: {cache_dir}")
                except OSError as e:
                    logger.warning(f"Could not delete workspace cache directory: {e}")

            # 2. Delete legacy workspace files written next to the PDF by
            #    previous versions of the application
            if self._active_html_path and os.path.exists(self._active_html_path):
                try:
                    os.remove(self._active_html_path)
                    logger.info(f"Cleaned up temporary workspace HTML: {self._active_html_path}")
                except OSError as e:
                    logger.warning(f"Could not delete temporary workspace file: {e}")

            # 3. Delete raw HTML compiled by pdf2htmlEX
            if self._active_pdf_path:
                pdf_dir = os.path.dirname(os.path.abspath(self._active_pdf_path))
                pdf_filename = os.path.basename(self._active_pdf_path)
                raw_html_path = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}_raw.html")
                if os.path.exists(raw_html_path):
                    try:
                        os.remove(raw_html_path)
                        logger.info(f"Cleaned up raw HTML layout file: {raw_html_path}")
                    except OSError as e:
                        logger.warning(f"Could not delete raw HTML file: {e}")


    def close_document(self) -> None:
        """
        Safely stops any active threads, purges temporary cache files
        if requested, and resets the document state registers.
        """
        self.stop_translation()
        self._cleanup_workspace_files()

        # Reset local document states
        self._active_pdf_path = None
        self._active_html_path = None
        self._original_texts = {}
        self._tid_to_page = {}
        self._translated_pages  = {}
        self._is_prepared = False
        self._metadata_total_pages = 0
        self._document_hash = None
        self._send_status_i18n("status_ready")