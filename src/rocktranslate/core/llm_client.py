"""
RockTranslate — Universal, Resilient, and Multi-Provider LLM Client
Path: src/rocktranslate/core/llm_client.py

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
import re
import threading
import time
from typing import Callable, Optional, List, Dict, Any, Tuple
from loguru import logger
import json_repair

# Suppress verbose debug console logs from LiteLLM dependencies
try:
    import litellm
    litellm.suppress_debug_info = True
except ImportError:
    litellm = None

# Safe imports supporting both standard package modules and direct scripts
from .constants import (
    DEFAULT_PROVIDERS, MAX_RETRIES, RETRY_DELAYS, DEFAULT_MODEL,
    DEFAULT_TEMPERATURE, REQUEST_TIMEOUT_SECONDS,
)
from .prompts import get_system_prompt, get_user_message
from .config_manager import config_db

def _copies_source(source: str, translated: str, run: int = 10) -> bool:
    """True when the output repeats >= `run` consecutive words of the source."""
    def words(t: str) -> list:
        return re.findall(r"[^\W\d_]+", re.sub(r"</?[a-z_0-9]+>", " ", t).lower())
    src, out = words(source), words(translated)
    if len(src) < run or len(out) < run:
        return False
    grams = {tuple(src[i:i + run]) for i in range(len(src) - run + 1)}
    covered = [False] * len(out)
    for i in range(len(out) - run + 1):
        if tuple(out[i:i + run]) in grams:
            for j in range(i, i + run):
                covered[j] = True
    ratio = sum(covered) / len(out)
    # Fully copied text (references, names, already-target-language text) is
    # accepted; only a PARTIAL copy means the model gave up halfway.
    return 0.15 <= ratio < 0.9


class LLMClient:
    """
    Universal translation API wrapper utilizing LiteLLM.
    Handles rate limiting, temporary API failures, and provider-conformed fallbacks.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        target_lang: str = "French",
        max_tokens: Optional[int] = None,
        custom_base_url: Optional[str] = None,
        all_keys: Optional[Dict[str, str]] = None,
        custom_glossary: Optional[str] = None,
        on_status: Optional[Callable[[str], None]] = None,
        temperature: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        """
        Initializes the resilient LLM translation client.

        Args:
            model: Selected model routing string (e.g., 'gemini/gemini-3.8-flash').
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
        self.custom_glossary: Optional[str] = custom_glossary 
        self.on_status: Optional[Callable[[str], None]] = on_status
        # Explicit values (library/CLI) win over the GUI config file
        self.temperature: Optional[float] = temperature
        self.max_retries: Optional[int] = max_retries

        # Cumulative usage of this client (tokens + estimated USD cost)
        self.usage: Dict[str, Any] = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        self._usage_lock = threading.Lock()

        if litellm is None:
            raise ImportError(
                "The 'litellm' library is required. Please install it via 'pip install litellm'."
            )

        logger.info(f"LLMClient initialized successfully: model='{self.model}' | target_lang='{self.target_lang}'")
    
    

    def _log_status(self, message: str, key: Optional[str] = None, variables: Optional[Dict[str, Any]] = None) -> None:
        """
        Logs the (English) message and notifies the UI status bar. With an i18n
        key, the UI shows the message in the interface language instead.
        """
        logger.info(message)
        if self.on_status:
            try:
                self.on_status(message, key, variables or {})
            except TypeError:  # legacy single-argument callbacks
                self.on_status(message)

    # ==============================================================================
    # PUBLIC TRANSLATION INTERFACE
    # ==============================================================================

    def translate_batch(
        self,
        batch_segments: List[Dict[str, str]],
        context: Optional[str] = None,
        check_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Optional[List[Dict[str, str]]]:
        """
        Translates a batch of segments with real exponential backoff, rate-limit
        waits, provider-isolated fallback and output validation.

        The returned list only contains ids that belong to the batch (hallucinated
        ids are dropped). Segments the model silently omitted are re-requested
        once as a smaller follow-up batch.

        Returns:
            The translated segments ([{"id", "translated"}]) or None on failure.
        """
        results = self._translate_with_retries(batch_segments, context, check_cancelled)
        if results is None:
            return None

        expected_ids = [seg["id"] for seg in batch_segments]
        by_id = self._index_valid_results(results, set(expected_ids))
        sources = {seg["id"]: seg["text"] for seg in batch_segments}
        # Partially translated outputs (the model copied the end of the source)
        # are treated like omissions and go through the retry path.
        for seg_id in [k for k, v in by_id.items() if _copies_source(sources.get(k, ""), v)]:
            logger.warning(f"Segment {seg_id} came back partly untranslated; retrying it.")
            del by_id[seg_id]

        missing = [seg for seg in batch_segments if seg["id"] not in by_id]
        if missing and not (check_cancelled and check_cancelled()):
            logger.warning(f"Model omitted {len(missing)} segment(s); re-requesting them once.")
            retry = self._translate_with_retries(missing, context, check_cancelled)
            if retry:
                by_id.update(self._index_valid_results(retry, {seg["id"] for seg in missing}))

        # Last resort: segments still omitted are sent ONE BY ONE (a model that
        # keeps skipping an item inside a list almost always answers a single one).
        still_missing = [seg for seg in batch_segments if seg["id"] not in by_id]
        for seg in still_missing[:8]:
            if check_cancelled and check_cancelled():
                break
            single = self._translate_with_retries([seg], context, check_cancelled)
            if single:
                by_id.update(self._index_valid_results(single, {seg["id"]}))
        if still_missing and any(seg["id"] not in by_id for seg in still_missing):
            logger.warning("Some segments could not be translated; they stay in the source language.")

        return [{"id": seg_id, "translated": by_id[seg_id]} for seg_id in expected_ids if seg_id in by_id]

    @staticmethod
    def _index_valid_results(results: List[Any], allowed_ids: set) -> Dict[str, str]:
        """Keeps well-formed results whose id belongs to the request."""
        valid: Dict[str, str] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            seg_id = item.get("id")
            text = item.get("translated")
            if isinstance(seg_id, str) and seg_id in allowed_ids and isinstance(text, str) and text.strip():
                valid[seg_id] = text.strip()
        return valid

    def _translate_with_retries(
        self,
        batch_segments: List[Dict[str, str]],
        context: Optional[str],
        check_cancelled: Optional[Callable[[], bool]],
    ) -> Optional[List[Dict[str, Any]]]:
        current_model: str = self.model
        current_key: Optional[str] = self.api_key
        max_retries = max(1, int(self.max_retries if self.max_retries is not None
                                 else config_db.get("TranslationConfig", "max_retries", MAX_RETRIES)))

        for attempt in range(max_retries):
            if check_cancelled and check_cancelled():
                self._log_status("Translation batch aborted: cancellation requested.", "llm_cancelled")
                return None

            # Provider-isolated fallback on the last attempts only
            if attempt >= 2:
                fallback_model, fallback_key = self._get_fallback_model_and_key(current_model)
                if fallback_model and fallback_model != current_model:
                    self._log_status(
                        f"🔄 '{current_model}' keeps failing: switching to '{fallback_model}' "
                        f"from the same provider (attempt {attempt + 1}/{max_retries}).",
                        "llm_model_fallback",
                        {"from": current_model, "to": fallback_model, "attempt": attempt + 1, "max": max_retries},
                    )
                    current_model, current_key = fallback_model, fallback_key

            error: Optional[Exception] = None
            try:
                results = self._call_llm(batch_segments, model=current_model, api_key=current_key, context=context)
                if results is not None:
                    return results
                logger.warning(f"Unparseable model output (attempt {attempt + 1}/{max_retries}).")
            except Exception as e:  # network, auth, rate limit, timeout...
                error = e
                logger.warning(f"LLM call failed ({type(e).__name__}): {str(e)[:300]}")

            if error is not None and self._is_fatal_error(error):
                self._log_status(f"❌ {type(error).__name__}: {str(error)[:200]}", "llm_error", {"error": type(error).__name__})
                return None
            if attempt == max_retries - 1:
                break

            delay_index = min(attempt, len(RETRY_DELAYS) - 1)
            wait_time = RETRY_DELAYS[delay_index] * (attempt + 1)
            if error is None:
                wait_time = 1.0  # unparseable JSON: retry quickly
            elif self._is_rate_limit_error(error):
                wait_time *= 2
                self._log_status(f"⏳ Rate limit or quota reached. Retrying in {int(wait_time)}s...", "llm_rate_limit", {"seconds": int(wait_time)})
            else:
                self._log_status(f"❌ API error ({type(error).__name__}). Retrying in {int(wait_time)}s...", "llm_api_retry", {"error": type(error).__name__, "seconds": int(wait_time)})

            deadline = time.monotonic() + wait_time
            while time.monotonic() < deadline:
                if check_cancelled and check_cancelled():
                    return None
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

        logger.error(f"Failed to translate batch after {max_retries} attempts.")
        return None

    @staticmethod
    def _is_rate_limit_error(error: Exception) -> bool:
        msg = f"{type(error).__name__} {error}".lower()
        return any(x in msg for x in (
            "ratelimit", "rate_limit", "rate limit", "429", "overloaded",
            "resource_exhausted", "resource exhausted", "quota", "unavailable", "503",
        ))

    @staticmethod
    def _is_fatal_error(error: Exception) -> bool:
        """Errors that retrying cannot fix (bad key, unknown model, no balance)."""
        if LLMClient._is_rate_limit_error(error):
            return False
        msg = f"{type(error).__name__} {error}".lower()
        return any(x in msg for x in (
            "authenticationerror", "invalid api key", "incorrect api key",
            "permissiondenied", "notfounderror", "model not found", "does not exist",
            "insufficient balance", "insufficient_quota",
        ))

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
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Executes one completion. Network/API errors are RAISED so the retry
        loop can apply backoff; None means the output could not be parsed.
        """
        system_prompt: str = get_system_prompt(self.target_lang, self.custom_glossary)
        user_message: str = get_user_message(batch_segments, context=context)

        temperature = (self.temperature if self.temperature is not None
                       else float(config_db.get("TranslationConfig", "temperature", DEFAULT_TEMPERATURE)))
        timeout = float(config_db.get("TranslationConfig", "request_timeout", REQUEST_TIMEOUT_SECONDS))

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": self._output_token_budget(model),
            "timeout": timeout,
        }
        if api_key:
            kwargs["api_key"] = api_key
        # Translation gains nothing from hidden "thinking" tokens: measured on
        # DeepSeek-V4.1-Flash, disabling them is ~5x faster and ~4x cheaper with
        # the same output. Providers rejecting the flag are retried without it.
        no_thinking = self._no_thinking_kwargs(model)
        if no_thinking and model not in LLMClient._thinking_flag_rejected:
            kwargs.update(no_thinking)
        # Integrate dynamic base URLs for custom target endpoints (e.g. Ollama)
        if self.custom_base_url:
            kwargs["api_base"] = self.custom_base_url

        try:
            response = litellm.completion(**kwargs)
        except Exception as e:
            if no_thinking and any(k in kwargs for k in no_thinking) and "thinking" in str(e).lower():
                logger.info(f"'{model}' rejects the no-thinking flag; continuing without it.")
                LLMClient._thinking_flag_rejected.add(model)
                for k in no_thinking:
                    kwargs.pop(k, None)
                response = litellm.completion(**kwargs)
            else:
                raise
        self._record_usage(response, model)
        raw_text: str = (response.choices[0].message.content or "").strip()
        return self._parse_json_response(raw_text)

    # Models that returned an error for the no-thinking flag (process-wide)
    _thinking_flag_rejected: set = set()

    @staticmethod
    def _no_thinking_kwargs(model: str) -> Dict[str, Any]:
        """Provider-specific arguments disabling hidden reasoning, if supported."""
        if not bool(config_db.get("TranslationConfig", "disable_reasoning", True)):
            return {}
        name = model.lower()
        if name.startswith("deepseek/") and "reasoner" not in name:
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {}

    @staticmethod
    def _output_token_budget(model: str) -> int:
        """Largest safe completion budget for the model (16k cap, model-limit aware)."""
        try:
            info = litellm.get_model_info(model)
            limit = info.get("max_output_tokens") or info.get("max_tokens")
            if limit:
                return int(min(16384, limit))
        except Exception:
            pass
        return 8192

    def _record_usage(self, response: Any, model: str) -> None:
        """Accumulates token usage and estimated cost (thread-safe)."""
        try:
            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            try:
                cost = float(litellm.completion_cost(completion_response=response, model=model) or 0.0)
            except Exception:
                cost = 0.0
            with self._usage_lock:
                self.usage["requests"] += 1
                self.usage["prompt_tokens"] += prompt_tokens
                self.usage["completion_tokens"] += completion_tokens
                self.usage["cost_usd"] += cost
        except Exception:
            pass

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
            current_model: The routing name of the model that failed (e.g., 'gemini/gemini-3.8-flash').

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
        
        # Build fully qualified model paths (e.g., 'gemini/gemini-3.8-flash')
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
        """Resolves the provider's API key from its standard environment variable."""
        for cfg in DEFAULT_PROVIDERS.values():
            prefix = cfg.get("prefix", "")
            env_name = cfg.get("key_env")
            if prefix and env_name and model.startswith(prefix):
                return os.getenv(env_name)
        model_lower = model.lower()
        if "gemini" in model_lower:
            return os.getenv("GEMINI_API_KEY")
        if "gpt" in model_lower or "openai" in model_lower:
            return os.getenv("OPENAI_API_KEY")
        if "claude" in model_lower or "anthropic" in model_lower:
            return os.getenv("ANTHROPIC_API_KEY")
        if "deepseek" in model_lower:
            return os.getenv("DEEPSEEK_API_KEY")
        return None
