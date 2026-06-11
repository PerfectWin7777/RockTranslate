"""
RockTranslate — Standalone Command Line Interface (CLI) Entry Point
Path: src/cli/cli.py

This module implements the lightweight, Qt-free CLI execution engine. It handles
asynchronous batching, offline HTML DOM translated text injection via BeautifulSoup,
and headless system browser-based print-to-PDF compilation.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import sys

# ── DYNAMIC SYSTEM PATH RESOLUTION ──
# Resolves search paths so that subscripts run directly without ModuleNotFound errors
current_dir = os.path.dirname(os.path.abspath(__file__))  # src/cli
src_dir = os.path.dirname(current_dir)                    # src
project_root = os.path.dirname(src_dir)                   # Project root

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# ────────────────────────────────────


import re
import json
import shutil
import argparse
import tempfile
import subprocess
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup

# Exclude heavy PyQt GUI modules from standard library requirements
try:
    from core.constants import DEFAULT_ASSETS_DIR, THRESHOLD_PX, SLIDING_CONTEXT_MAX_SIZE, MAX_SEGMENTS_PER_BATCH, MAX_RETRIES
    from core.html_transformer import convert_pdf_to_html, instrument_html
    from translation.chunker import build_batches, Batch
    from translation.llm_client import LLMClient
    from utils.pdf_metadata import get_pdf_metadata
except ImportError:
    from src.core.constants import DEFAULT_ASSETS_DIR, THRESHOLD_PX, SLIDING_CONTEXT_MAX_SIZE, MAX_SEGMENTS_PER_BATCH, MAX_RETRIES
    from src.core.html_transformer import convert_pdf_to_html, instrument_html
    from src.translation.chunker import build_batches, Batch
    from src.translation.llm_client import LLMClient
    from src.utils.pdf_metadata import get_pdf_metadata

# Only import winreg on Windows platforms to query installed internet browser registries
if sys.platform == "win32":
    import winreg
else:
    winreg = None


def get_safe_setting(config_scope: str, key: str, fallback_default: Any) -> Any:
    """
    Safely retrieves a user configuration. 
    If PyQt6 is installed in the active environment, it queries QSettings.
    If PyQt6 is missing (CLI-only installation), it silently falls back 
    to the provided default value without raising ImportErrors.
    """
    try:
        from PyQt6.QtCore import QSettings
        settings = QSettings("RockTranslate", config_scope)
        val = settings.value(key, fallback_default)
        if isinstance(fallback_default, bool):
            return str(val).lower() in ("true", "1", "yes")
        if isinstance(fallback_default, int):
            return int(val)
        if isinstance(fallback_default, float):
            return float(val)
        return val
    except ImportError:
        return fallback_default


def find_system_chromium_browser() -> Optional[str]:
    """
    Scans the local operating system to discover the absolute path
    of the first available Chromium-based browser (Chrome, Edge, or Chromium).
    Filters out non-Chromium browsers like Firefox to prevent printing hangs.
    """
    # 1. Search the system environment PATH (works perfectly on Linux/macOS)
    common_commands = [
        "google-chrome", "chrome", "chromium", 
        "chromium-browser", "microsoft-edge", "msedge"
    ]
    for cmd in common_commands:
        resolved_path = shutil.which(cmd)
        if resolved_path:
            return resolved_path

    # 2. Search Windows Registry if running on Win32
    if sys.platform == "win32" and winreg:
        registry_path = r"SOFTWARE\Clients\StartMenuInternet"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as hkey:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(hkey, index)
                        index += 1
                        cmd_path = rf"{registry_path}\{subkey_name}\shell\open\command"
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cmd_path) as command_key:
                            raw_command, _ = winreg.QueryValueEx(command_key, "")
                            if raw_command:
                                clean_path = raw_command.strip().strip('"')
                                if " -osint" in clean_path:
                                    clean_path = clean_path.split(" -osint")[0].strip('"')
                                
                                # --- FILTER FIX: Only accept Chromium-based browsers ---
                                clean_path_lower = clean_path.lower()
                                if any(x in clean_path_lower for x in ["chrome", "edge", "chromium", "brave"]):
                                    if os.path.exists(clean_path):
                                        return clean_path
                    except OSError as e:
                        if e.winerror == 259:  # No more registry subkeys
                            break
                        raise
        except Exception:
            pass

    # 3. Search standard app bundles on macOS
    elif sys.platform == "darwin":
        mac_apps = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        ]
        for path in mac_apps:
            if os.path.exists(path):
                return path
                
    return None



def apply_translations_offline(input_html_path: str, output_html_path: str, 
                               translations: Dict[str, str], page_size_css: str = "A4") -> None:
    """
    Injects the translated segments dictionary into a script tag at the bottom of the HTML.
    Appends an automated headless execution hook that triggers the original scale-compression
    and layout engine inside Chrome before compiling the PDF.
    """
    with open(input_html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Formulate the JSON translations payload
    # Formulate the JSON translations payload
    translations_json = json.dumps(translations, ensure_ascii=False)

    # Force the exact physical page size of the original PDF during headless printing
    page_size_style = f"""
    <style>
    @page {{
        size: {page_size_css};
        margin: 0;
    }}
    body {{
        margin: 0;
        padding: 0;
    }}
    </style>
    """

    # Embedded Javascript execution hook to trigger pixel-perfect scaling inside headless Chrome
    automated_hook_script = f"""
    <script>
    var cliTranslations = {translations_json};
    window.addEventListener('load', function() {{
        // Fast-hide all pending visual glass overlays
        document.querySelectorAll('[id^="glass-overlay-t-"]').forEach(function(glass) {{
            glass.style.display = 'none';
        }});
        
        // Execute the native scale-compression engine for every translated element
        for (var transId in cliTranslations) {{
            if (window.applyTranslation) {{
                window.applyTranslation(transId, cliTranslations[transId]);
            }}
        }}
        
        // Clean up remaining visual shimmer loader styles
        document.querySelectorAll('.shimmer-line').forEach(function(el) {{
            el.classList.remove('shimmer-line');
        }});
    }});
    </script>
    """

    # Inject page size style in head, and translation script in body
    optimized_html = html_content.replace("</head>", f"{page_size_style}\n</head>")
    optimized_html = optimized_html.replace("</body>", f"{automated_hook_script}\n</body>")

    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(optimized_html)




def print_html_to_vector_pdf(browser_path: str, input_html_path: str, output_pdf_path: str) -> bool:
    """
    Executes a headless background process using the resolved browser
    to print the translated HTML into a high-fidelity vector PDF.
    """
    if not os.path.exists(input_html_path):
        return False
        
    cmd = [
        browser_path,
        "--headless",
        "--disable-gpu",
        "--no-margins",               
        "--no-pdf-header-footer",
        f"--print-to-pdf={os.path.abspath(output_pdf_path)}",
        os.path.abspath(input_html_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def main() -> None:
    """
    Primary CLI execution loop. Resolves arguments, queries API batches,
    applies translations offline, and compiles the final vector PDF.
    """
    parser = argparse.ArgumentParser(
        description="RockTranslate: High-Fidelity AI Layout-Preserved PDF Translator."
    )
    parser.add_argument("input", help="Path to the source scientific PDF file to translate.")
    parser.add_argument("-l", "--lang", default="French", help="Target language (default: French).")
    parser.add_argument("-o", "--output", help="Output path for the translated PDF.")
    parser.add_argument("-m", "--model", help="Target LLM model (e.g., gemini/gemini-2.5-flash-lite).")
    parser.add_argument("-k", "--api-key", help="API Key override.")
    parser.add_argument("-t", "--temp", type=float, help="Model temperature (0.0 to 2.0).")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input) or not args.input.lower().endswith(".pdf"):
        print(f"❌ Error: Invalid input PDF path: {args.input}")
        sys.exit(1)

    print("🔍 Inspecting system environment for available headless browser engines...")
    browser_path = find_system_chromium_browser()
    if not browser_path:
        print(
            "❌ Error: No compatible Chromium-based browser (Chrome, Edge, or Chromium) was found.\n"
            "A system browser is required to export high-fidelity vector PDFs in CLI mode.\n"
            "Please install Google Chrome or Microsoft Edge and try again."
        )
        sys.exit(1)
        
    print(f"   -> Discovered browser: '{os.path.basename(browser_path)}'")

    # Load dynamic configurations safely
    temp = args.temp or get_safe_setting("TranslationConfig", "temperature", 1.0)
    max_retries = get_safe_setting("TranslationConfig", "max_retries", MAX_RETRIES)
    max_batch_size = get_safe_setting("TranslationConfig", "max_segments_per_batch", MAX_SEGMENTS_PER_BATCH)
    
    # Resolve API credentials
    api_settings = get_safe_setting("APIConfig", "api_keys_by_provider", "{}")
    try:
        keys_dict = json.loads(api_settings) if isinstance(api_settings, str) else api_settings
    except Exception:
        keys_dict = {}

    model_name = args.model
    if not model_name:
        provider = get_safe_setting("APIConfig", "provider", "Google Gemini")
        model_name = get_safe_setting("APIConfig", f"last_model_{provider}", "gemini-3.1-flash-lite")
        if provider == "Google Gemini" and not model_name.startswith("gemini/"):
            model_name = f"gemini/{model_name}"

    api_key = args.api_key
    if not api_key:
        # Search env space, then standard fallbacks
        api_key = os.getenv("GEMINI_API_KEY") or keys_dict.get("Google Gemini", "")

    if not api_key and "ollama" not in model_name.lower():
        print(f"❌ Error: Missing API Key for model: {model_name}. Please specify -k or set your env variables.")
        sys.exit(1)

    print(f"📄 Processing document: '{os.path.basename(args.input)}'")
    print(f"🤖 LLM Target: '{model_name}' | Language: '{args.lang}' | Temperature: {temp}")

    # Use a temporary directory to compile intermediate HTML files
    with tempfile.TemporaryDirectory() as temp_dir:
        raw_html_path = os.path.join(temp_dir, "raw.html")
        workspace_html_path = os.path.join(temp_dir, "workspace.html")
        translated_html_path = os.path.join(temp_dir, "translated.html")

        # Step 1: Geometric layout conversion via local pdf2htmlEX
        print("⚡ Extracting physical PDF layout coordinates (pdf2htmlEX)...")
        convert_pdf_to_html(args.input, DEFAULT_ASSETS_DIR)
        
        # Determine raw output name
        pdf_dir = os.path.dirname(os.path.abspath(args.input))
        pdf_basename = os.path.splitext(os.path.basename(args.input))[0]
        generated_raw = os.path.join(pdf_dir, f"{pdf_basename}_raw.html")
        
        if not os.path.exists(generated_raw):
            print("❌ Error: Geometric conversion failed.")
            sys.exit(1)
            
        shutil.move(generated_raw, raw_html_path)

        # Step 2: Semantic HTML DOM instrumentation
        print("🧩 Segmenting DOM structures into translatable blocks...")
        original_texts, tid_to_page = instrument_html(raw_html_path, workspace_html_path)

        # Step 3: Build token-controlled batches
        print("📦 Building optimized translation batches...")
        batches = build_batches(original_texts, model_name)
        total_batches = len(batches)

        # --- NEW: Retrieve original PDF page dimensions dynamically ---
        metadata = get_pdf_metadata(args.input)
        page_size_raw = metadata.get("page_size", "")  # e.g., "[21.00 x 29.70 cm]"
        
        # Extract numerical width and height using regex
        match = re.search(r'\[([\d\.]+)\s*x\s*([\d\.]+)\s*cm\]', page_size_raw)
        if match:
            width_cm = float(match.group(1))
            height_cm = float(match.group(2))
            page_size_css = f"{width_cm}cm {height_cm}cm"
        else:
            page_size_css = "A4"  # Safe standard fallback

        # Step 4: Execute API translations
        client = LLMClient(
            model=model_name,
            api_key=api_key,
            target_lang=args.lang,
            all_keys=keys_dict
        )

        translated_results: Dict[str, str] = {}
        
        # Bypass equations/digits directly in the CLI as well
        translatable_ids = set()
        for b in batches:
            translatable_ids.update(b.ids)
            
        skipped_ids = set(original_texts.keys()) - translatable_ids
        for skip_id in skipped_ids:
            translated_results[skip_id] = original_texts[skip_id]

        print(f"🔄 Translating {len(translatable_ids)} segment(s) in {total_batches} batch(es)...")
        
        for idx, batch in enumerate(batches):
            sys.stdout.write(f"\r[CLI] Batch progress: {idx + 1}/{total_batches}...")
            sys.stdout.flush()
            
            results = client.translate_batch(batch.segments)
            if results is None:
                print("\n❌ Error: Translation interrupted due to connection issues.")
                sys.exit(1)
                
            for res in results:
                seg_id = res.get("id")
                translated_text = res.get("translated")
                if seg_id and translated_text:
                    translated_results[seg_id] = translated_text

        sys.stdout.write("\n")
        print("✅ Translation batches completed successfully.")

        # Step 5: Inject translations back into the HTML offline
        print("🪡 Rebuilding HTML DOM with translation overlays...")
        apply_translations_offline(workspace_html_path, translated_html_path, translated_results, page_size_css)

        # Step 6: Export final vector PDF
        output_pdf = args.output or os.path.join(pdf_dir, f"{pdf_basename}_translated.pdf")
        print("🖨️ Headless Chromium vector printing in progress...")
        
        if print_html_to_vector_pdf(browser_path, translated_html_path, output_pdf):
            print(f"🎉 Success! Translated vector PDF saved at: '{output_pdf}'")
        else:
            print("❌ Error: Vector PDF printing failed.")
            sys.exit(1)


if __name__ == "__main__":
    main()