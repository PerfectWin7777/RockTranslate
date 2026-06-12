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
    find_system_chromium_browser,
    apply_translations_offline,
    print_html_to_vector_pdf
)


class RockTranslator:
    """Core programmatic translator class to translate PDFs while preserving layout."""

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: Optional[str] = None,
        target_lang: str = "French",
        temperature: float = 1.0,
        custom_base_url: Optional[str] = None,
        all_keys: Optional[Dict[str, str]] = None
    ) -> None:
        """Initializes the RockTranslator engine.

        Args:
            model: Target LLM model routing (e.g., 'gemini/gemini-2.5-flash-lite').
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
        browser_path = find_system_chromium_browser()
        if not browser_path:
            logger.error("No compatible Chromium-based browser (Chrome, Edge) found. Printing cancelled.")
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
    # Example usage demonstrating programmatic translation.
    # Ensure you have your API key set in your environment or local .env file.
    # E.g., export GEMINI_API_KEY="your_api_key_here"

    # Initialize the translator
    translator = RockTranslator(
        model="gemini/gemini-2.5-flash-lite",
        target_lang="Spanish"
    )

    # Translate a sample document
    sample_pdf = "Sample_doc.pdf"
    
    if os.path.exists(sample_pdf):
        logger.info(f"Starting test translation for: {sample_pdf}")
        success = translator.translate(input_pdf_path=sample_pdf)
        logger.info(f"Test translation completed with status: {success}")
    else:
        logger.warning(
            f"Sample file '{sample_pdf}' not found. "
            "Place a PDF in your working directory to run this test block."
        )

        
"""