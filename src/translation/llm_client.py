"""
llm_client.py — Client de traduction LiteLLM pour RockTranslate
Chemin : /src/translation/llm_client.py

Usage minimal :
    client = LLMClient(model="gemini/gemini-2.0-flash", api_key="...", target_lang="French")
    translated_paragraphs = client.translate_document(paragraphs)

Providers supportés (via LiteLLM) :
    Gemini  : "gemini/gemini-2.0-flash"
    OpenAI  : "gpt-4o", "gpt-4o-mini"
    Anthropic: "claude-sonnet-4-20250514"
    Ollama  : "ollama/mistral" (local, pas de clé API)
"""

import json
import os
import time
import re
from dataclasses import dataclass
from typing import Callable

from loguru import logger

try:
    import litellm
    litellm.suppress_debug_info = True
except ImportError:
    litellm = None


from core.domain import FitzBlock
from translation.chunker import Batch, build_batches, batches_summary
from translation.prompts import (
    get_system_prompt,
    get_user_message,
    DEFAULT_LANG_NAME,
)
from utils.style_codec import decode_styled_text

# ── Retry config ───────────────────────────────────────────────────────────────
_MAX_RETRIES   = 4
_RETRY_DELAYS  = [2.0, 3.0, 6.0]   # backoff exponentiel (secondes)


@dataclass
class TranslationResult:
    """Résultat d'une traduction complète."""
    paragraphs: list[FitzBlock]   # avec .translated_text rempli
    total_batches: int
    total_tokens_estimated: int
    failed_paragraphs: list[int]  # indices des paras échoués


