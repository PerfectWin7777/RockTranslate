"""
RockTranslate — Standalone Command Line Interface (CLI) Entry Point
Path: src/rocktranslate/cli.py

This module implements the lightweight, Qt-free CLI execution engine. It handles
asynchronous batching, offline HTML DOM translated text injection via BeautifulSoup,
and headless system browser-based print-to-PDF compilation.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import sys
import re
import json
import shutil
import argparse
import tempfile
import subprocess
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup

# ── DYNAMIC SYSTEM PATH RESOLUTION ──
# Resolves search paths so that subscripts run directly without ModuleNotFound errors.
current_dir = os.path.dirname(os.path.abspath(__file__))  # src/rocktranslate
src_dir = os.path.dirname(current_dir)                    # src
project_root = os.path.dirname(src_dir)                   # Project root

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# ────────────────────────────────────

# ── RESILIENT LOGGING FALLBACK ──
# Falls back to standard logging if loguru is not installed in the system environment
try:
    from loguru import logger
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logger = logging.getLogger("RockTranslate-CLI")

# Absolute package imports from the rocktranslate package
from .core.constants import (
    DEFAULT_ASSETS_DIR,
    THRESHOLD_PX,
    SLIDING_CONTEXT_MAX_SIZE,
    MAX_SEGMENTS_PER_BATCH,
    MAX_RETRIES,
)
from .core.config_manager import config_db
from .core.html_transformer import convert_pdf_to_html, instrument_html
from .core.chunker import build_batches, Batch
from .core.llm_client import LLMClient
from .core.pdf_metadata import get_pdf_metadata
from .core.renderer import (
    resolve_pdf_renderer,
    apply_translations_offline,
    print_html_to_vector_pdf,
)

# Only import winreg on Windows platforms to query installed internet browser registries
if sys.platform == "win32":
    import winreg
else:
    winreg = None




def main() -> None:
    """Primary CLI execution routine.

    Parses arguments, executes layout conversions, batches segments, 
    manages translations, and prints high-fidelity vector PDFs headlessly.
    """
    parser = argparse.ArgumentParser(
        description="RockTranslate CLI: High-fidelity layout-preserved PDF document translator.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
        Usage Examples:
        1. Translate to French (default) using the default Gemini model:
            rocktranslate article_scientifique.pdf -l French

        2. Translate to Spanish and save to a custom output file:
            rocktranslate paper.pdf -l Spanish -o report_es.pdf

        3. Translate to German using OpenAI with an explicit API key:
            rocktranslate document.pdf -m openai/gpt-4o-mini -k YOUR_OPENAI_KEY -l German

        4. Run fully local translation using Ollama (no API key required):
            rocktranslate document.pdf -m ollama/llama3 -l French
        """
    )
    
    parser.add_argument(
        "input", 
        help="Path to the source scientific/academic PDF file to translate."
    )
    parser.add_argument(
        "-l", "--lang", 
        default="French", 
        help=(
            "Target language for the translated document (default: French).\n"
            "Supports any language accepted by the model (e.g., French, Spanish, German, Japanese)."
        )
    )
    parser.add_argument(
        "-o", "--output", 
        help="Custom output path for the translated PDF. Default: '[input]_translated.pdf'"
    )
    parser.add_argument(
        "-m", "--model", 
        help=(
            "Target LLM model router string (default: gemini/gemini-3.1-flash-lite).\n"
            "Format: [provider]/[model_name]\n"
            "Examples:\n"
            "  - gemini/gemini-2.5-flash-lite\n"
            "  - openai/gpt-4o-mini\n"
            "  - anthropic/claude-3-5-sonnet\n"
            "  - ollama/llama3 (for local execution)"
        )
    )
    parser.add_argument(
        "-k", "--api-key", 
        help=(
            "Override/provide the API key for your selected translation provider.\n"
            "If omitted, the CLI automatically retrieves keys from your system variables\n"
            "or local '.env' file (e.g., GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY)."
        )
    )
    parser.add_argument(
        "-t", "--temp", 
        type=float, 
        help="Model generation temperature (0.0 to 2.0). Lower is more precise and consistent."
    )
    
    args = parser.parse_args()
    
    # Ensure input file exists and is a PDF
    if not os.path.exists(args.input) or not args.input.lower().endswith(".pdf"):
        logger.error(f"Invalid input PDF path: {args.input}")
        sys.exit(1)

    logger.info("Inspecting system environment for headless browser engines...")
    # Smart dual-layer resolver: System browser first, automatic download fallback second
    browser_path = resolve_pdf_renderer()
    if not browser_path:
        logger.error(
            "No compatible Chromium-based browser (Chrome, Edge, or Chromium) was found.\n"
            "A system browser is required to export high-fidelity vector PDFs in CLI mode.\n"
            "Failed to resolve or download a compatible Chromium rendering engine.\n"
            "Please check your internet connection or install Google Chrome/Microsoft Edge manually."
        )
        sys.exit(1)
        
    logger.info(f"Discovered browser: '{os.path.basename(browser_path)}'")

   # Load configuration parameters
    temp = args.temp if args.temp is not None else float(config_db.get("TranslationConfig", "temperature", 1.0))
    max_retries = int(config_db.get("TranslationConfig", "max_retries", MAX_RETRIES))
    max_batch_size = int(config_db.get("TranslationConfig", "max_segments_per_batch", MAX_SEGMENTS_PER_BATCH))

    # Parse API settings and credentials
    api_settings = config_db.get("APIConfig", "api_keys_by_provider", {})
    try:
        keys_dict = json.loads(api_settings) if isinstance(api_settings, str) else api_settings
    except Exception:
        keys_dict = {}

    # Resolve the correct target model
    model_name = args.model
    if not model_name:
        provider = config_db.get("APIConfig", "provider", "Google Gemini")
        model_name = config_db.get("APIConfig", f"last_model_{provider}", "gemini-3.1-flash-lite")
        if provider == "Google Gemini" and not model_name.startswith("gemini/"):
            model_name = f"gemini/{model_name}"

    # Resolve API Key credentials from argument, environment, or saved configurations
    api_key = args.api_key
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY") or keys_dict.get("Google Gemini", "")

    # Skip key enforcement only for local Ollama deployments
    if not api_key and "ollama" not in model_name.lower():
        logger.error(f"Missing API Key for model: {model_name}. Specify -k or configure the GEMINI_API_KEY environment variable.")
        sys.exit(1)

    logger.info(f"Processing document: '{os.path.basename(args.input)}'")
    logger.info(f"LLM Target: '{model_name}' | Language: '{args.lang}' | Temperature: {temp}")

    # Use a secure temporary directory to prevent messy residues on the file system
    with tempfile.TemporaryDirectory() as temp_dir:
        raw_html_path = os.path.join(temp_dir, "raw.html")
        workspace_html_path = os.path.join(temp_dir, "workspace.html")
        translated_html_path = os.path.join(temp_dir, "translated.html")

        # Step 1: Execute pdf2htmlEX layout conversion
        logger.info("Extracting physical PDF layout coordinates (pdf2htmlEX)...")
        convert_pdf_to_html(args.input, DEFAULT_ASSETS_DIR)
        
        # Resolve path for raw output generated by pdf2htmlEX
        pdf_dir = os.path.dirname(os.path.abspath(args.input))
        pdf_basename = os.path.splitext(os.path.basename(args.input))[0]
        generated_raw = os.path.join(pdf_dir, f"{pdf_basename}_raw.html")
        
        if not os.path.exists(generated_raw):
            logger.error("Geometric conversion failed.")
            sys.exit(1)
            
        shutil.move(generated_raw, raw_html_path)

        # Step 2: Semantic HTML DOM instrumentation
        logger.info("Segmenting DOM structures into translatable blocks...")
        original_texts, tid_to_page = instrument_html(raw_html_path, workspace_html_path)

        # Step 3: Group elements into token-controlled payload packages
        logger.info("Building optimized translation batches...")
        batches = build_batches(original_texts, model_name)
        total_batches = len(batches)

        # Dynamically calculate page dimension configurations
        metadata = get_pdf_metadata(args.input)
        page_size_raw = metadata.get("page_size", "")  # e.g., "[21.00 x 29.70 cm]"
        
        match = re.search(r'\[([\d\.]+)\s*x\s*([\d\.]+)\s*cm\]', page_size_raw)
        if match:
            width_cm = float(match.group(1))
            height_cm = float(match.group(2))
            page_size_css = f"{width_cm}cm {height_cm}cm"
        else:
            page_size_css = "A4"

        # Step 4: Run LiteLLM Translation Worker Client
        client = LLMClient(
            model=model_name,
            api_key=api_key,
            target_lang=args.lang,
            all_keys=keys_dict
        )

        translated_results: Dict[str, str] = {}
        
        # Identify non-translatable text indices (e.g. math formulas, page metrics)
        trans_ids = set()
        for b in batches:
            trans_ids.update(b.ids)
            
        # Instantly bypass translation for non-prose segments to protect token quotas
        skipped_ids = set(original_texts.keys()) - trans_ids
        for skip_id in skipped_ids:
            translated_results[skip_id] = original_texts[skip_id]

        logger.info(f"Translating {len(trans_ids)} segment(s) across {total_batches} batch(es)...")
        
        for idx, batch in enumerate(batches):
            sys.stdout.write(f"\r[CLI] Progress: Batch {idx + 1}/{total_batches}...")
            sys.stdout.flush()
            
            results = client.translate_batch(batch.segments)
            if results is None:
                print("\n")
                logger.error("Translation was interrupted due to connection failures.")
                sys.exit(1)
                
            for res in results:
                seg_id = res.get("id")
                translated_text = res.get("translated")
                if seg_id and translated_text:
                    translated_results[seg_id] = translated_text

        sys.stdout.write("\n")
        logger.info("Translation batches completed successfully.")

        # Step 5: Inject translated strings back into the HTML DOM structure
        logger.info("Rebuilding HTML DOM with translation overlays...")
        apply_translations_offline(workspace_html_path, translated_html_path, translated_results, page_size_css)

        # Step 6: Render final vector PDF using headless system browser
        output_pdf = args.output or os.path.join(pdf_dir, f"{pdf_basename}_translated.pdf")
        logger.info("Headless Chromium vector printing in progress...")
        
        if print_html_to_vector_pdf(browser_path, translated_html_path, output_pdf):
            logger.info(f"Success! Translated vector PDF saved at: '{output_pdf}'")
        else:
            logger.error("Vector PDF printing failed.")
            sys.exit(1)


if __name__ == "__main__":
    main()