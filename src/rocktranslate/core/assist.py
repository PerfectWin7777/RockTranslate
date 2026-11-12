"""
RockTranslate — Reading assistant (quick LLM actions)
Path: src/rocktranslate/core/assist.py

Short, interactive LLM calls used while READING a paper, shared by the
desktop app, the Python API and the CLI:

- translate_text / explain_text: a selection translated or explained, with
  streaming (the first words show up within a second on fast models);
- summarize_text: a section summarized in the reader's language;
- build_glossary: the key terms of a paper with one consistent translation,
  reusable as the translation glossary ("term -> translation" lines);
- ask_document: a question answered from the paper, with verbatim quotes and
  their page so the reader can jump to the exact passage.

Every function takes an LLMClient (model, key, base URL already resolved) and
records tokens and cost in client.usage like the batch translator does.

Author: RockTranslate Contributors
License: MIT License
"""

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .llm_client import LLMClient, litellm

Delta = Callable[[str], None]

# Whole-paper prompts stay far below the context of current models; longer
# documents are cut page by page (the question/summary still sees most of it).
MAX_DOCUMENT_CHARS = 400_000


# ── Text clean-up shared with "clean copy" ────────────────────────────────────

_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")


def clean_selection(text: str) -> str:
    """
    Text selected in a PDF, made readable: words cut by a line-end hyphen are
    joined ("trans-\\nlation" -> "translation"), single line breaks become
    spaces, blank lines (paragraph breaks) are kept, spaces are normalized.
    """
    text = (text or "").replace("\r", "")
    text = text.replace("­\n", "").replace("­", "")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in paragraphs]
    return "\n\n".join(p for p in paragraphs if p)


# ── LLM plumbing ──────────────────────────────────────────────────────────────

def _base_kwargs(client: LLMClient, messages: List[Dict[str, str]], max_tokens: int,
                 temperature: float) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"model": client.model, "messages": messages,
                              "temperature": temperature, "max_tokens": max_tokens, "timeout": 120}
    if client.api_key:
        kwargs["api_key"] = client.api_key
    if client.custom_base_url:
        kwargs["api_base"] = client.custom_base_url
    no_thinking = LLMClient._no_thinking_kwargs(client.model)
    if no_thinking and client.model not in LLMClient._thinking_flag_rejected:
        kwargs.update(no_thinking)
    return kwargs


def _completion(kwargs: Dict[str, Any]) -> Any:
    """litellm.completion, retried once without the no-thinking flag if refused."""
    try:
        return litellm.completion(**kwargs)
    except Exception as e:
        if "extra_body" in kwargs and "thinking" in str(e).lower():
            LLMClient._thinking_flag_rejected.add(kwargs["model"])
            kwargs = {k: v for k, v in kwargs.items() if k != "extra_body"}
            return litellm.completion(**kwargs)
        raise


def chat(client: LLMClient, system: str, user: str, on_delta: Optional[Delta] = None,
         max_tokens: int = 2048, temperature: float = 0.2) -> str:
    """
    One chat completion. With on_delta, the answer is streamed and on_delta
    receives each new piece of text as it arrives. Returns the full text.
    """
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    kwargs = _base_kwargs(client, messages, max_tokens, temperature)
    started = time.monotonic()
    if on_delta is None:
        response = _completion(kwargs)
        client._record_usage(response, client.model)
        return (response.choices[0].message.content or "").strip()

    kwargs["stream"] = True
    chunks: List[Any] = []
    parts: List[str] = []
    for chunk in _completion(kwargs):
        chunks.append(chunk)
        try:
            piece = chunk.choices[0].delta.content or ""
        except (AttributeError, IndexError):
            piece = ""
        if piece:
            parts.append(piece)
            on_delta(piece)
    # Usage and cost of a streamed answer: rebuilt from its chunks
    try:
        rebuilt = litellm.stream_chunk_builder(chunks, messages=messages)
        if rebuilt is not None:
            client._record_usage(rebuilt, client.model)
    except Exception as e:
        logger.debug(f"Streamed usage unavailable: {e}")
    logger.info(f"Assistant answer in {time.monotonic() - started:.1f}s ({client.model})")
    return "".join(parts).strip()


