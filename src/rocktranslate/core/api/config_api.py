"""
RockTranslate — Configurations and Credentials Web API Mixin
Path: src/rocktranslate/core/api/config_api.py

Manages system locale preferences and fetches active provider credential statuses.
Handles reading and writing system settings and translation engine settings.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.3
"""

import json # <--- ADD THIS IMPORT
from typing import Dict, Any
from ..config_manager import config_db
from ..constants import DEFAULT_PROVIDERS, THRESHOLD_PX, SLIDING_CONTEXT_MAX_SIZE, MAX_SEGMENTS_PER_BATCH, MAX_RETRIES


class ConfigApiMixin:
    """
    Mixin class handling system preferences and LLM credentials status.
    """
    def get_system_locale(self) -> str:
        return config_db.get("SystemConfig", "ui_language", "en")

    def set_system_locale(self, locale_code: str) -> None:
        config_db.set("SystemConfig", "ui_language", locale_code)
        print(f"[API] Saved system UI locale preference: {locale_code}")

    def get_api_status(self) -> Dict[str, Any]:
        try:
            provider = config_db.get("APIConfig", "provider", "Google Gemini")
            keys_dict = config_db.get("APIConfig", "api_keys_by_provider", {})
            
            if not isinstance(keys_dict, dict):
                keys_dict = {}
                
            active_key = keys_dict.get(provider, "")
            fallback_model = DEFAULT_PROVIDERS[provider]["models"][0]
            model = config_db.get("APIConfig", f"last_model_{provider}", fallback_model)
            is_active = bool(active_key) or provider == "Ollama (Local)"
            
            return {
                "active": is_active,
                "provider": provider,
                "model": model
            }
        except Exception as e:
            print(f"[API Error] Could not read API configuration status: {e}")
            
        return {
            "active": False,
            "provider": "Google Gemini",
            "model": "gemini-3.1-flash-lite"
        }

    # ── SYSTEM & CACHE CONFIGURATIONS ──
    def get_system_settings(self) -> Dict[str, Any]:
        return {
            "clear_cache_on_exit": config_db.get("SystemConfig", "clear_cache_on_exit", True),
            "pdf2htmlex_path_override": config_db.get("SystemConfig", "pdf2htmlex_path_override", ""),
            "pdfjs_path_override": config_db.get("SystemConfig", "pdfjs_path_override", "")
        }

    def save_system_settings(self, settings: Dict[str, Any]) -> Dict[str, str]:
        try:
            config_db.set("SystemConfig", "clear_cache_on_exit", bool(settings.get("clear_cache_on_exit", True)))
            config_db.set("SystemConfig", "pdf2htmlex_path_override", str(settings.get("pdf2htmlex_path_override", "")).strip())
            config_db.set("SystemConfig", "pdfjs_path_override", str(settings.get("pdfjs_path_override", "")).strip())
            return {"status": "success"}
        except Exception as error:
            return {"status": "error", "message": str(error)}

    # ── TRANSLATION ENGINE CONFIGURATIONS ──
    def get_translation_settings(self) -> Dict[str, Any]:
        return {
            "temperature": config_db.get("TranslationConfig", "temperature", 1.0),
            "sliding_context_size": config_db.get("TranslationConfig", "sliding_context_size", SLIDING_CONTEXT_MAX_SIZE),
            "max_segments_per_batch": config_db.get("TranslationConfig", "max_segments_per_batch", MAX_SEGMENTS_PER_BATCH),
            "threshold_px": config_db.get("TranslationConfig", "threshold_px", THRESHOLD_PX),
            "max_retries": config_db.get("TranslationConfig", "max_retries", MAX_RETRIES)
        }

    def save_translation_settings(self, settings: Dict[str, Any]) -> Dict[str, str]:
        try:
            config_db.set("TranslationConfig", "temperature", float(settings.get("temperature", 1.0)))
            config_db.set("TranslationConfig", "sliding_context_size", int(settings.get("sliding_context_size", 5)))
            config_db.set("TranslationConfig", "max_segments_per_batch", int(settings.get("max_segments_per_batch", 60)))
            config_db.set("TranslationConfig", "threshold_px", float(settings.get("threshold_px", 12.0)))
            config_db.set("TranslationConfig", "max_retries", int(settings.get("max_retries", 4)))
            return {"status": "success"}
        except Exception as error:
            return {"status": "error", "message": str(error)}

    # ── DYNAMIC AI PROVIDERS & KEY MANAGERS ──
    def get_providers_config(self) -> Dict[str, Any]:
        return DEFAULT_PROVIDERS

    def get_api_config(self) -> Dict[str, Any]:
        """
        Fetches all active provider credentials and isolated configurations with safe error containment.
        """
        try:
            provider = config_db.get("APIConfig", "provider", "Google Gemini")
            keys_dict = config_db.get("APIConfig", "api_keys_by_provider", {})
            
            if isinstance(keys_dict, str):
                try:
                    keys_dict = json.loads(keys_dict)
                except Exception:
                    keys_dict = {}
            elif not isinstance(keys_dict, dict):
                keys_dict = {}

            isolated_configs = {}
            for prov_name in DEFAULT_PROVIDERS.keys():
                isolated_configs[prov_name] = {
                    "use_custom_base": config_db.get("APIConfig", f"use_custom_base_{prov_name}", False),
                    "custom_base_url": config_db.get(
                        "APIConfig", 
                        f"custom_base_url_{prov_name}", 
                        "http://localhost:11434" if prov_name == "Ollama (Local)" else ""
                    ),
                    "last_model": config_db.get("APIConfig", f"last_model_{prov_name}", DEFAULT_PROVIDERS[prov_name]["models"][0]),
                    "api_key": keys_dict.get(prov_name, "")
                }

            return {
                "current_provider": provider,
                "isolated_configs": isolated_configs
            }
        except Exception as e:
            print(f"[API Error] Critical bridge failure in get_api_config: {e}")
            return {"current_provider": "Google Gemini", "isolated_configs": {}}

    def save_api_config(self, config: Dict[str, Any]) -> Dict[str, str]:
        try:
            current_provider = config.get("current_provider", "Google Gemini")
            isolated_configs = config.get("isolated_configs", {})

            config_db.set("APIConfig", "provider", current_provider)

            keys_dict = {}
            for prov_name, prov_data in isolated_configs.items():
                config_db.set("APIConfig", f"use_custom_base_{prov_name}", bool(prov_data.get("use_custom_base", False)))
                config_db.set("APIConfig", f"custom_base_url_{prov_name}", str(prov_data.get("custom_base_url", "")).strip())
                config_db.set("APIConfig", f"last_model_{prov_name}", str(prov_data.get("last_model", "")).strip())
                
                if prov_name != "Ollama (Local)":
                    keys_dict[prov_name] = str(prov_data.get("api_key", "")).strip()

            config_db.set("APIConfig", "api_keys_by_provider", keys_dict)

            active_data = isolated_configs.get(current_provider, {})
            config_db.set("APIConfig", "use_custom_base", bool(active_data.get("use_custom_base", False)))
            config_db.set("APIConfig", "custom_base_url", str(active_data.get("custom_base_url", "")).strip())

            return {"status": "success"}
        except Exception as error:
            return {"status": "error", "message": str(error)}
    

    def get_target_language(self) -> str:
        """Returns the currently saved target translation language."""
        return config_db.get("SystemConfig", "target_lang", "French")

    def set_target_language(self, lang: str) -> None:
        """Persists the user-selected target translation language."""
        config_db.set("SystemConfig", "target_lang", lang)


    def reset_settings_to_default(self) -> Dict[str, str]:
        try:
            config_db.clear()
            return {"status": "success"}
        except Exception as error:
            return {"status": "error", "message": str(error)}