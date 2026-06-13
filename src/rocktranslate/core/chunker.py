"""
RockTranslate — Semantic Text Chunking and Token Budget Router
Path: src/rocktranslate/core/chunker.py

This module implements the document chunking pipeline:
1. Filters geometrical layout noise, citation pointers, and mathematical formulas.
2. Estimates token footprints dynamically (with dedicated CJK character weight ratios).
3. Batches structural paragraph nodes into size-controlled token payloads.

All token boundaries and batch counts are imported from core.constants.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Optional
from loguru import logger
try:
    from PyQt6.QtCore import QSettings
except ImportError:
    QSettings = None

# Safe imports supporting both standard package modules and direct scripts
from .constants import MODEL_TOKEN_LIMITS, DEFAULT_TOKEN_LIMIT, MAX_SEGMENTS_PER_BATCH

@dataclass
class Batch:
    """
    Represents a unified, size-constrained batch of text segments 
    packaged for a single concurrent LLM request.
    """
    segments: List[Dict[str, str]]  # List structure: [{"id": "g-0", "text": "..."}]
    estimated_tokens: int

    @property
    def ids(self) -> List[str]:
        """
        Extracts all target routing identifiers mapped inside this batch.

        Returns:
            List[str]: List of unique segment ID tags.
        """
        return [s["id"] for s in self.segments]


def should_translate(text: str) -> bool:
    """
    Evaluates if a text node should be skipped to avoid wasting API budgets.
    Bypasses structural page coordinates, citations, and isolated math glyphs.

    Args:
        text: Raw text string to analyze.

    Returns:
        bool: True if the segment is translatable prose, False if it is noise.
    """
    text = text.strip()
    if not text:
        return False

    # Skip isolated page numbers, section headers, or floating layout floats (e.g., '24', '0.58')
    if text.isdigit() or re.match(r'^[\d\s,\.\-\+]+$', text):
        return False

    # Skip pure floating citation brackets (e.g., '[12]', '(5)')
    if re.match(r'^\[\d+\]$', text) or re.match(r'^\(\d+\)$', text):
        return False

    # Bypass noisy non-alphabetic single characters, preserving meaningful letters (like 'a' or 'I')
    if len(text) == 1 and not text.isalpha():
        return False

    return True


def _estimate_tokens(text: str) -> int:
    """
    Runs a fast heuristic estimation of the token footprint of a text string.
    - Standard Latin prose: ~1 token per 4 characters.
    - CJK (Chinese, Japanese, Korean) prose: ~1 token per 1.5 characters.
    Applies a safety margin ratio of 1.3 to avoid rate limits.

    Args:
        text: The source string segment to evaluate.

    Returns:
        int: Estimated token count (minimum of 1).
    """
    if not text:
        return 0
        
    # Heuristic detection of CJK character sets
    cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cjk_chars > len(text) * 0.3:
        return int(len(text) / 1.5)
    
    # Apply standard multiplier with safety buffer margins
    return max(1, int(len(text) / 4 * 1.3))


def get_max_source_tokens(model: str) -> int:
    """
    Looks up contextual input token ceilings for a given model routing string.

    Args:
        model: Target model routing string.

    Returns:
        int: The model's token capacity ceiling.
    """
    return MODEL_TOKEN_LIMITS.get(model, DEFAULT_TOKEN_LIMIT)


def build_batches(
    segments: Dict[str, str],
    model: str = "gemini/gemini-2.5-flash-lite",
    max_tokens: Optional[int] = None,
) -> List[Batch]:
    """
    Aggregates semantic text segments into structured token-controlled batches.

    Ensures that individual chunks neither exceed the model's budget nor
    surpass the safe physical item count ceiling (MAX_SEGMENTS_PER_BATCH).

    Args:
        segments: Dictionary of active text nodes (ID to content).
        model: Target model used to check token limits.
        max_tokens: Optional override to force custom token limits.

    Returns:
        List[Batch]: Size-controlled batches queued for processing.
    """
    if not segments:
        return []

     # Safe fallback configuration if QSettings is unavailable [1]
    if QSettings is not None:
        try:
            translation_settings = QSettings("RockTranslate", "TranslationConfig")
            max_batch_size = translation_settings.value("max_segments_per_batch", 60, type=int)
        except Exception:
            max_batch_size = MAX_SEGMENTS_PER_BATCH
    else:
        max_batch_size = MAX_SEGMENTS_PER_BATCH  # Default safe chunk size for CLI execution [1]

    budget = max_tokens or get_max_source_tokens(model)
    batches: List[Batch] = []
    current_segments: List[Dict[str, str]] = []
    current_tokens: int = 0

    for text_id, text in segments.items():

        # systematic noise filtering before integration
        if not should_translate(text):
            continue

        tokens = _estimate_tokens(text)
        item = {"id": text_id, "text": text}

        # If a single dense block exceeds the overall budget, package it alone
        if tokens > budget:
            if current_segments:
                batches.append(Batch(segments=current_segments, estimated_tokens=current_tokens))
                current_segments, current_tokens = [], 0
            batches.append(Batch(segments=[item], estimated_tokens=tokens))
            continue

        # Accumulate within current batch boundaries
        if (current_tokens + tokens <= budget) and (len(current_segments) < max_batch_size):
            current_segments.append(item)
            current_tokens += tokens
        else:
            batches.append(Batch(segments=current_segments, estimated_tokens=current_tokens))
            current_segments = [item]
            current_tokens = tokens

    # Flush remaining segment nodes
    if current_segments:
        batches.append(Batch(segments=current_segments, estimated_tokens=current_tokens))

    return batches


def filter_noise(segments: Dict[str, str]) -> Dict[str, str]:
    """
    Filters non-translatable noise elements from a dictionary.

    Args:
        segments: Source dictionary mapping IDs to text.

    Returns:
        Dict[str, str]: Filtered dictionary containing only valid prose.
    """
    filtered = {text_id: text for text_id, text in segments.items() if should_translate(text)}
    logger.debug(f"Filtering pass complete: {len(segments)} -> {len(filtered)} prose segments retained.")
    return filtered


def batches_summary(batches: List[Batch]) -> str:
    """
    Generates a human-readable console execution plan summary for logging.

    Args:
        batches: Processed lists of batches.

    Returns:
        str: Summary table.
    """
    total_segments = sum(len(b.segments) for b in batches)
    total_tokens = sum(b.estimated_tokens for b in batches)
    
    summary_lines = [
        f"📋 Semantic chunking plan: {len(batches)} batch(es) | "
        f"{total_segments} segment(s) retained | ~{total_tokens:,} estimated tokens."
    ]
    for i, b in enumerate(batches):
        summary_lines.append(
            f"  -> Batch {i+1:02d} : {len(b.segments)} segment(s), ~{b.estimated_tokens:,} tokens"
        )
    return "\n".join(summary_lines)