def _json_from(raw: str) -> Any:
    """Parses a JSON answer, tolerating code fences and small syntax slips."""
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    try:
        return json.loads(raw)
    except ValueError:
        from json_repair import repair_json
        return json.loads(repair_json(raw))


# ── Quick actions on a selection ──────────────────────────────────────────────

def translate_text(client: LLMClient, text: str, lang: Optional[str] = None,
                   on_delta: Optional[Delta] = None) -> str:
    """A passage translated into `lang` (default: the client's target language)."""
    lang = lang or client.target_lang
    system = (
        f"You translate passages of scientific papers into {lang}. The passage was copied from a PDF: "
        "lines may be broken in the middle of sentences and words may be cut by a line-end hyphen; "
        "rebuild the sentences before translating. Keep formulas, symbols, numbers, citations such as [12] "
        "or (Smith et al., 2020) and proper nouns exactly as they are. Use the established terminology of the "
        "field. Answer with the translation only: no quotes, no notes, no preamble."
    )
    glossary = (client.custom_glossary or "").strip()
    if glossary:
        system += f"\nMandatory terminology (source -> {lang}):\n{glossary}"
    return chat(client, system, clean_selection(text), on_delta=on_delta, max_tokens=4096, temperature=0.1)


def explain_text(client: LLMClient, text: str, lang: Optional[str] = None,
                 on_delta: Optional[Delta] = None, context: Optional[str] = None) -> str:
    """
    A passage explained in plain words in `lang`: what it says, the jargon it
    uses and, for a formula, what every symbol stands for.
    """
    lang = lang or client.target_lang
    system = (
        f"You help a researcher read a scientific paper. Explain the selected passage in {lang}, "
        "for a reader who is not a specialist of this exact topic: first what it says in one or two plain "
        "sentences, then the technical terms it relies on. If the passage is or contains a formula, explain "
        "what each symbol stands for and what the formula computes. Be precise and brief (at most about 180 "
        "words). Light Markdown: short paragraphs, '- ' bullets, **bold** for the key terms; math written inline "
        "with Unicode symbols; no headings, no LaTeX."
        f" Write the whole answer in {lang}, even though the passage is in another language."
    )
    user = clean_selection(text)
    if context:
        user = f"Paper: {context}\n\nSelected passage:\n{user}"
    # Repeated last: models follow the language of the passage otherwise
    user += f"\n\n(Answer in {lang}.)"
    return chat(client, system, user, on_delta=on_delta, max_tokens=1200, temperature=0.2)


def summarize_text(client: LLMClient, text: str, lang: Optional[str] = None,
                   title: Optional[str] = None, on_delta: Optional[Delta] = None) -> str:
    """A section (or a whole paper) summarized in `lang` as 3 to 6 bullets."""
    lang = lang or client.target_lang
    system = (
        f"Summarize this part of a scientific paper in {lang} as 3 to 6 short '- ' bullets: the question, "
        "the method or argument, the key numbers and the conclusion when present. Keep technical terms "
        "precise, do not invent anything that is not in the text. No heading, no preamble."
        f" Write in {lang}, even though the paper is in another language."
    )
    body = clean_selection(text)[:MAX_DOCUMENT_CHARS]
    user = (f"Section: {title}\n\n{body}" if title else body) + f"\n\n(Answer in {lang}.)"
    return chat(client, system, user, on_delta=on_delta, max_tokens=1200, temperature=0.2)


def build_glossary(client: LLMClient, text: str, lang: Optional[str] = None,
                   max_terms: int = 30) -> List[Dict[str, str]]:
    """
    Key terms of a paper with ONE translation each, so the whole document uses
    the same wording. Returns [{"term", "translation", "note"}].
    """
    lang = lang or client.target_lang
    system = (
        f"Build the terminology glossary of this scientific paper for a translation into {lang}. Pick the "
        f"{max_terms} most important domain-specific terms, acronyms and multi-word expressions (not common "
        f"words). For each, give the standard {lang} equivalent used by specialists; keep acronyms and names "
        "that are not translated in the field as they are. Answer with JSON only: "
        '[{"term": "...", "translation": "...", "note": "short definition in ' + lang + '"}]'
    )
    raw = chat(client, system, clean_selection(text)[:120_000], max_tokens=4096, temperature=0.1)
    items = _json_from(raw)
    if isinstance(items, dict):
        items = items.get("terms") or items.get("glossary") or []
    out = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and str(it.get("term", "")).strip() and str(it.get("translation", "")).strip():
            out.append({"term": str(it["term"]).strip(), "translation": str(it["translation"]).strip(),
                        "note": str(it.get("note", "")).strip()})
    return out[:max_terms]


