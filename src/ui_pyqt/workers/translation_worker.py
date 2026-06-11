"""
RockTranslate — Asynchronous Background Thread Translation Orchestrator
Path: ui_pyqt/workers/translation_worker.py

This module implements the background processing thread (QThread) responsible
for grouping text chunks into optimized batches, communicating with the LiteLLM
routing client, maintaining sliding contextual memories, and streaming translations
live to the UI as they arrive.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

from typing import Dict, List, Optional, Set
from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger
from PyQt6.QtCore import QSettings
# Safe fallback imports supporting both standard package modules and direct scripts
try:
    from translation.chunker import build_batches, Batch
    from translation.llm_client import LLMClient
except ImportError:
    from src.translation.chunker import build_batches, Batch
    from src.translation.llm_client import LLMClient


class TranslationWorker(QThread):
    """
    Asynchronous background thread managing the segmentation pipeline,
    AI API client initialization, and real-time segment streaming.
    """
    # UI status updates message signals
    status_update = pyqtSignal(str)
    
    # Batch execution progress increments (emits: batches_completed, total_batches)
    batch_progress = pyqtSignal(int, int)
    
    # Real-time translated segment updates (emits: target_segment_id, translated_text)
    segment_translated = pyqtSignal(str, str)
    
    # Successful translation completion triggers
    finished = pyqtSignal()
    
    # Critical translation thread exception triggers
    error = pyqtSignal(str)

    def __init__(
        self, 
        original_texts: Dict[str, str], 
        model: str, 
        api_key: str, 
        target_lang: str,  
        custom_base_url: Optional[str] = None,  
        all_keys: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Initializes the translation worker.

        Args:
            original_texts: Map of all document text nodes (ID to raw text).
            model: Target model routing string (e.g., 'gemini/gemini-2.5-flash-lite').
            api_key: API Key for the active provider.
            target_lang: Selected translation language name.
            custom_base_url: Optional custom target API gateway (e.g., local Ollama port).
            all_keys: Mapping of all configured provider API keys.
        """
        super().__init__()
        self.original_texts: Dict[str, str] = original_texts
        self.model: str = model
        self.api_key: str = api_key
        self.target_lang: str = target_lang
        self.custom_base_url: Optional[str] = custom_base_url
        self.all_keys: Dict[str, str] = all_keys or {}

        # Abort state markers
        self._stop: bool = False
        self.client: Optional[LLMClient] = None

    def run(self) -> None:
        """
        Main runner executing translation cycles. Groups texts, bypasses mathematical
        formulas instantly, and runs batch API requests.
        """
        try:
            self._stop = False
            self.status_update.emit(self.tr("Initializing AI Translator..."))

            # Prune sliding window to prevent token explosion bounds based on user preferences
            translation_settings = QSettings("RockTranslate", "TranslationConfig")
            context_size = translation_settings.value("sliding_context_size", 5, type=int)
            
            # Step A: Instantiate dynamic LiteLLM router wrapper
            self.client = LLMClient(
                model=self.model,
                api_key=self.api_key,
                target_lang=self.target_lang,
                custom_base_url=self.custom_base_url,
                all_keys=self.all_keys,
                on_status=lambda msg: self.status_update.emit(msg)
            )

            # Step B: Segment the raw dictionary nodes into optimized token buckets
            self.status_update.emit(self.tr("Building translation batches..."))
            batches: List[Batch] = build_batches(self.original_texts, self.model)
            total_batches: int = len(batches)
            
            if not batches:
                self.status_update.emit(self.tr("No text to translate was found."))
                self.finished.emit()
                return

            logger.info(f"Starting translation process: {total_batches} batches mapped.")
            
            # ── Step B.2: INSTANTLY BYPASS FORMULAS & NUMERICAL ARTIFACTS ──
            # Map all text node IDs targeted for API translation
            translatable_ids: Set[str] = set()
            for batch in batches:
                translatable_ids.update(batch.ids)
            
            # Unmapped IDs are geometrical bypasses (formulas, citation coordinates, isolated digits)
            skipped_ids: Set[str] = set(self.original_texts.keys()) - translatable_ids
            logger.debug(f"Direct bypass triggered: {len(skipped_ids)} segments skipped (formulas/digits).")
            
            # Immediately stream original values to clear shimmer loaders on bypassed spans
            for skipped_id in skipped_ids:
                orig_text: str = self.original_texts[skipped_id]
                logger.debug(f"Bypassed node displayed instantly: {skipped_id} -> '{orig_text}'")
                self.segment_translated.emit(skipped_id, orig_text)
            # ───────────────────────────────────────────────────────────────

            sliding_context: List[str] = []

            # Step C: Sequentially translate batch segments
            for idx, batch in enumerate(batches):
                # Safe abort check before initiating network request
                if self._stop:
                    logger.info("Translation process aborted by the user.")
                    self.status_update.emit(self.tr("Translation interrupted by the user."))
                    break

                self.batch_progress.emit(idx + 1, total_batches)
                self.status_update.emit(
                    self.tr("Translating batch {current}/{total}...").format(
                        current=idx + 1, total=total_batches
                    )
                )

                # Format localized sliding terminal context
                context_str: Optional[str] = "\n".join(sliding_context) if sliding_context else None

                # Perform actual API request
                results = self.client.translate_batch(batch.segments, context=context_str)

                # Safe abort check after returning network values
                if self._stop:
                    self.status_update.emit(self.tr("Translation interrupted by the user."))
                    break

                # If batch request fails, stream warning labels to prevent stuck shimmer lines
                # if results is None:
                #     for item in batch.segments:
                #         fail_text: str = self.tr("[FAILED] {text}").format(text=item["text"])
                #         self.segment_translated.emit(item["id"], fail_text)
                #     continue

                if results is None:
                    # clean user's message
                    fail_msg: str = self.tr(
                        "API Connection Error: All connection attempts failed.\n\n"
                        "Please verify:\n"
                        "1. Your internet connection and active VPN configurations.\n"
                        "2. That your target host is running (especially for local Ollama).\n"
                        "3. Your active API key limits."
                    )
                    self.error.emit(fail_msg)
                    return  # stop the task

                # Stream translation segments sequentially for live UI updating
                for item in results:
                    seg_id: Optional[str] = item.get("id")
                    translated_text: str = item.get("translated", "").strip()
                    
                    if seg_id and translated_text:
                        # Emits to MainWindow for asynchronous DOM updates
                        self.segment_translated.emit(seg_id, translated_text)
                        
                        # Store in localized sliding terminal memory
                        sliding_context.append(translated_text)

                # Prune sliding window to prevent token explosion bounds
                if len(sliding_context) > context_size:
                    sliding_context = sliding_context[-context_size:]

            self.status_update.emit(self.tr("Document translation completed successfully."))
            self.finished.emit()

        except Exception as e:
            logger.error(f"Critical exception raised during background translation execution: {e}")
            self.error.emit(str(e))

    def stop(self) -> None:
        """ Signals the worker thread to safely halt operations. """
        self._stop = True

    def is_stopped(self) -> bool:
        """
        Checks if the worker thread is marked for termination.

        Returns:
            bool: True if stop signal was sent, False otherwise.
        """
        return self._stop