"""
RockTranslate — Configurations and Credentials Web API Mixin
Path: src/rocktranslate/core/api/config_api.py

Manages system locale preferences, active provider credential statuses, and target
translation languages. Handles reading and writing system settings, API keys,
and translation engine parameters with strict error boundaries.

Author: RockTranslate Contributors
License: MIT License
Version: 1.1.0
"""

import re
import json
import time
import threading
import urllib.request
from loguru import logger
from typing import Dict, Any, Optional, List, Set
from ..config_manager import config_db
from ..constants import (
    DEFAULT_PROVIDERS,
    THRESHOLD_PX,
    SLIDING_CONTEXT_MAX_SIZE,
    MAX_SEGMENTS_PER_BATCH,
    MAX_RETRIES
)

# Tokens identifying non-chat models (audio, embeddings, moderators…) that are
# pointless for document translation and are excluded from suggestion lists.
_EXCLUDED_MODEL_TOKENS = (
    "audio", "transcribe", "tts", "whisper", "embedding", "moderation",
    "realtime", "live", "dall-e", "image", "rerank", "guard", "search",
    "computer-use", "video",
)

# Regex patterns matching obsolete models older than 1.5 years (2024 or earlier,
# or deprecated generations like gpt-4o, gpt-3.5, gemini-1.5, claude-3-opus, etc.).
_OBSOLETE_MODEL_PATTERNS = (
    r'-(?:2020|2021|2022|2023|2024)\d*',
    r'-(?:0314|0613|1106|0125)',
    r'^gpt-3',
    r'^gpt-4(?![.\d])',
    r'^gpt-4o',
    r'^chatgpt-4o',
    r'^o1-preview',
    r'^o1-mini',
    r'^o1$',
    r'^claude-[12]',
    r'^claude-3-(?:opus|sonnet|haiku)',
    r'^claude-3-5-(?:sonnet|haiku)',
    r'^claude-3\.5',
    r'^gemini-[12]\.',
    r'^gemini-exp',
    r'mixtral-8x[72][2b]',
    r'llama3-70b-8192',
    r'llama-3-8b',
    r'moonshot-v1',
)


def _is_obsolete_model(model_name: str) -> bool:
    """Checks if a model name corresponds to a deprecated model older than ~1.5 years."""
    if not model_name:
        return True
    return any(re.search(pat, model_name, re.IGNORECASE) for pat in _OBSOLETE_MODEL_PATTERNS)


# How long the persisted per-provider model cache stays authoritative (24h).
_MODEL_CACHE_TTL_SECONDS = 86400

# LiteLLM's live model database on GitHub: the same model_prices map the
# library itself auto-syncs from, updated upstream within hours of every new
# model release. Fetching it decouples the app's model knowledge from the
# frozen bundled registry of the installed litellm version.
_REMOTE_MODEL_DB_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
_REMOTE_SYNC_TIMEOUT_SECONDS = 6

# Guards against spawning several background syncs for the same provider.
_REMOTE_SYNC_IN_FLIGHT: Set[str] = set()
_REMOTE_SYNC_GUARD = threading.Lock()
_GLOBAL_STARTUP_SYNC_STARTED = False