def glossary_to_rules(items: List[Dict[str, str]]) -> str:
    """Glossary entries as translation rules ("term -> translation" lines)."""
    return "\n".join(f"{it['term']} -> {it['translation']}" for it in items
                     if it.get("term") and it.get("translation"))


def rules_to_glossary(rules: str) -> List[Dict[str, str]]:
    """Inverse of glossary_to_rules (a user-edited glossary file)."""
    out = []
    for line in (rules or "").splitlines():
        if "->" in line:
            term, _, translation = line.partition("->")
            if term.strip() and translation.strip():
                out.append({"term": term.strip(), "translation": translation.strip(), "note": ""})
    return out


def ask_document(client: LLMClient, pages: List[str], question: str,
                 lang: Optional[str] = None) -> Dict[str, Any]:
    """
    Answers a question from the paper. Returns {"answer", "quotes": [{"page",
    "quote"}]}: quotes are copied verbatim from the paper (original language)
    with their 1-based page, so the reader can be taken to the exact passage.
    """
    lang = lang or client.target_lang
    numbered, size = [], 0
    for i, page in enumerate(pages):
        chunk = f"[page {i + 1}]\n{page.strip()}"
        if size + len(chunk) > MAX_DOCUMENT_CHARS:
            break
        numbered.append(chunk)
        size += len(chunk)
    system = (
        f"You answer questions about the scientific paper below, in {lang}, using ONLY what the paper says. "
        "If the paper does not answer, say so. Support the answer with 1 to 4 quotes copied WORD FOR WORD from "
        "the paper (same language and spelling as the paper, 5 to 25 consecutive words taken from a single "
        "line or sentence, no ellipsis) with the page number shown before them. Answer with JSON only: "
        '{"answer": "...", "quotes": [{"page": 3, "quote": "..."}]}'
        f" The answer is in {lang} even when the question or the paper is in another language; the quotes stay in "
        "the paper's language."
    )
    user = "PAPER\n" + "\n\n".join(numbered) + f"\n\nQUESTION\n{question.strip()}\n\n(Answer in {lang}.)"
    raw = chat(client, system, user, max_tokens=2048, temperature=0.1)
    try:
        data = _json_from(raw)
    except Exception:
        return {"answer": raw, "quotes": []}
    answer = str(data.get("answer", "")).strip() if isinstance(data, dict) else str(data)
    quotes = []
    for q in (data.get("quotes") or []) if isinstance(data, dict) else []:
        try:
            page = int(q.get("page"))
        except (TypeError, ValueError, AttributeError):
            continue
        text = str(q.get("quote", "")).strip().strip('"“”')
        if text and 1 <= page <= len(pages):
            # Keep only quotes really present on their page (no invented citation)
            if _normalize(text)[:40] in _normalize(pages[page - 1]):
                quotes.append({"page": page, "quote": text})
            else:
                found = next((i for i, p in enumerate(pages) if _normalize(text)[:40] in _normalize(p)), None)
                if found is not None:
                    quotes.append({"page": found + 1, "quote": text})
    return {"answer": answer, "quotes": quotes}


def _normalize(text: str) -> str:
    """Comparison form: letters and digits only, lowercase (layout-proof)."""
    return re.sub(r"[^0-9a-z]+", "", clean_selection(text).lower())


# ── Document text ─────────────────────────────────────────────────────────────

def page_texts(pdf_path: str, password: Optional[str] = None) -> List[str]:
    """Plain text of every page (pypdf, fast, no layout engine)."""
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    if reader.is_encrypted:
        reader.decrypt(password or "")
    out = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:
            out.append("")
    return out