class LLMClient:
    """
    Client de traduction provider-agnostic via LiteLLM.

    Paramètres :
        model       : identifiant LiteLLM (ex: "gemini/gemini-2.0-flash")
        api_key     : clé API (None = lit depuis les variables d'env)
        target_lang : langue cible (ex: "French", "Spanish", "Arabic")
        max_tokens  : override du budget tokens (None = auto)
        on_progress : callback(current, total) appelé après chaque batch
    """

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: str | None = None,
        target_lang: str = DEFAULT_LANG_NAME,
        max_tokens: int | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ):
        self.model       = model
        self.api_key     = api_key or self._get_api_key_from_env(model)
        self.target_lang = target_lang
        self.max_tokens  = max_tokens
        self.on_progress = on_progress
        self.on_status   = on_status

        self._litellm = litellm

        logger.info(
            f"LLMClient initialisé — modèle: {model} | "
            f"langue: {target_lang}"
        )

    def _log_status(self, message: str):
        """Envoie des retours d'informations à l'UI et aux logs simultanément."""
        logger.info(message)
        if self.on_status:
            self.on_status(message)

    # ══════════════════════════════════════════════════════════
    # API PUBLIQUE
    # ══════════════════════════════════════════════════════════

    def translate_document(
        self,
        paragraphs: list[FitzBlock],
    ) -> TranslationResult:
        """
        Traduit tous les paragraphes du document.
        Remplit para.translated_text sur chaque Paragraph.
        """
        batches = build_batches(paragraphs, self.model, self.max_tokens)

        if not batches:
            logger.warning("Aucun paragraphe à traduire.")
            return TranslationResult(
                paragraphs=paragraphs,
                total_batches=0,
                total_tokens_estimated=0,
                failed_paragraphs=[],
            )

        logger.info(f"Plan de traduction :\n{batches_summary(batches)}")

        failed: list[int] = []
        total_tokens = sum(b.estimated_tokens for b in batches)

        for i, batch in enumerate(batches):
            logger.info(
                f"Batch {i+1}/{len(batches)} — "
                f"{len(batch.paragraphs)} para(s)"
            )

            success = self._translate_batch_with_retry(batch)

            if not success:
                for para in batch.paragraphs:
                    para.translated_text = f"[TRANSLATION FAILED] {para.text}"
                    failed.append(id(para))
                logger.error(
                    f"Batch {i+1} échoué après {_MAX_RETRIES} tentatives."
                )

            if self.on_progress:
                self.on_progress(i + 1, len(batches))

        logger.info(
            f"Traduction terminée — "
            f"{len(paragraphs) - len(failed)}/{len(paragraphs)} réussis"
        )

        return TranslationResult(
            paragraphs=paragraphs,
            total_batches=len(batches),
            total_tokens_estimated=total_tokens,
            failed_paragraphs=failed,
        )

    def translate_single(self, text: str) -> str:
        """Traduit un texte brut (hors pipeline)."""
        batch_data = [{"id": 0, "text": text}]
        result = self._call_llm(batch_data)
        if result and result[0].get("translated"):
            return decode_styled_text(result[0]["translated"])
        return f"[TRANSLATION FAILED] {text}"

    # ══════════════════════════════════════════════════════════
    # RETRY LOGIC
    # ══════════════════════════════════════════════════════════

    def _translate_batch_with_retry(
        self,
        batch: Batch,
        context: str | None = None,
    ) -> bool:
        """
        Tente de traduire un batch avec jusqu'à _MAX_RETRIES tentatives.
        Retourne True si succès, False si toutes les tentatives échouent.
        Ne lève jamais d'exception — les erreurs rate-limit sont gérées ici
        silencieusement avec décompte dans la status bar.
        """
        batch_data = [
            {"id": i, "text": para.text}
            for i, para in enumerate(batch.paragraphs)
        ]

        current_model = self.model

        for attempt in range(_MAX_RETRIES):
            try:
                if attempt >= 2:
                    fallback_model = self._get_fallback_model(current_model)
                    if fallback_model and fallback_model != current_model:
                        fallback_key = self._get_api_key_from_env(fallback_model)
                        if fallback_key:
                            self._log_status(
                                f"🔄 Modèle {current_model} saturé. "
                                f"Basculement sur {fallback_model}..."
                            )
                            current_model = fallback_model
                            self.api_key = fallback_key

                results = self._call_llm(batch_data, context=context)

                if results is None:
                    continue

                id_to_para = {i: p for i, p in enumerate(batch.paragraphs)}
                for item in results:
                    idx = item.get("id")
                    translated = item.get("translated", "").strip()
                    if idx in id_to_para and translated:
                        id_to_para[idx].translated_text = decode_styled_text(translated)

                all_translated = all(
                    p.translated_text for p in batch.paragraphs
                )
                if all_translated:
                    return True

                self._log_status(
                    f"⚠️ Traduction incomplète. Tentative {attempt + 1}/{_MAX_RETRIES}..."
                )

            except Exception as e:
                err_msg = str(e).lower()

                is_rate_limit = any(
                    x in err_msg for x in [
                        "rate_limit", "rate limit", "429", "overloaded",
                        "resource_exhausted", "resource exhausted", "quota"
                    ]
                )

                wait_time = 6 * (attempt + 1)  # 6s, 12s, 18s...

                if is_rate_limit:
                    # Décompte interactif dans la status bar — pas de QMessageBox
                    for remaining in range(wait_time, 0, -1):
                        self._log_status(
                            f"⏳ Limite API atteinte — reprise dans {remaining}s..."
                        )
                        time.sleep(1)
                else:
                    self._log_status(
                        f"❌ Erreur réseau ({type(e).__name__}) — pause {wait_time}s..."
                    )
                    time.sleep(wait_time)

        return False

    def _get_fallback_model(self, current_model: str) -> str | None:
        fallback_chain = [
            "gemini/gemini-2.5-flash-lite",
            "gemini/gemini-3.1-flash-lite",
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.0-flash",
            "gpt-4o-mini",
            "gemini/gemini-1.5-pro",
            "gpt-4o"
        ]
        try:
            current_idx = fallback_chain.index(current_model)
            candidates = fallback_chain[current_idx + 1:] + fallback_chain[:current_idx]
        except ValueError:
            candidates = fallback_chain

        for candidate in candidates:
            key = self._get_api_key_from_env(candidate)
            if key:
                return candidate
        return None

    # ══════════════════════════════════════════════════════════
    # APPEL LLM
    # ══════════════════════════════════════════════════════════

    def _call_llm(
        self,
        batch_data: list[dict],
        context: str | None = None,
    ) -> list[dict] | None:
        """
        Appel LiteLLM et parsing de la réponse JSON.
        context : texte de contexte glissant injecté avant le batch.
        """
        system_prompt = get_system_prompt(self.target_lang)
        user_message  = get_user_message(batch_data, context=context)

        kwargs = {
            "model":    self.model,
            "messages": [
                {"role": "system",  "content": system_prompt},
                {"role": "user",    "content": user_message},
            ],
            "temperature": 0.1,
            "max_tokens":  65536,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key

        response = self._litellm.completion(**kwargs)
        raw_text = response.choices[0].message.content.strip()
        print(f"[LLM RAW] {raw_text[:200]}...")

        logger.debug(f"  Réponse brute ({len(raw_text)} chars) : {raw_text[:120]}…")

        return self._parse_json_response(raw_text)

    def _parse_json_response(self, raw: str) -> list[dict] | None:
        cleaned = raw
        if "```" in cleaned:
            lines = cleaned.split("\n")
            cleaned = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            )
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
            logger.warning(f"JSON valide mais pas une liste : {type(data)}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"JSON invalide : {e}")
            logger.debug(f"Texte brut : {cleaned[:300]}")

            start = cleaned.find("[")
            end   = cleaned.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1])
                except json.JSONDecodeError:
                    pass
            return None
    
    

    


    # ══════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _get_api_key_from_env(model: str) -> str | None:
        model_lower = model.lower()
        if "gemini" in model_lower:
            return os.getenv("GEMINI_API_KEY")
        if "gpt" in model_lower or "openai" in model_lower:
            return os.getenv("OPENAI_API_KEY")
        if "claude" in model_lower or "anthropic" in model_lower:
            return os.getenv("ANTHROPIC_API_KEY")
        return None