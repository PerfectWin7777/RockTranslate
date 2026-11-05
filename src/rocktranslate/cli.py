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

from loguru import logger

from . import __version__
from .core.config_manager import config_db
from .core.constants import DEFAULT_PARALLEL_REQUESTS, DEFAULT_PROVIDERS, DEFAULT_TEMPERATURE


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


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        sys.exit(run_doctor())

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
            "  rocktranslate doctor          # check pdf2htmlEX, browser, keys\n"
        ),
    )
    parser.add_argument("input", help="Source PDF file.")
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
    parser.add_argument("--version", action="version", version=f"rocktranslate {__version__}")
    args = parser.parse_args()

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
    )

    def progress(done: int, total: int) -> None:
        sys.stderr.write(f"\r[rocktranslate] batches {done}/{total}")
        sys.stderr.flush()
        if done == total:
            sys.stderr.write("\n")

    report = translator.translate_document(
        args.input, args.output, pages=args.pages, progress=progress,
        keep_html=args.keep_html, password=args.password,
    )

    summary = (f"{report.segments_translated}/{report.segments_total} segments, "
               f"{report.batches_total} batches, {report.seconds:.1f}s, "
               f"{report.prompt_tokens + report.completion_tokens} tokens, ~${report.cost_usd:.4f}")
    if report.success:
        logger.info(f"Done: {report.output_path} ({summary})")
        sys.exit(0)
    if report.output_path and os.path.exists(report.output_path) and report.batches_failed:
        logger.warning(f"Partial result: {report.output_path} — {report.error} ({summary})")
        sys.exit(2)
    logger.error(report.error or "Translation failed.")
    sys.exit(1)


if __name__ == "__main__":
    main()
