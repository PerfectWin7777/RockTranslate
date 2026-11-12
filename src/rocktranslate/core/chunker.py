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

# Safe imports supporting both standard package modules and direct scripts
from .constants import MODEL_TOKEN_LIMITS, DEFAULT_TOKEN_LIMIT, MAX_SEGMENTS_PER_BATCH, DEFAULT_MODEL
from .config_manager import config_db

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


_MATH_OPERATOR_WORDS = frozenset(
    "max min sup inf lim log ln exp sin cos tan sinh cosh tanh arg argmax argmin det tr dim ker mod deg gcd var cov".split())


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

    # Math operator names cut out of an equation ("max" of k_max, "log", "exp"):
    # translated alone they became "maximum" squeezed into a subscript box.
    if text.lower() in _MATH_OPERATOR_WORDS:
        return False

    # Bypass noisy non-alphabetic single characters, preserving meaningful letters (like 'a' or 'I')
    if len(text) == 1 and not text.isalpha():
        return False

    # Formulas and symbol runs ("(i = 1, 2, ..., n)", "CI = (λmax − n)/(n − 1)"):
    # too few characters belong to real words (3+ letters). A model would only
    # reformat them (", " -> " ; " ...), never translate them.
    plain = re.sub(r"</?[a-z_0-9]+>", "", text)
    visible = re.sub(r"\s+", "", plain)
    if visible:
        wordy = sum(len(w) for w in re.findall(r"[^\W\d_]{3,}", plain))
        has_real_word = re.search(r"[^\W\d_]{5,}", plain) is not None
        if wordy / len(visible) < 0.3 and not has_real_word:
            return False

    return True



# ── BIBLIOGRAPHY DETECTION (optional "do not translate the references") ──
# Headings are matched with spaces removed: pdf2htmlEX often splits words of
# letter-spaced fonts ("Ref erences", "App endix").
_REF_WORDS = (r"(?:references?|bibliography|literaturecited|workscited|referencelist|références|bibliographie|"
              r"literatur(?:verzeichnis)?|referencias|bibliografía|riferimenti|bibliografia)")
_REFERENCES_HEADING_RE = re.compile(r"^(?:\d+|[ivx]+)?\.?" + _REF_WORDS + r":?$", re.I)
# Heading glued to the first entry: "References [1] J. Bear, ..."
_REFERENCES_GLUED_RE = re.compile(r"^(?:\d+\.?\s*)?(?:References?|Bibliography|Références|Bibliographie|Literatur)"
                                  r"\s*:?\s*\[1\]")
_AFTER_REFERENCES_RE = re.compile(r"^(?:[a-z]|\d+)?\.?(?:appendix|appendices|supplementary|annexes?|anhang|apéndice)",
                                  re.I)
_ENTRY_RE = re.compile(r"^\s*\[\d+\]")


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"</?[a-z_0-9]+[^>]*>", "", text or "")).strip()


def reference_segment_ids(ordered_texts: Dict[str, str],
                          tid_to_page: Optional[Dict[str, int]] = None) -> List[str]:
    """
    Ids of the segments that belong to the bibliography.

    The list starts at a "References"/"Bibliography" heading (alone, or glued
    to its first entry) and runs to an appendix heading or the end of the
    document. A standalone heading stays translated; a glued one goes with
    its entry.

    pdf2htmlEX does not always emit a page in reading order: the first entries
    of the start page can come BEFORE the heading. With tid_to_page, entries
    ("[n] ...") of that page that precede the heading are included too.

    Args:
        ordered_texts: segment id -> source text, in document (DOM) order.
        tid_to_page: segment id -> page index (optional, improves the start page).
    """
    ids = list(ordered_texts)
    page_of = (lambda i: tid_to_page.get(i, 0)) if tid_to_page else (lambda i: 0)
    start = None
    heading_alone = False
    for k, seg_id in enumerate(ids):
        plain = _plain(ordered_texts[seg_id])
        compact = re.sub(r"\s+", "", plain)
        if len(compact) <= 40 and _REFERENCES_HEADING_RE.match(compact):
            start, heading_alone = k, True
        elif _REFERENCES_GLUED_RE.match(plain):
            start, heading_alone = k, False
        if start is not None:
            break
    if start is None:
        return []

    refs: List[str] = []
    if tid_to_page:
        # Same page, before the heading in DOM order: from the first "[n]" entry on
        start_page = page_of(ids[start])
        same_page = [k for k in range(start) if page_of(ids[k]) == start_page]
        first_entry = next((k for k in same_page if _ENTRY_RE.match(_plain(ordered_texts[ids[k]]))), None)
        if first_entry is not None:
            refs.extend(ids[k] for k in same_page if k >= first_entry)

    for k in range(start + (1 if heading_alone else 0), len(ids)):
        compact = re.sub(r"\s+", "", _plain(ordered_texts[ids[k]]))
        if k > start and len(compact) <= 60 and _AFTER_REFERENCES_RE.match(compact):
            break
        refs.append(ids[k])
    return refs


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
    model: str = DEFAULT_MODEL,
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

    # Fetch chunk limitations directly from the JSON database
    max_batch_size = int(config_db.get("TranslationConfig", "max_segments_per_batch", MAX_SEGMENTS_PER_BATCH))

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