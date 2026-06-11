"""
RockTranslate — Universal, Resilient, and Multi-Provider LLM Client
Path: translation/llm_client.py

This module implements a robust, fault-tolerant translation wrapper based on LiteLLM.
It integrates automatic connection retry budgets (exponential backoff), 
rate-limit (429) wait recovery loops, and dynamic, provider-isolated model fallback.

All parsed JSON responses are processed through 'json_repair' to handle and correct 
minor syntactic deviations in model outputs automatically.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import time
from typing import Callable, Optional, List, Dict, Any, Tuple
from loguru import logger
import json_repair
from PyQt6.QtCore import QSettings
# Suppress verbose debug console logs from LiteLLM dependencies
try:
    import litellm
    litellm.suppress_debug_info = True
except ImportError:
    litellm = None

# Safe fallback imports supporting both standard package modules and direct scripts
try:
    from core.constants import DEFAULT_PROVIDERS, MAX_RETRIES, RETRY_DELAYS
    from translation.prompts import get_system_prompt, get_user_message
except ImportError:
    from src.core.constants import DEFAULT_PROVIDERS, MAX_RETRIES, RETRY_DELAYS
    from src.translation.prompts import get_system_prompt, get_user_message


class LLMClient:
    """
    Universal translation API wrapper utilizing LiteLLM.
    Handles rate limiting, temporary API failures, and provider-conformed fallbacks.
    """

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: Optional[str] = None,
        target_lang: str = "French",
        max_tokens: Optional[int] = None,
        custom_base_url: Optional[str] = None,
        all_keys: Optional[Dict[str, str]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Initializes the resilient LLM translation client.

        Args:
            model: Selected model routing string (e.g., 'gemini/gemini-2.5-flash').
            api_key: The API Key corresponding to the selected provider.
            target_lang: Complete text name of the target language (e.g., 'Spanish').
            max_tokens: Optional token ceiling limit.
            custom_base_url: Optional custom target API gateway (e.g., local Ollama port).
            all_keys: Dictionary holding all configured API credentials from UI settings.
            on_status: Callback routing live operation statuses to UI tracking elements.
        """
        self.model: str = model
        self.api_key: Optional[str] = api_key or self._get_api_key_from_env(model)
        self.target_lang: str = target_lang
        self.max_tokens: Optional[int] = max_tokens
        self.custom_base_url: Optional[str] = custom_base_url
        self.all_keys: Dict[str, str] = all_keys or {}
        self.on_status: Optional[Callable[[str], None]] = on_status

        if litellm is None:
            raise ImportError(
                "The 'litellm' library is required. Please install it via 'pip install litellm'."
            )

        logger.info(f"LLMClient initialized successfully: model='{self.model}' | target_lang='{self.target_lang}'")

    def _log_status(self, message: str) -> None:
        """ Notifies the UI status bar (via the callback) and logs debug info. """
        logger.info(message)
        if self.on_status:
            self.on_status(message)

    # ==============================================================================
    # PUBLIC TRANSLATION INTERFACE
    # ==============================================================================

    def translate_batch(
        self,
        batch_segments: List[Dict[str, str]],
        context: Optional[str] = None,
    ) -> Optional[List[Dict[str, str]]]:
        """
        Translates a batch of text segments, managing network failures,
        exponential delays, and automated provider-isolated fallbacks.

        Args:
            batch_segments: Payload segments list structure (e.g., [{"id": "g-0", "text": "..."}]).
            context: Sliding terminal context of translated paragraphs.

        Returns:
            Optional[List[Dict[str, str]]]: Translated segments output list or None.
        """
        current_model: str = self.model
        current_key: Optional[str] = self.api_key

        for attempt in range(MAX_RETRIES):
            try:
                # Trigger provider-safe dynamic fallback on repeated failures (attempts 3 and 4)
                if attempt >= 2:
                    fallback_model, fallback_key = self._get_fallback_model_and_key(current_model)
                    if fallback_model and fallback_key:
                        self._log_status(
                            f"🔄 Connection temporarily unavailable. "
                            f"Safely falling back to alternative model '{fallback_model}' "
                            f"from the same provider (Attempt {attempt + 1})..."
                        )
                        current_model = fallback_model
                        current_key = fallback_key

                # Perform raw API invocation
                results = self._call_llm(batch_segments, model=current_model, api_key=current_key, context=context)

                if results is not None:
                    return results

            except Exception as e:
                err_msg: str = str(e).lower()
                is_rate_limit: bool = any(
                    x in err_msg for x in [
                        "rate_limit", "rate limit", "429", "overloaded", "RESOURCE_EXHAUSTED",
                        "resource_exhausted", "resource exhausted", "quota",
                        "UNAVAILABLE", "503", "timeout", "timed out", "connection error",
                    ]
                )

                # Calculate exponential delay index matching RETRY_DELAYS bounds
                delay_index: int = min(attempt, len(RETRY_DELAYS) - 1)
                wait_time: float = RETRY_DELAYS[delay_index] * (attempt + 1)

                if is_rate_limit:
                    for remaining in range(int(wait_time), 0, -1):
                        self._log_status(
                            f"⏳ API quota or rate limits exceeded. Automatically retrying in {remaining}s..."
                        )
                        time.sleep(1)
                else:
                    self._log_status(
                        f"❌ Network connection error ({type(e).__name__}). Pausing for {int(wait_time)}s..."
                    )
                    time.sleep(wait_time)

        logger.error(f"Failed to translate target batch after {MAX_RETRIES} attempts.")
        return None

    def translate_single(self, text: str) -> str:
        """
        Translates a single raw string outside of the standard batch pipelines.

        Args:
            text: Raw string contents to translate.

        Returns:
            str: Translated text string.
        """
        batch_data: List[Dict[str, str]] = [{"id": "t-single", "text": text}]
        result = self.translate_batch(batch_data)
        if result and result[0].get("translated"):
            return result[0]["translated"]
        return f"[TRANSLATION FAILED] {text}"

    # ==============================================================================
    # INTERNAL COMPLETIONS & REPAIR ENGINES
    # ==============================================================================

    def _call_llm(
        self,
        batch_segments: List[Dict[str, str]],
        model: str,
        api_key: Optional[str],
        context: Optional[str] = None,
    ) -> Optional[List[Dict[str, str]]]:
        """ Executes standard completion payloads using the LiteLLM client router. """
        try:
            system_prompt: str = get_system_prompt(self.target_lang)
            user_message: str = get_user_message(batch_segments, context=context)

            translation_settings = QSettings("RockTranslate", "TranslationConfig")
            temperature = translation_settings.value("temperature", 1.0, type=float)

            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": temperature,
                "max_tokens": 16384,  # Budget to prevent response truncation
            }

            if api_key:
                kwargs["api_key"] = api_key
            
            # Integrate dynamic base URLs for custom target endpoints (e.g. Ollama)
            if self.custom_base_url:
                kwargs["api_base"] = self.custom_base_url

            response = litellm.completion(**kwargs)
            raw_text: str = response.choices[0].message.content.strip()
            return self._parse_json_response(raw_text)
            
        except Exception as e:
            logger.warning(f"Error during raw LiteLLM execution: {e}")
            return None

    def _parse_json_response(self, raw: str) -> Optional[List[Dict[str, str]]]:
        """
        Parses and cleans the raw JSON response returned by the LLM.
        Utilizes json_repair to handle and correct minor formatting/syntax issues.
        """
        cleaned: str = raw
        # Remove markdown block tags if present
        if "```" in cleaned:
            lines = cleaned.split("\n")
            cleaned = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            )
        cleaned = cleaned.strip()

        try:
            # Tolerates syntax anomalies and corrects missing braces/commas
            data = json_repair.loads(cleaned)
            if isinstance(data, list):
                return data
            logger.warning(f"Decoded JSON is valid but is not a list: {type(data)}")
            return None
        except Exception as e:
            logger.warning(f"Failed to parse or repair JSON response: {e}")
            
            # Sub-string backup search for brackets in case of preamble/postamble chatter
            start: int = cleaned.find("[")
            end: int = cleaned.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    repaired = json_repair.loads(cleaned[start:end + 1])
                    if isinstance(repaired, list):
                        return repaired
                except Exception:
                    pass
            return None

    def _get_fallback_model_and_key(self, current_model: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Dynamically determines a safer fallback model strictly restricted to the 
        active provider, ensuring API billings and keys remain within the same boundaries.

        Args:
            current_model: The routing name of the model that failed (e.g., 'gemini/gemini-2.5-flash-lite').

        Returns:
            Tuple[Optional[str], Optional[str]]: The alternative model name and its active API key if configured.
        """
        # 1. Identify which provider is currently running by checking prefixes
        active_provider: Optional[str] = None
        provider_config: Optional[Dict[str, Any]] = None
        
        for name, cfg in DEFAULT_PROVIDERS.items():
            prefix = cfg.get("prefix", "")
            if prefix and isinstance(prefix, str) and current_model.startswith(prefix):
                active_provider = name
                provider_config = cfg
                break
                
        if not active_provider or not provider_config:
            logger.warning(f"Could not resolve provider boundaries for model: {current_model}")
            return None, None

        # 2. Get the list of alternative models for this provider
        suggested_models: list = provider_config.get("models", [])
        prefix = provider_config.get("prefix", "")
        
        # Build fully qualified model paths (e.g., 'gemini/gemini-2.5-flash')
        qualified_models: List[str] = [
            f"{prefix}{m}" if not m.startswith(prefix) else m for m in suggested_models
        ]

        # 3. Locate the failing model in the chain to find subsequent alternatives
        candidates: List[str] = []
        try:
            current_idx = qualified_models.index(current_model)
            candidates = qualified_models[current_idx + 1:]
        except ValueError:
            # Fallback to the entire model sequence if the failing model is not in standard lists
            candidates = qualified_models

        # 4. Find the first candidate that has a valid API key configured
        key = self.all_keys.get(active_provider, self.api_key)
        
        for candidate in candidates:
            # Local Ollama doesn't require keys, others require valid credentials
            if active_provider == "Ollama (Local)" or key:
                return candidate, key

        return None, None

    @staticmethod
    def _get_api_key_from_env(model: str) -> Optional[str]:
        """ Retrieves standard credentials from active system environments dynamically. """
        model_lower = model.lower()
        if "gemini" in model_lower:
            return os.getenv("GEMINI_API_KEY")
        if "gpt" in model_lower or "openai" in model_lower:
            return os.getenv("OPENAI_API_KEY")
        if "claude" in model_lower or "anthropic" in model_lower:
            return os.getenv("ANTHROPIC_API_KEY")
        return None