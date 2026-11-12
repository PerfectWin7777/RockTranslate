"""
RockTranslate — Command Line Interface
Path: src/rocktranslate/cli.py

    rocktranslate paper.pdf -l French -m deepseek/deepseek-flash --pages 1-3
    rocktranslate doctor

License: MIT License
"""

import argparse
import json
import os
import sys
from typing import List

from loguru import logger

from . import __version__
from .core.config_manager import config_db
from .core.constants import DEFAULT_PARALLEL_REQUESTS, DEFAULT_PROVIDERS, DEFAULT_TEMPERATURE
from .core.sources import default_output_dir, is_url, resolve_pdf_source


def _default_model() -> str:
    """Model saved in the GUI settings, else the first model of the first provider."""
    provider = config_db.get("APIConfig", "provider", "")
    cfg = DEFAULT_PROVIDERS.get(provider)
    if cfg:
        model = config_db.get("APIConfig", f"last_model_{provider}", cfg["models"][0])
        prefix = cfg.get("prefix", "")
        return model if (not prefix or model.startswith(prefix)) else f"{prefix}{model}"
    from .core.constants import DEFAULT_MODEL
    return DEFAULT_MODEL


def _saved_keys() -> dict:
    raw = config_db.get("APIConfig", "api_keys_by_provider", {})
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except ValueError:
        return {}


def _key_for_model(model: str, keys: dict):
    from .core.llm_client import LLMClient
    env_key = LLMClient._get_api_key_from_env(model)
    if env_key:
        return env_key
    for name, cfg in DEFAULT_PROVIDERS.items():
        prefix = cfg.get("prefix", "")
        if prefix and model.startswith(prefix):
            return keys.get(name)
    return None


def run_doctor() -> int:
    """Checks every external dependency and prints actionable fixes."""
    from .core.downloader import check_and_download_pdf2htmlex, check_and_download_pdfjs
    from .core.renderer import resolve_pdf_renderer

    ok = True
    print(f"RockTranslate {__version__} — environment check\n")
    print(f"  Python            : {sys.version.split()[0]} ({sys.executable})")
    print(f"  Config directory  : {config_db.config_dir}")

    exe = check_and_download_pdf2htmlex()
    print(f"  pdf2htmlEX        : {exe or 'MISSING'}")
    ok &= bool(exe)

    viewer = check_and_download_pdfjs()
    print(f"  PDF.js (GUI only) : {viewer or 'MISSING'}")

    browser = resolve_pdf_renderer()
    print(f"  PDF renderer      : {browser or 'MISSING'}")
    ok &= bool(browser)

    try:
        import webview  # noqa: F401
        print("  GUI (pywebview)   : installed")
    except ImportError:
        print('  GUI (pywebview)   : not installed (pip install "rocktranslate[gui]")')

    keys = _saved_keys()
    found = [name for name, cfg in DEFAULT_PROVIDERS.items()
             if keys.get(name) or (cfg.get("key_env") and os.getenv(cfg["key_env"]))]
    print(f"  API keys          : {', '.join(found) if found else 'none configured'}")

    print("\nResult:", "ready" if ok else "some components are missing (see above)")
    return 0 if ok else 1


