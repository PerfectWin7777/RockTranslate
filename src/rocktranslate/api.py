"""
RockTranslate — Programmatic Python API
Path: src/rocktranslate/api.py

This module provides the core high-fidelity PDF translation class for Python developers.
"""

import os
import re
import tempfile
import shutil
from typing import Optional, Dict, Any
from loguru import logger

# Import sibling package modules
from .core.constants import DEFAULT_ASSETS_DIR
from .core.html_transformer import convert_pdf_to_html, instrument_html
from .core.chunker import build_batches
from .core.llm_client import LLMClient
from .core.pdf_metadata import get_pdf_metadata
from .core.renderer import (
    resolve_pdf_renderer,
    apply_translations_offline,
    print_html_to_vector_pdf
)


class RockTranslator:
    """Core programmatic translator class to translate PDFs while preserving layout."""

    def __init__(
        self,
        model: str = "gemini/gemini-3.1-flash-lite",
        api_key: Optional[str] = None,
        target_lang: str = "French",
        temperature: float = 1.0,
        custom_base_url: Optional[str] = None,
        all_keys: Optional[Dict[str, str]] = None
    ) -> None:
        """Initializes the RockTranslator engine.

        Args:
            model: Target LLM model routing (e.g., 'gemini/gemini-3.1-flash-lite').
            api_key: API Key for the active provider.
            target_lang: Destination language name (e.g., 'Spanish', 'German').
            temperature: Model sampling temperature (0.0 to 2.0).
            custom_base_url: Optional target API gateway (e.g., local Ollama port).
            all_keys: Dictionary mapping multiple provider keys.
        """
        self.model: str = model
        self.api_key: Optional[str] = api_key or os.getenv("GEMINI_API_KEY")
        self.target_lang: str = target_lang
        self.temperature: float = temperature
        self.custom_base_url: Optional[str] = custom_base_url
        self.all_keys: Dict[str, str] = all_keys or {}
        
        logger.info(
            f"RockTranslator initialized programmatically (model='{self.model}', "
            f"language='{self.target_lang}', temp={self.temperature})"
        )

    def translate(self, input_pdf_path: str, output_pdf_path: Optional[str] = None) -> bool:
        """Translates a target PDF document while preserving layout.

        Args:
            input_pdf_path: Absolute or relative path to the input PDF.
            output_pdf_path: Target output path. Defaults to '[input]_translated.pdf'.

        Returns:
            True if translation and rendering succeeded, False otherwise.
        """
        if not os.path.exists(input_pdf_path) or not input_pdf_path.lower().endswith(".pdf"):
            logger.error(f"Invalid input PDF file path: {input_pdf_path}")
            return False

        # Resolve output path
        if not output_pdf_path:
            pdf_dir = os.path.dirname(os.path.abspath(input_pdf_path))
            pdf_basename = os.path.splitext(os.path.basename(input_pdf_path))[0]
            output_pdf_path = os.path.join(pdf_dir, f"{pdf_basename}_translated.pdf")

        logger.info(f"Scanning system environment for Chromium rendering engines...")
        # Smart dual-layer resolver: System browser first, automatic download fallback second
        browser_path = resolve_pdf_renderer()
        if not browser_path:
            logger.error("No compatible Chromium-based browser (Chrome, Edge) found. Printing cancelled."
                         "Failed to resolve or download a compatible Chromium rendering engine.")
            return False
        logger.info(f"Using browser renderer: '{os.path.basename(browser_path)}'")

        # Execute conversion using temp files
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_html_path = os.path.join(temp_dir, "raw.html")
            workspace_html_path = os.path.join(temp_dir, "workspace.html")
            translated_html_path = os.path.join(temp_dir, "translated.html")

            logger.info("Step 1: Extracting layout coordinates (pdf2htmlEX)...")
            convert_pdf_to_html(input_pdf_path, DEFAULT_ASSETS_DIR)
            
            pdf_dir_local = os.path.dirname(os.path.abspath(input_pdf_path))
            pdf_basename_local = os.path.splitext(os.path.basename(input_pdf_path))[0]
            generated_raw = os.path.join(pdf_dir_local, f"{pdf_basename_local}_raw.html")
            
            if not os.path.exists(generated_raw):
                logger.error("Geometric HTML compilation failed.")
                return False
                
            shutil.move(generated_raw, raw_html_path)

            logger.info("Step 2: Instrumenting HTML DOM coordinates...")
            original_texts, tid_to_page = instrument_html(raw_html_path, workspace_html_path)

            logger.info("Step 3: Building translation batches...")
            batches = build_batches(original_texts, self.model)
            total_batches = len(batches)
            
            if not batches:
                logger.warning("No translatable prose segments found in this document.")
                return False

            # Extract physical dimensions
            metadata = get_pdf_metadata(input_pdf_path)
            page_size_raw = metadata.get("page_size", "")
            match = re.search(r'\[([\d\.]+)\s*x\s*([\d\.]+)\s*cm\]', page_size_raw)
            page_size_css = f"{match.group(1)}cm {match.group(2)}cm" if match else "A4"

            # Setup translation client
            client = LLMClient(
                model=self.model,
                api_key=self.api_key,
                target_lang=self.target_lang,
                custom_base_url=self.custom_base_url,
                all_keys=self.all_keys
            )

            translated_results: Dict[str, str] = {}
            
            # Instantly bypass mathematical formulas or digit layout segments
            trans_ids = set()
            for b in batches:
                trans_ids.update(b.ids)
                
            skipped_ids = set(original_texts.keys()) - trans_ids
            for skip_id in skipped_ids:
                translated_results[skip_id] = original_texts[skip_id]

            logger.info(f"Step 4: Sending {len(trans_ids)} segment(s) in {total_batches} batch(es) to LLM...")
            
            for idx, batch in enumerate(batches):
                logger.info(f"Processing batch {idx + 1}/{total_batches}...")
                results = client.translate_batch(batch.segments)
                if results is None:
                    logger.error("API translation workflow interrupted due to network errors.")
                    return False
                    
                for res in results:
                    seg_id = res.get("id")
                    translated_text = res.get("translated")
                    if seg_id and translated_text:
                        translated_results[seg_id] = translated_text

            logger.info("Step 5: Injecting translated text overlays...")
            apply_translations_offline(
                workspace_html_path, 
                translated_html_path, 
                translated_results, 
                page_size_css
            )

            logger.info(f"Step 6: Headless vector printing to target destination: {output_pdf_path}")
            if print_html_to_vector_pdf(browser_path, translated_html_path, output_pdf_path):
                logger.info("PDF translation and layout preservation completed successfully!")
                return True
                
            logger.error("Failed to generate output vector PDF via browser headless print.")
            return False



