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
from typing import Dict, Optional

from loguru import logger

from .core.constants import DEFAULT_MODEL, DEFAULT_PARALLEL_REQUESTS, DEFAULT_TEMPERATURE
from .core.llm_client import LLMClient
from .core.pipeline import ProgressCallback, TranslationReport, extract_document, translate_pdf
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
        """
        self.model = model
        self.target_lang = target_lang
        self.temperature = temperature
        self.custom_base_url = custom_base_url
        self.all_keys = all_keys or {}
        self.parallel = parallel
        self.glossary = glossary
        self.max_retries = max_retries
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
    ) -> TranslationReport:
        """
        Translates a PDF and returns a detailed report (tokens, cost, failures).
        With structured=True, report.document is a Document whose elements carry
        their aligned translation; render_pdf=False skips the PDF rendering.

        Args:
            input_pdf_path: Source PDF.
            output_pdf_path: Destination (default '<input>_translated.pdf').
            pages: Optional page range, e.g. '1-3, 5'. Only those pages are converted.
            progress: Optional callback(batches_done, batches_total).
            keep_html: Optional path to also save the translated HTML.
            password: Password for PDFs that require one to open.
        """
        if not input_pdf_path.lower().endswith(".pdf"):
            return TranslationReport(success=False, error=f"Not a PDF file: {input_pdf_path}")
        return translate_pdf(
            input_pdf_path, output_pdf_path, self._client(),
            pages=pages, parallel=self.parallel, progress=progress,
            keep_html=keep_html, user_password=password,
            structured=structured, render_pdf=render_pdf,
        )

    def translate(self, input_pdf_path: str, output_pdf_path: Optional[str] = None,
                  pages: Optional[str] = None) -> bool:
        """Backward-compatible API: returns True on success."""
        report = self.translate_document(input_pdf_path, output_pdf_path, pages=pages)
        if not report.success:
            logger.error(report.error or "Translation failed.")
        return report.success


def extract(pdf_path: str, pages: Optional[str] = None, password: Optional[str] = None,
            measure: bool = True) -> Document:
    """
    PDF -> structured Document: titles, sections, paragraphs, lists, tables,
    captions, formulas, footnotes, headers/footers, each with its page and its
    exact box in PDF points. Local and free: no LLM, no API key.

        >>> doc = rocktranslate.extract("paper.pdf")
        >>> doc.to_markdown("paper.md"); doc.to_json("paper.json")
        >>> chunks = doc.chunks(max_characters=1500)        # RAG-ready
    """
    return extract_document(pdf_path, pages=pages, user_password=password, measure=measure)


def translate(pdf_path: str, lang: str = "French", model: str = DEFAULT_MODEL, api_key: Optional[str] = None,
              pages: Optional[str] = None, output_pdf: Optional[str] = None, render_pdf: bool = True,
              parallel: int = DEFAULT_PARALLEL_REQUESTS, password: Optional[str] = None,
              **options) -> Document:
    """
    PDF -> translated Document (and, by default, the translated PDF with the
    original layout). Every element keeps its original text AND its aligned
    translation: doc.to_markdown(bilingual=True), doc.to_json(), doc.chunks().

        >>> doc = rocktranslate.translate("paper.pdf", lang="German", pages="1-2")
        >>> doc.output_pdf, doc.report.cost_usd
        >>> doc.to_markdown("paper.de.md", translated=True)

    Raises RuntimeError when nothing could be translated (key, network...).
    """
    translator = RockTranslator(model=model, api_key=api_key, target_lang=lang, parallel=parallel, **options)
    report = translator.translate_document(pdf_path, output_pdf, pages=pages, password=password,
                                           structured=True, render_pdf=render_pdf)
    if report.document is None:
        raise RuntimeError(report.error or "Translation failed.")
    doc: Document = report.document
    doc.report = report
    doc.output_pdf = report.output_path if render_pdf and report.output_path and os.path.exists(report.output_path) else None
    return doc


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import sys
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        print("Usage: python -m rocktranslate.api <file.pdf> [pages]")
        sys.exit(1)
    rt = RockTranslator(model=os.getenv("ROCKTRANSLATE_MODEL", DEFAULT_MODEL))
    print(rt.translate_document(sys.argv[1], pages=sys.argv[2] if len(sys.argv) > 2 else None))
