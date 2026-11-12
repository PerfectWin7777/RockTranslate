"""
RockTranslate — Programmatic Python API
Path: src/rocktranslate/api.py

Example:
    >>> from rocktranslate import RockTranslator
    >>> rt = RockTranslator(model="deepseek/deepseek-flash", target_lang="French")
    >>> report = rt.translate_document("paper.pdf", pages="1-3")
    >>> report.success, report.output_path, report.cost_usd

License: MIT License
"""

import os
from typing import Any, Dict, List, Optional

from loguru import logger

from .core.constants import DEFAULT_MODEL, DEFAULT_PARALLEL_REQUESTS, DEFAULT_TEMPERATURE
from .core.llm_client import LLMClient
from .core.pipeline import ProgressCallback, TranslationReport, extract_document, translate_pdf
from .core import assist
from .core.assist import glossary_to_rules
from .core.side_by_side import make_side_by_side
from .core.sources import default_output_dir, is_url, resolve_pdf_source
from .document import Document


class RockTranslator:
    """Translates PDFs while preserving their exact layout."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        target_lang: str = "French",
        temperature: float = DEFAULT_TEMPERATURE,
        custom_base_url: Optional[str] = None,
        all_keys: Optional[Dict[str, str]] = None,
        parallel: int = DEFAULT_PARALLEL_REQUESTS,
        glossary: Optional[str] = None,
        max_retries: int = 4,
        translate_references: bool = True,
    ) -> None:
        """
        Args:
            model: LiteLLM model route, e.g. 'deepseek/deepseek-flash', 'gemini/gemini-3.8-flash'.
            api_key: Provider API key. Defaults to the provider's standard env variable
                (DEEPSEEK_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY...).
            target_lang: Destination language name (e.g. 'Spanish', 'German').
            temperature: Sampling temperature (low = faithful translation).
            custom_base_url: Optional API gateway (e.g. local Ollama).
            all_keys: Provider -> key mapping used for same-provider fallbacks.
            parallel: Number of concurrent LLM requests.
            glossary: Optional mandatory terminology rules for the prompt.
            max_retries: Attempts per batch before giving up.
            translate_references: False keeps the bibliography in its original language.
        """
        self.model = model
        self.target_lang = target_lang
        self.temperature = temperature
        self.custom_base_url = custom_base_url
        self.all_keys = all_keys or {}
        self.parallel = parallel
        self.glossary = glossary
        self.max_retries = max_retries
        self.translate_references = translate_references
        self.api_key = api_key or LLMClient._get_api_key_from_env(model)

        logger.info(
            f"RockTranslator initialized (model='{self.model}', language='{self.target_lang}', "
            f"temperature={self.temperature}, parallel={self.parallel})"
        )

    def _client(self) -> LLMClient:
        return LLMClient(
            model=self.model,
            api_key=self.api_key,
            target_lang=self.target_lang,
            custom_base_url=self.custom_base_url,
            all_keys=self.all_keys,
            custom_glossary=self.glossary,
            temperature=self.temperature,
            max_retries=self.max_retries,
        )

    def translate_document(
        self,
        input_pdf_path: str,
        output_pdf_path: Optional[str] = None,
        pages: Optional[str] = None,
        progress: Optional[ProgressCallback] = None,
        keep_html: Optional[str] = None,
        password: Optional[str] = None,
        structured: bool = False,
        render_pdf: bool = True,
        images: bool = True,
    ) -> TranslationReport:
        """
        Translates a PDF and returns a detailed report (tokens, cost, failures).
        With structured=True, report.document is a Document whose elements carry
        their aligned translation; render_pdf=False skips the PDF rendering.

        Args:
            input_pdf_path: Source PDF, or an http(s) link to one (arXiv /abs/ links work).
            output_pdf_path: Destination (default '<input>_translated.pdf'; for a link,
                in the current directory).
            pages: Optional page range, e.g. '1-3, 5'. Only those pages are converted.
            progress: Optional callback(batches_done, batches_total).
            keep_html: Optional path to also save the translated HTML.
            password: Password for PDFs that require one to open.
        """
        source = input_pdf_path
        try:
            input_pdf_path = resolve_pdf_source(source)
        except (OSError, ValueError) as e:
            return TranslationReport(success=False, error=f"Could not download {source}: {e}")
        if not is_url(source) and not input_pdf_path.lower().endswith(".pdf"):
            return TranslationReport(success=False, error=f"Not a PDF file: {input_pdf_path}")
        if not output_pdf_path and is_url(source):
            stem = os.path.splitext(os.path.basename(input_pdf_path))[0]
            output_pdf_path = os.path.join(default_output_dir(source, input_pdf_path), f"{stem}_translated.pdf")
        return translate_pdf(
            input_pdf_path, output_pdf_path, self._client(),
            pages=pages, parallel=self.parallel, progress=progress,
            keep_html=keep_html, user_password=password,
            structured=structured, render_pdf=render_pdf,
            translate_references=self.translate_references, images=images,
        )

    def translate(self, input_pdf_path: str, output_pdf_path: Optional[str] = None,
                  pages: Optional[str] = None) -> bool:
        """Backward-compatible API: returns True on success."""
        report = self.translate_document(input_pdf_path, output_pdf_path, pages=pages)
        if not report.success:
            logger.error(report.error or "Translation failed.")
        return report.success


def extract(pdf_path: str, pages: Optional[str] = None, password: Optional[str] = None,
            measure: bool = True, images: bool = True) -> Document:
    """
    PDF -> structured Document: titles, sections, paragraphs, lists, tables,
    captions, formulas, footnotes, headers/footers, each with its page and its
    exact box in PDF points. Local and free: no LLM, no API key.

        >>> doc = rocktranslate.extract("paper.pdf")
        >>> doc.to_markdown("paper.md"); doc.to_json("paper.json")
        >>> chunks = doc.chunks(max_characters=1500)        # RAG-ready
        >>> doc = rocktranslate.extract("https://arxiv.org/abs/1706.03762")   # links work too
        >>> doc.images; doc.to_markdown("paper.md")    # figures -> paper_images/*.png, linked

    images=True (default) renders every captioned figure as a PNG Image element
    (vector plots included); images=False skips it (faster, text only).
    """
    return extract_document(resolve_pdf_source(pdf_path), pages=pages, user_password=password, measure=measure,
                            images=images)


def translate(pdf_path: str, lang: str = "French", model: str = DEFAULT_MODEL, api_key: Optional[str] = None,
              pages: Optional[str] = None, output_pdf: Optional[str] = None, render_pdf: bool = True,
              parallel: int = DEFAULT_PARALLEL_REQUESTS, password: Optional[str] = None,
              side_by_side: Optional[str] = None, images: bool = True, **options) -> Document:
    """
    PDF -> translated Document (and, by default, the translated PDF with the
    original layout). Every element keeps its original text AND its aligned
    translation: doc.to_markdown(bilingual=True), doc.to_json(), doc.chunks().

        >>> doc = rocktranslate.translate("paper.pdf", lang="German", pages="1-2")
        >>> doc.output_pdf, doc.report.cost_usd
        >>> doc.to_markdown("paper.de.md", translated=True)

    side_by_side: optional path of a bilingual study copy (original page |
    translated page on each sheet). glossary: "term -> translation" lines, or
    the list returned by rocktranslate.glossary(), applied to every segment.

    Raises RuntimeError when nothing could be translated (key, network...).
    """
    if isinstance(options.get("glossary"), list):
        options["glossary"] = glossary_to_rules(options["glossary"])
    translator = RockTranslator(model=model, api_key=api_key, target_lang=lang, parallel=parallel, **options)
    report = translator.translate_document(pdf_path, output_pdf, pages=pages, password=password,
                                           structured=True, render_pdf=render_pdf, images=images)
    if report.document is None:
        raise RuntimeError(report.error or "Translation failed.")
    doc: Document = report.document
    doc.report = report
    doc.output_pdf = report.output_path if render_pdf and report.output_path and os.path.exists(report.output_path) else None
    if side_by_side and doc.output_pdf:
        first = int(str(pages).split(",")[0].split("-")[0]) if pages else 1
        make_side_by_side(resolve_pdf_source(pdf_path), doc.output_pdf, side_by_side, first_page=first,
                          password=password)
        doc.side_by_side_pdf = side_by_side
    return doc


# ── Reading assistant (short LLM calls) ──────────────────────────────────────

def _assistant(model: str, api_key: Optional[str], lang: str, glossary: Optional[str] = None,
               base_url: Optional[str] = None) -> LLMClient:
    return LLMClient(model=model, api_key=api_key, target_lang=lang, custom_glossary=glossary,
                     custom_base_url=base_url)


def translate_text(text: str, lang: str = "French", model: str = DEFAULT_MODEL, api_key: Optional[str] = None,
                   on_delta=None) -> str:
    """
    Translates a passage copied from a PDF (broken lines and hyphenated words
    are rebuilt first). on_delta(piece) receives the answer while it streams.

        >>> rocktranslate.translate_text("The encoder is com-\nposed of a stack", "French")
    """
    return assist.translate_text(_assistant(model, api_key, lang), text, lang, on_delta=on_delta)


def explain(text: str, lang: str = "French", model: str = DEFAULT_MODEL, api_key: Optional[str] = None,
            on_delta=None) -> str:
    """Explains a passage or a formula in plain words, in `lang`."""
    return assist.explain_text(_assistant(model, api_key, lang), text, lang, on_delta=on_delta)


def summarize(pdf_path: str, lang: str = "French", section: Optional[str] = None,
              model: str = DEFAULT_MODEL, api_key: Optional[str] = None, password: Optional[str] = None,
              on_delta=None) -> str:
    """
    Summary of a paper, or of one of its sections ("3.2", "Results"), in `lang`.
    A section is located with the structured extraction (headings and depth).
    """
    local = resolve_pdf_source(pdf_path)
    if section:
        text = extract(local, password=password).section_text(section)
        if text is None:
            raise ValueError(f"Section not found: {section}")
    else:
        text = "\n\n".join(assist.page_texts(local, password))
    return assist.summarize_text(_assistant(model, api_key, lang), text, lang, title=section, on_delta=on_delta)


def glossary(pdf_path: str, lang: str = "French", max_terms: int = 30, model: str = DEFAULT_MODEL,
             api_key: Optional[str] = None, password: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Key terms of a paper with one consistent translation each:
    [{"term", "translation", "note"}]. Pass it to translate(glossary=...).
    """
    pages = assist.page_texts(resolve_pdf_source(pdf_path), password)
    return assist.build_glossary(_assistant(model, api_key, lang), "\n\n".join(pages), lang, max_terms)


def ask(pdf_path: str, question: str, lang: str = "French", model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    """
    Answers a question from the paper: {"answer", "quotes": [{"page", "quote"}]}.
    Quotes are verbatim passages of the paper with their page (checked).

        >>> rocktranslate.ask("paper.pdf", "Which dataset is used?", lang="French")
    """
    pages = assist.page_texts(resolve_pdf_source(pdf_path), password)
    return assist.ask_document(_assistant(model, api_key, lang), pages, question, lang)


def side_by_side(original_pdf: str, translated_pdf: str, output_pdf: str, first_page: int = 1,
                 password: Optional[str] = None) -> int:
    """Bilingual study copy: original page | translated page. Returns the sheet count."""
    return make_side_by_side(resolve_pdf_source(original_pdf), translated_pdf, output_pdf,
                             first_page=first_page, password=password)


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import sys
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        print("Usage: python -m rocktranslate.api <file.pdf> [pages]")
        sys.exit(1)
    rt = RockTranslator(model=os.getenv("ROCKTRANSLATE_MODEL", DEFAULT_MODEL))
    print(rt.translate_document(sys.argv[1], pages=sys.argv[2] if len(sys.argv) > 2 else None))