"""

if __name__ == "__main__":
     # ==============================================================================
    # 📚 PROGRAMMATIC USAGE EXAMPLES & DIAGNOSTICS
    # ==============================================================================


    # Example usage demonstrating programmatic translation.
    # Ensure you have your API key set in your environment or local .env file.
    # E.g., export GEMINI_API_KEY="your_api_key_here"
   
    # This block demonstrates how to integrate RockTranslator into your own Python
    # scripts for various use cases and setups.

    # import the library 
    import os
    from rocktranslate import RockTranslator
    
    # import the logger
    try:
        from loguru import logger
    except ImportError:
        import logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        logger = logging.getLogger("RockTranslate")

    
    logger.info("Executing RockTranslate programmatic API diagnostics...")

    # Define a test file pathway
    sample_pdf = "article_scientifique.pdf"

    # Ensure a sample file is present before initiating diagnostic runs
    if not os.path.exists(sample_pdf):
        logger.warning(
            f"Sample file '{sample_pdf}' not found in the current working directory.\n"
            "Please place a valid PDF in your execution folder to run these tests."
        )
    else:
        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 1: Basic Translation (Using Google Gemini with environment key)
        # ──────────────────────────────────────────────────────────────────────
        logger.info("--- SCENARIO 1: Standard Gemini Translation ---")
        # Automatically searches for GEMINI_API_KEY inside system environment variables
        translator_gemini = RockTranslator(
            model="gemini/gemini-3.1-flash-lite",
            target_lang="Spanish"
        )
        
        # Executes translation, saving the file to '[article_scientifique]_translated.pdf'
        success_gemini = translator_gemini.translate(input_pdf_path=sample_pdf)
        logger.info(f"Scenario 1 complete. Success: {success_gemini}")

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 2: Custom Output Path and Language Customization
        # ──────────────────────────────────────────────────────────────────────
        logger.info("--- SCENARIO 2: Custom Language & Output Path ---")
        translator_custom = RockTranslator(
            model="gemini/gemini-3.1-flash-lite",
            target_lang="German"
        )
        
        # Translates to German and writes output to a custom specified path
        custom_output = "results/german_report.pdf"
        os.makedirs("results", exist_ok=True)
        
        success_custom = translator_custom.translate(
            input_pdf_path=sample_pdf,
            output_pdf_path=custom_output
        )
        logger.info(f"Scenario 2 complete. Translated PDF written to: {custom_output} (Success: {success_custom})")

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 3: Alternative Provider (OpenAI) with Explicit API Key
        # ──────────────────────────────────────────────────────────────────────
        logger.info("--- SCENARIO 3: Custom Provider with Explicit Credentials ---")
        # Explicit credentials pass overrides local environment configurations
        translator_openai = RockTranslator(
            model="openai/gpt-4o-mini",
            api_key="sk-your-openai-api-key-here",  # Replace with a valid credentials key
            target_lang="Italian",
            temperature=0.3  # Lower temperature for more rigid, literal academic translation
        )
        
        # success_openai = translator_openai.translate(input_pdf_path=sample_pdf)
        logger.info("Scenario 3 configured. (Run skipped to avoid credential errors.)")

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 4: Fully Local and Offline Translation (Using Ollama)
        # ──────────────────────────────────────────────────────────────────────
        logger.info("--- SCENARIO 4: Offline Local Translation ---")
        # No API keys or remote servers required. Ensure Ollama is running on the host machine.
        translator_local = RockTranslator(
            model="ollama/llama3",
            target_lang="French",
            custom_base_url="http://localhost:11434"  # Default local Ollama gateway port
        )
        
        # success_local = translator_local.translate(input_pdf_path=sample_pdf)
        logger.info("Scenario 4 configured for local offline execution.")
        
"""