def _write_structured(doc, base: str, formats: List[str], bilingual: bool, translated: bool) -> List[str]:
    """Writes the requested structured outputs next to `base` (no extension)."""
    written = []
    if "json" in formats:
        written.append(base + ".json")
        doc.to_json(written[-1])
    if "md" in formats or "markdown" in formats:
        written.append(base + ".md")
        doc.to_markdown(written[-1], translated=translated and not bilingual, bilingual=bilingual)
    if "chunks" in formats:
        written.append(base + ".chunks.json")
        with open(written[-1], "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in doc.chunks()], f, ensure_ascii=False, indent=2)
    return written


def run_extract(argv: List[str]) -> int:
    """rocktranslate extract paper.pdf --format json,md : structure only, no LLM."""
    parser = argparse.ArgumentParser(
        prog="rocktranslate extract",
        description="Extracts the structure of a PDF (titles, sections, paragraphs, tables, captions, "
                    "formulas...) as JSON / Markdown / RAG chunks. Local, free, no API key.")
    parser.add_argument("input", help="Source PDF file, or an http(s) link to one.")
    parser.add_argument("-f", "--format", default="json,md",
                        help="Comma-separated: json, md, chunks (default: json,md).")
    parser.add_argument("-o", "--output", help="Output base path without extension (default: next to the PDF).")
    parser.add_argument("-p", "--pages", help="Page range, e.g. '1-3, 5'.")
    parser.add_argument("--password", help="Password of a protected PDF.")
    args = parser.parse_args(argv)
    source = args.input
    try:
        local_pdf = resolve_pdf_source(source)
    except (OSError, ValueError) as e:
        logger.error(f"Could not download {source}: {e}")
        return 1
    if not os.path.isfile(local_pdf):
        logger.error(f"File not found: {source}")
        return 1
    from .api import extract
    doc = extract(local_pdf, pages=args.pages, password=args.password)
    stem = os.path.splitext(os.path.basename(local_pdf))[0]
    base = args.output or os.path.join(default_output_dir(source, local_pdf), stem)
    formats = [f.strip().lower() for f in args.format.split(",") if f.strip()]
    for path in _write_structured(doc, base, formats, bilingual=False, translated=False):
        logger.info(f"Written: {path}")
    logger.info(f"Done: {doc!r}")
    return 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        sys.exit(run_doctor())
    if len(sys.argv) > 1 and sys.argv[1] == "extract":
        sys.exit(run_extract(sys.argv[2:]))

    parser = argparse.ArgumentParser(
        prog="rocktranslate",
        description="RockTranslate: layout-preserving PDF translator.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  rocktranslate paper.pdf -l French\n"
            "  rocktranslate paper.pdf -l Spanish -o paper_es.pdf --pages 1-3\n"
            "  rocktranslate paper.pdf -m deepseek/deepseek-flash --parallel 6\n"
            "  rocktranslate paper.pdf -m ollama/llama4 --base-url http://localhost:11434\n"
            "  rocktranslate paper.pdf -l German -f pdf,md --bilingual\n"
            "  rocktranslate extract paper.pdf -f json,md,chunks   # structure only, no LLM\n"
            "  rocktranslate doctor          # check pdf2htmlEX, browser, keys\n"
        ),
    )
    parser.add_argument("input", help="Source PDF file, or an http(s) link to one (arXiv /abs/ links work).")
    parser.add_argument("-l", "--lang", default="French", help="Target language (default: French).")
    parser.add_argument("-o", "--output", help="Output PDF (default: <input>_translated.pdf).")
    parser.add_argument("-m", "--model", help="LiteLLM model route, e.g. deepseek/deepseek-flash.")
    parser.add_argument("-k", "--api-key", help="API key (default: provider env variable or GUI settings).")
    parser.add_argument("-t", "--temp", type=float, default=None,
                        help=f"Temperature (default: {DEFAULT_TEMPERATURE}).")
    parser.add_argument("-p", "--pages", help="Page range to translate, e.g. '1-3, 5'.")
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL_REQUESTS,
                        help=f"Concurrent LLM requests (default: {DEFAULT_PARALLEL_REQUESTS}).")
    parser.add_argument("--base-url", help="Custom API base URL (Ollama, proxies...).")
    parser.add_argument("--password", help="Password of a protected PDF.")
    parser.add_argument("--keep-html", help="Also save the translated HTML to this path.")
    parser.add_argument("-f", "--format", default="pdf",
                        help="Comma-separated outputs: pdf, json, md, chunks (default: pdf).\n"
                             "json/md/chunks hold every element with its aligned translation.")
    parser.add_argument("--skip-references", action="store_true",
                        help="Keep the bibliography in its original language (fewer tokens).")
    parser.add_argument("--bilingual", action="store_true",
                        help="Markdown output: original paragraph followed by its translation.")
    parser.add_argument("--version", action="version", version=f"rocktranslate {__version__}")
    args = parser.parse_args()

    source = args.input
    if is_url(source):
        try:
            args.input = resolve_pdf_source(source)
        except (OSError, ValueError) as e:
            logger.error(f"Could not download {source}: {e}")
            sys.exit(1)
    if not os.path.isfile(args.input) and os.path.isfile(args.input + ".pdf"):
        args.input += ".pdf"          # "paper" -> "paper.pdf"
    if not os.path.isfile(args.input) or not args.input.lower().endswith(".pdf"):
        logger.error(f"Invalid input PDF path: {args.input} (file not found or not a .pdf; "
                     "put the path in quotes if it contains spaces)")
        sys.exit(1)

    keys = _saved_keys()
    model = args.model or _default_model()
    api_key = args.api_key or _key_for_model(model, keys)
    if not api_key and "ollama" not in model.lower():
        logger.error(f"No API key for '{model}'. Use -k or set the provider's environment variable.")
        sys.exit(1)

    temperature = args.temp if args.temp is not None else float(
        config_db.get("TranslationConfig", "temperature", DEFAULT_TEMPERATURE))

    from .api import RockTranslator
    translator = RockTranslator(
        model=model, api_key=api_key, target_lang=args.lang, temperature=temperature,
        custom_base_url=args.base_url, all_keys=keys, parallel=args.parallel,
        glossary=config_db.get("TranslationConfig", "custom_glossary", "") or None,
        translate_references=not args.skip_references
        and bool(config_db.get("TranslationConfig", "translate_references", True)),
    )

    def progress(done: int, total: int) -> None:
        sys.stderr.write(f"\r[rocktranslate] batches {done}/{total}")
        sys.stderr.flush()
        if done == total:
            sys.stderr.write("\n")

    formats = [f.strip().lower() for f in args.format.split(",") if f.strip()]
    # Default outputs sit next to a local PDF; for a link, in the current
    # directory (never inside the hidden download cache).
    out_stem = os.path.join(default_output_dir(source, args.input),
                            os.path.splitext(os.path.basename(args.input))[0])
    pdf_output = args.output or (f"{out_stem}_translated.pdf" if is_url(source) else None)
    structured = any(f in formats for f in ("json", "md", "markdown", "chunks"))
    try:
        report = translator.translate_document(
            args.input, pdf_output, pages=args.pages, progress=progress,
            keep_html=args.keep_html, password=args.password,
            structured=structured, render_pdf="pdf" in formats,
        )
    except KeyboardInterrupt:
        logger.warning("Interrupted.")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        logger.error("Please report this with the log above: https://github.com/PerfectWin7777/RockTranslate/issues")
        sys.exit(1)

    if report.document is not None:
        base = os.path.splitext(args.output)[0] if args.output else out_stem
        if not args.output:
            base += f"_{args.lang.lower()}"
        for path in _write_structured(report.document, base, formats, args.bilingual, translated=True):
            logger.info(f"Written: {path}")

    summary = (f"{report.segments_translated}/{report.segments_total} segments, "
               f"{report.batches_total} batches, {report.seconds:.1f}s, "
               f"{report.prompt_tokens + report.completion_tokens} tokens, ~${report.cost_usd:.4f}")
    if report.success:
        logger.info(f"Done: {report.output_path or 'structured outputs written'} ({summary})")
        sys.exit(0)
    if report.output_path and os.path.exists(report.output_path) and report.batches_failed:
        logger.warning(f"Partial result: {report.output_path} — {report.error} ({summary})")
        sys.exit(2)
    logger.error(report.error or "Translation failed.")
    sys.exit(1)


if __name__ == "__main__":
    main()