class ConfigApiMixin:
    """
    Mixin class handling system preferences, active model parameters, 
    and LLM credentials status. Communicates directly with frontend JavaScript layers.
    """

    def get_system_locale(self) -> str:
        """
        Retrieves the persisted UI language preference of the application.

        Returns:
            str: The saved language code (e.g., 'en', 'fr'). Defaults to 'en'.
        """
        print(config_db)
        return str(config_db.get("SystemConfig", "ui_language", "en")).strip()

    def set_system_locale(self, locale_code: str) -> None:
        """
        Saves the preferred UI language code to persistent storage.

        Args:
            locale_code: The target language code (e.g., 'fr', 'es').
        """
        config_db.set("SystemConfig", "ui_language", str(locale_code).strip())
        print(f"[API] Saved system UI locale preference: {locale_code}")

    # ── TARGET TRANSLATION LANGUAGE SYNC (Cures the silent target language gap) ──
    def set_target_language(self, language_name: str) -> None:
        """
        Saves the target translation language to database configuration,
        and safely resets active translation states to prevent cross-language memory leaks.

        Args:
            language_name: The full string name of the target language (e.g., 'Spanish', 'German').
        """
        try:
            clean_lang = str(language_name).strip()
            # 1. Persist to disk instantly
            config_db.set("SystemConfig", "target_lang", clean_lang)
            
            # 2. Run reset within a defensive safety container
            if hasattr(self, "reset_all_translations"):
                try:
                    self.reset_all_translations()
                except Exception as reset_error:
                    # Ignore failures if no document is active or DOM is not parsed yet
                    logger.warning(f"[API] Silence reset_all_translations failure: {reset_error}")
        except Exception as e:
            logger.error(f"[API] Critical failure saving target language: {e}")

    def get_target_language(self) -> str:
        """Returns the currently saved target translation language."""
        lang = config_db.get("SystemConfig", "target_lang", "French")
        # Diagnostic Log
        print(f"[API DEBUG] get_target_language read value: '{lang}' (from file: {config_db.filepath})")
        return lang
    
    def get_api_status(self) -> Dict[str, Any]:
        """
        Fetches the connection status and name of the active LLM provider model.

        Returns:
            Dict[str, Any]: A dictionary containing active status, provider name, and model.
        """
        try:
            provider = config_db.get("APIConfig", "provider", "Google Gemini")
            keys_dict = config_db.get("APIConfig", "api_keys_by_provider", {})
            
            if not isinstance(keys_dict, dict):
                keys_dict = {}
                
            active_key = keys_dict.get(provider, "")
            fallback_model = DEFAULT_PROVIDERS.get(provider, {}).get("models", ["gemini-3.8-flash"])[0]
            model = config_db.get("APIConfig", f"last_model_{provider}", fallback_model)
            if _is_obsolete_model(model):
                model = fallback_model
            
            # Ollama operates offline without API keys; others require active credentials
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
            "model": "gemini-3.8-flash"
        }

    # ── SYSTEM & CACHE CONFIGURATIONS ──
    def get_system_settings(self) -> Dict[str, Any]:
        """
        Retrieves active local caches and path override parameters.

        Returns:
            Dict[str, Any]: Dictionary containing overrides and exit cache lifecycles.
        """
        return {
            "clear_cache_on_exit": config_db.get("SystemConfig", "clear_cache_on_exit", False),
            "pdf2htmlex_path_override": config_db.get("SystemConfig", "pdf2htmlex_path_override", ""),
            "pdfjs_path_override": config_db.get("SystemConfig", "pdfjs_path_override", "")
        }

    def save_system_settings(self, settings: Dict[str, Any]) -> Dict[str, str]:
        """
        Saves updated system settings and binary overrides to persistent database.

        Args:
            settings: Map holding user configured system fields.

        Returns:
            Dict[str, str]: Status payload ('success' or 'error' with message).
        """
        try:
            config_db.set("SystemConfig", "clear_cache_on_exit", bool(settings.get("clear_cache_on_exit", False)))
            config_db.set("SystemConfig", "pdf2htmlex_path_override", str(settings.get("pdf2htmlex_path_override", "")).strip())
            config_db.set("SystemConfig", "pdfjs_path_override", str(settings.get("pdfjs_path_override", "")).strip())
            return {"status": "success"}
        except Exception as error:
            return {"status": "error", "message": str(error)}

    # ── TRANSLATION ENGINE CONFIGURATIONS ──
    def get_translation_settings(self) -> Dict[str, Any]:
        """
        Retrieves active LLM parameters, temperature variables, and physical tolerances.

        Returns:
            Dict[str, Any]: Map of current active configuration parameters.
        """
        return {
            "temperature": config_db.get("TranslationConfig", "temperature", 1.0),
            "sliding_context_size": config_db.get("TranslationConfig", "sliding_context_size", SLIDING_CONTEXT_MAX_SIZE),
            "max_segments_per_batch": config_db.get("TranslationConfig", "max_segments_per_batch", MAX_SEGMENTS_PER_BATCH),
            "threshold_px": config_db.get("TranslationConfig", "threshold_px", THRESHOLD_PX),
            "max_retries": config_db.get("TranslationConfig", "max_retries", MAX_RETRIES),
            "custom_glossary": config_db.get("TranslationConfig", "custom_glossary", "")
        }

    def save_translation_settings(self, settings: Dict[str, Any]) -> Dict[str, str]:
        """
        Saves updated translation parameters and column division thresholds to database.

        Args:
            settings: Dictionary of updated parameter values.

        Returns:
            Dict[str, str]: Status dictionary response.
        """
        try:
            config_db.set("TranslationConfig", "temperature", float(settings.get("temperature", 1.0)))
            config_db.set("TranslationConfig", "sliding_context_size", int(settings.get("sliding_context_size", 5)))
            config_db.set("TranslationConfig", "max_segments_per_batch", int(settings.get("max_segments_per_batch", 60)))
            config_db.set("TranslationConfig", "threshold_px", float(settings.get("threshold_px", 12.0)))
            config_db.set("TranslationConfig", "max_retries", int(settings.get("max_retries", 4))),
            config_db.set("TranslationConfig", "custom_glossary", str(settings.get("custom_glossary", "")).strip()) 
            return {"status": "success"}
        except Exception as error:
            return {"status": "error", "message": str(error)}

    # ── DYNAMIC AI PROVIDERS & KEY MANAGERS ──
    def get_providers_config(self) -> Dict[str, Any]:
        """
        Exposes static provider configurations and suggested models.

        Returns:
            Dict[str, Any]: Provider profiles catalog dictionary.
        """
        return DEFAULT_PROVIDERS

    def get_available_models(self, provider: str) -> Dict[str, Any]:
        """
        Builds the up-to-date model list for a provider and never blocks:

        1. Serves the persisted cache instantly when fresh (24h TTL) — offline.
        2. Otherwise merges the curated defaults with the bundled LiteLLM
           registry of the installed version and returns immediately.
        3. Kicks a background thread that fetches LiteLLM's live model database
           from GitHub (the same file the library auto-syncs internally), so
           brand-new models (gemini-3.x, glm-5.x...) appear without upgrading
           litellm and without rebuilding the installer. On completion the
           refreshed list is persisted and pushed to the UI via the
           'models-refreshed' event.

        Args:
            provider: Provider display name (e.g. 'Google Gemini', 'OpenRouter').

        Returns:
            Dict[str, Any]: {'status', 'provider', 'models', 'source'} payload.
        """
        provider = str(provider)
        defaults: List[str] = list(DEFAULT_PROVIDERS.get(provider, {}).get("models", []))

        cached = config_db.get("ModelCache", provider, {})
        has_cache = isinstance(cached, dict) and bool(cached.get("models"))
        cache_fresh = has_cache and (
            time.time() - float(cached.get("fetched_at", 0)) < _MODEL_CACHE_TTL_SECONDS)

        if cache_fresh:
            return {
                "status": "success",
                "provider": provider,
                "models": cached["models"],
                "source": "cache"
            }

        # Stale or first run: best-available list right now (bundled registry
        # of the installed litellm + previous remote results + defaults).
        models = self._merge_model_lists(provider, defaults,
                                         cached.get("models") if has_cache else [])
        self._persist_model_cache(provider, models)

        # Schedule the non-blocking remote sync so new releases flow in.
        self._schedule_remote_model_sync(provider)

        return {
            "status": "success",
            "provider": provider,
            "models": models,
            "source": "stale-cache" if has_cache else "registry+defaults"
        }

    def _merge_model_lists(self, provider: str, defaults: List[str],
                           *extra_lists: Optional[List[str]]) -> List[str]:
        """
        Merges curated defaults, the bundled registry of the installed litellm
        and any previously fetched lists into one deduplicated, filtered list.
        """
        registry: List[str] = []
        try:
            import litellm
            model_cost = getattr(litellm, "model_cost", {}) or {}
            prefix = str(DEFAULT_PROVIDERS.get(provider, {}).get("prefix", ""))
            if provider != "Ollama (Local)":
                if prefix:
                    registry = [k[len(prefix):] for k in model_cost
                                if k.startswith(prefix) and len(k) > len(prefix)]
                else:
                    # OpenAI-family models are registered without provider prefix
                    registry = sorted(getattr(litellm, "models_by_provider", {}).get("openai", set()))
        except Exception as registry_error:
            logger.warning(f"[API] LiteLLM bundled registry unavailable for {provider}: {registry_error}")

        merged: List[str] = []
        for source_list in (defaults, *extra_lists, registry):
            if not source_list:
                continue
            for model in source_list:
                if not model or not isinstance(model, str):
                    continue
                if any(bad in model.lower() for bad in _EXCLUDED_MODEL_TOKENS):
                    continue
                if _is_obsolete_model(model):
                    continue
                if model not in merged:
                    merged.append(model)
        return merged

    def _schedule_remote_model_sync(self, provider: str) -> None:
        """
        Starts the background GitHub sync for a provider at most once at a time.
        Silent on failure: the bundled registry and cache always remain the
        fallback, which keeps the feature fully offline-safe.
        """
        with _REMOTE_SYNC_GUARD:
            if provider in _REMOTE_SYNC_IN_FLIGHT:
                return
            _REMOTE_SYNC_IN_FLIGHT.add(provider)

        thread = threading.Thread(
            target=self._remote_model_sync_worker,
            args=(provider,),
            name=f"model-sync-{provider}",
            daemon=True
        )
        thread.start()

    def _remote_model_sync_worker(self, provider: str) -> None:
        try:
            remote_models = self._fetch_remote_models(provider)
            if not remote_models:
                return

            defaults: List[str] = list(DEFAULT_PROVIDERS.get(provider, {}).get("models", []))
            cached = config_db.get("ModelCache", provider, {})
            previous = cached.get("models", []) if isinstance(cached, dict) else []
            models = self._merge_model_lists(provider, defaults, previous, remote_models)

            self._persist_model_cache(provider, models)

            # Live-update an open API config modal without any restart
            send_js = getattr(self, "_send_js", None)
            if callable(send_js):
                send_js(
                    "window.dispatchEvent(new CustomEvent('models-refreshed', { "
                    f"detail: {{ provider: {json.dumps(provider)}, "
                    f"models: {json.dumps(models)}, source: 'remote' }} }}))"
                )
            logger.info(f"[API] Remote model sync completed for {provider}: {len(models)} models.")
        except Exception as sync_error:
            logger.warning(f"[API] Remote model sync skipped for {provider}: {sync_error}")
        finally:
            with _REMOTE_SYNC_GUARD:
                _REMOTE_SYNC_IN_FLIGHT.discard(provider)

    def start_background_model_sync(self) -> None:
        """
        Launches an asynchronous background thread at software startup to automatically
        sync the up-to-date model catalog from LiteLLM into persistent cache (config_db).
        Runs completely non-blockingly. If offline, the cache and bundled registry
        serve the models seamlessly.
        """
        global _GLOBAL_STARTUP_SYNC_STARTED
        with _REMOTE_SYNC_GUARD:
            if _GLOBAL_STARTUP_SYNC_STARTED:
                return
            _GLOBAL_STARTUP_SYNC_STARTED = True

        thread = threading.Thread(
            target=self._startup_model_sync_worker,
            name="startup-model-catalog-sync",
            daemon=True
        )
        thread.start()

    def _startup_model_sync_worker(self) -> None:
        """
        Worker thread executed at software startup.
        Downloads LiteLLM's up-to-date model catalog from GitHub once,
        extracts modern models for every provider (pruning models >1.5 years old),
        and caches them locally.
        """
        logger.info("[API] Starting background LiteLLM model catalog sync at startup...")
        remote_data: Optional[Dict[str, Any]] = None
        try:
            req = urllib.request.Request(
                _REMOTE_MODEL_DB_URL,
                headers={"User-Agent": "RockTranslate/2.0.2"}
            )
            with urllib.request.urlopen(req, timeout=_REMOTE_SYNC_TIMEOUT_SECONDS) as response:
                content = response.read().decode("utf-8", errors="ignore")
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    remote_data = parsed
            logger.info(f"[API] LiteLLM live model catalog fetched ({len(remote_data)} total entries).")
        except Exception as e:
            logger.info(f"[API] Startup model remote sync offline or failed ({e}); using bundled/cached catalog.")

        for provider_name, provider_data in DEFAULT_PROVIDERS.items():
            try:
                defaults = list(provider_data.get("models", []))
                prefix = str(provider_data.get("prefix", ""))
                remote_models: List[str] = []

                if remote_data and provider_name != "Ollama (Local)":
                    for key in remote_data.keys():
                        if prefix:
                            if key.startswith(prefix) and len(key) > len(prefix):
                                remote_models.append(key[len(prefix):])
                        elif key.startswith("openai/") or "/" not in key:
                            remote_models.append(key.split("/")[-1] if key.startswith("openai/") else key)

                cached = config_db.get("ModelCache", provider_name, {})
                previous = cached.get("models", []) if isinstance(cached, dict) else []

                models = self._merge_model_lists(provider_name, defaults, previous, remote_models)
                self._persist_model_cache(provider_name, models)

                # If window is open, send notification for the active provider
                send_js = getattr(self, "_send_js", None)
                if callable(send_js):
                    active_provider = config_db.get("APIConfig", "provider", "Google Gemini")
                    if provider_name == active_provider:
                        send_js(
                            "window.dispatchEvent(new CustomEvent('models-refreshed', { "
                            f"detail: {{ provider: {json.dumps(provider_name)}, "
                            f"models: {json.dumps(models)}, source: 'startup-sync' }} }}))"
                        )
            except Exception as prov_err:
                logger.warning(f"[API] Startup sync error for {provider_name}: {prov_err}")

        logger.info("[API] Startup LiteLLM model catalog sync completed.")

    def _fetch_remote_models(self, provider: str) -> List[str]:
        """
        Downloads and filters LiteLLM's live model database for one provider.
        Raises on network failure (the caller treats that as 'keep fallback').
        """
        prefix = str(DEFAULT_PROVIDERS.get(provider, {}).get("prefix", ""))
        req = urllib.request.Request(_REMOTE_MODEL_DB_URL, headers={"User-Agent": "RockTranslate/2.0.2"})
        with urllib.request.urlopen(req, timeout=_REMOTE_SYNC_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8", errors="ignore"))
        if not isinstance(data, dict):
            return []

        models: List[str] = []
        for key in data.keys():
            if prefix:
                if key.startswith(prefix) and len(key) > len(prefix):
                    models.append(key[len(prefix):])
            elif key.startswith("openai/") or "/" not in key:
                # OpenAI-family models are registered without provider prefix
                models.append(key.split("/")[-1] if key.startswith("openai/") else key)

        return [
            m for m in models
            if m and not any(bad in m.lower() for bad in _EXCLUDED_MODEL_TOKENS)
            and not _is_obsolete_model(m)
        ]

    def _persist_model_cache(self, provider: str, models: List[str]) -> None:
        try:
            config_db.set("ModelCache", provider, {
                "models": models,
                "fetched_at": time.time()
            })
        except OSError as cache_error:
            logger.warning(f"[API] Could not persist model cache: {cache_error}")

    def force_model_refresh(self, provider: str) -> Dict[str, Any]:
        """
        Immediately fetches LiteLLM's live model database for one provider and
        returns the refreshed list (synchronous, wired to the modal's
        'Latest models' button). Falls back to the best available list —
        persisted cache or bundled registry — when offline.

        Args:
            provider: Provider display name.

        Returns:
            Dict[str, Any]: {'status', 'provider', 'models', 'source'} payload.
        """
        provider = str(provider)
        defaults: List[str] = list(DEFAULT_PROVIDERS.get(provider, {}).get("models", []))
        try:
            remote_models = self._fetch_remote_models(provider)
            if remote_models:
                cached = config_db.get("ModelCache", provider, {})
                previous = cached.get("models", []) if isinstance(cached, dict) else []
                models = self._merge_model_lists(provider, defaults, previous, remote_models)
                self._persist_model_cache(provider, models)
                return {"status": "success", "provider": provider,
                        "models": models, "source": "remote"}
        except Exception as sync_error:
            logger.warning(f"[API] Forced model refresh failed for {provider}: {sync_error}")

        # Offline fallback: serve the freshest list we already have
        models = self._merge_model_lists(provider, defaults,
                                         self._cached_models(provider))
        return {"status": "offline", "provider": provider,
                "models": models, "source": "cache"}

    def validate_custom_model(self, provider: str, model_id: str) -> Dict[str, Any]:
        """
        Checks a pasted model id against everything the app knows: the curated
        defaults, the persisted cache and the bundled LiteLLM registry. This is
        advisory only — a brand-new model absent from every list is still
        accepted with a warning, since registries always lag behind releases.

        Returns:
            Dict[str, Any]: {'status': 'known'|'unknown', 'model', 'message'}
        """
        provider = str(provider)
        model_id = str(model_id or "").strip()
        if not model_id:
            return {"status": "unknown", "model": "", "message": "empty"}

        prefix = str(DEFAULT_PROVIDERS.get(provider, {}).get("prefix", ""))
        bare = model_id[len(prefix):] if prefix and model_id.startswith(prefix) else model_id

        known = set(self._merge_model_lists(provider, list(
            DEFAULT_PROVIDERS.get(provider, {}).get("models", []))))
        known.update(self._cached_models(provider))
        if bare in known or model_id in known:
            return {"status": "known", "model": model_id, "message": "known"}

        return {"status": "unknown", "model": model_id, "message": "not-in-registry"}

    def _cached_models(self, provider: str) -> List[str]:
        cached = config_db.get("ModelCache", provider, {})
        if isinstance(cached, dict) and isinstance(cached.get("models"), list):
            return cached["models"]
        return []

    def get_api_config(self) -> Dict[str, Any]:
        """
        Fetches credentials and settings mapped individually for each AI provider.

        Returns:
            Dict[str, Any]: Nested dictionary containing configs and model keys.
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
                saved_model = config_db.get("APIConfig", f"last_model_{prov_name}", DEFAULT_PROVIDERS[prov_name]["models"][0])
                if _is_obsolete_model(saved_model):
                    saved_model = DEFAULT_PROVIDERS[prov_name]["models"][0]
                isolated_configs[prov_name] = {
                    "use_custom_base": config_db.get("APIConfig", f"use_custom_base_{prov_name}", False),
                    "custom_base_url": config_db.get(
                        "APIConfig", 
                        f"custom_base_url_{prov_name}", 
                        "http://localhost:11434" if prov_name == "Ollama (Local)" else ""
                    ),
                    "last_model": saved_model,
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
        """
        Saves customized model credentials, custom URLs, and provider keys to database.

        Args:
            config: Target dictionary layout payload containing active settings.

        Returns:
            Dict[str, str]: Status dictionary.
        """
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

    def reset_settings_to_default(self) -> Dict[str, str]:
        """
        Wipes active database settings files.

        Returns:
            Dict[str, str]: Status dictionary.
        """
        try:
            config_db.clear()
            return {"status": "success"}
        except Exception as error:
            return {"status": "error", "message": str(error)}