"""
RockTranslate — Autonomous AI Translation Editor for TS Files
Path: dev_tools/translate_ts_files.py

This script reads raw QT .ts translation files, batches untranslated strings,
queries the Google Gemini API using native JSON Mode, and updates the XML templates
with high-fidelity translated text.

Usage:
    python translate_ts_files.py
"""

import os
import re
import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional


def load_api_key_from_env() -> Optional[str]:
    """
    Attempts to read GEMINI_API_KEY first from standard environment variables,
    then defensively parses the local root .env file if present.
    """
    # Try system environment first
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        return api_key

    # Corrected: Go up one directory (..) from 'dev_tools' to locate the root .env file
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env_path = os.path.join(project_root, ".env")
    
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        if key.strip() == "GEMINI_API_KEY":
                            return val.strip().strip('"').strip("'")
        except Exception as e:
            print(f"⚠️ Warning: Failed to parse local .env file: {e}")
            
    return None


def query_gemini_api(api_key: str, source_texts: List[str], target_lang: str) -> Dict[str, str]:
    """
    Sends a batch of source strings to Google Gemini using native JSON Mode
    and retrieves translation mappings.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    
    # Prompt instructing Gemini to return a clean JSON mapping
    prompt_instruction = (
        f"You are an expert software translation bot. Your task is to translate standard "
        f"desktop application GUI strings and parameters into {target_lang}.\n\n"
        f"Translate naturally and formally. Keep acronyms or paths in their original format.\n"
        f"Return ONLY a valid JSON dictionary mapping the original English keys to their "
        f"translated values. No explanations, no markdown wrappers, no conversational text."
    )
    
    # Formulate JSON payload
    payload = {
        "contents": [{
            "parts": [{
                "text": f"{prompt_instruction}\n\nList to translate:\n{json.dumps(source_texts, ensure_ascii=False)}"
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode("utf-8")
            res_json = json.loads(res_data)
            
            # Extract returned text portion containing the raw JSON
            raw_response_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(raw_response_text)
            
    except urllib.error.HTTPError as e:
        print(f"❌ API Error: Connection failed with code {e.code}. Details: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"❌ Parsing Error: Failed to decode Gemini payload: {e}")
        
    return {}


def translate_ts_file(api_key: str, ts_path: str, target_lang: str) -> None:
    """
    Parses a single QT .ts file, extracts unfinished message nodes,
    requests translations from Gemini, and saves updates.
    """
    if not os.path.exists(ts_path):
        print(f"⚠️ Warning: File not found at: {ts_path}")
        return

    print(f"📖 Processing: '{os.path.basename(ts_path)}' for target language: '{target_lang}'...")
    
    # Parse XML Tree structure
    try:
        tree = ET.parse(ts_path)
        root = tree.getroot()
    except Exception as e:
        print(f"❌ Error: Failed to parse XML structure: {e}")
        return

    # 1. Collect untranslated strings
    untranslated_elements = []
    untranslated_sources = []
    
    for msg in root.findall(".//message"):
        source = msg.find("source")
        translation = msg.find("translation")
        
        if source is not None and translation is not None:
            source_text = source.text
            if source_text and (translation.attrib.get("type") == "unfinished" or not translation.text):
                untranslated_elements.append((source_text, translation))
                untranslated_sources.append(source_text)

    if not untranslated_sources:
        print(f"✨ Perfect: No untranslated strings found in {os.path.basename(ts_path)}.")
        return

    print(f"🚀 Batching {len(untranslated_sources)} untranslated string(s) to Gemini API...")
    
    # 2. Query Gemini
    translations_dict = query_gemini_api(api_key, untranslated_sources, target_lang)
    
    if not translations_dict:
        print("❌ Error: Received empty translation payload from API.")
        return

    # 3. Inject translations back into the XML Tree
    success_count = 0
    for source_text, trans_node in untranslated_elements:
        translated_text = translations_dict.get(source_text)
        if translated_text:
            trans_node.text = translated_text
            # Remove the "unfinished" state flag to mark it as compiled-ready
            if "type" in trans_node.attrib:
                del trans_node.attrib["type"]
            success_count += 1

    # 4. Save XML changes back to disk
    try:
        # Preserve standard XML formatting header
        tree.write(ts_path, encoding="utf-8", xml_declaration=True)
        print(f"💾 Saved: Successfully updated {success_count} strings inside '{os.path.basename(ts_path)}'!")
    except Exception as e:
        print(f"❌ Error: Failed to save XML changes back to disk: {e}")


def main() -> None:
    """
    Main loop running translation passes sequentially over French, Spanish, and German locales.
    """
    print("🤖 RockTranslate AI-Editor: Starting translation pipeline...")
    
    api_key = load_api_key_from_env()
    if not api_key:
        print(
            "❌ Error: No GEMINI_API_KEY was found in your environment or local .env file.\n"
            "Please configure your API key first."
        )
        return

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ts_dir = os.path.join(project_root, "src", "assets", "translations")
    
    # Locale files and their explicit language mappings
    targets = [
        ("fr", "French"),
        ("es", "Spanish"),
        ("de", "German")
    ]
    
    for locale, lang_name in targets:
        ts_path = os.path.join(ts_dir, f"rocktranslate_{locale}.ts")
        translate_ts_file(api_key, ts_path, lang_name)
        print("-" * 60)
        
    print("🎉 All translation files processed successfully!")


if __name__ == "__main__":
    main()