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
from dataclasses import dataclass
from typing import Callable

from loguru import logger

from core.domain import Paragraph
from translation.chunker import Batch, build_batches, batches_summary
from translation.prompts import (
    get_system_prompt,
    get_user_message,
    DEFAULT_LANG_NAME,
)


# ── Retry config ───────────────────────────────────────────────────────────────
_MAX_RETRIES   = 3
_RETRY_DELAYS  = [2.0, 5.0, 15.0]   # backoff exponentiel (secondes)


@dataclass
class TranslationResult:
    """Résultat d'une traduction complète."""
    paragraphs: list[Paragraph]   # avec .translated_text rempli
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
        model: str = "gemini/gemini-3.1-flash-lite",
        api_key: str | None = None,
        target_lang: str = DEFAULT_LANG_NAME,
        max_tokens: int | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ):
        self.model       = model
        self.api_key     = api_key or self._get_api_key_from_env(model)
        self.target_lang = target_lang
        self.max_tokens  = max_tokens
        self.on_progress = on_progress

        # Import ici pour ne pas crasher si litellm n'est pas installé
        try:
            import litellm
            self._litellm = litellm
            # Silence les logs verbeux de litellm
            litellm.suppress_debug_info = True
        except ImportError:
            raise ImportError(
                "litellm n'est pas installé.\n"
                "Lance : pip install litellm"
            )

        logger.info(
            f"LLMClient initialisé — modèle: {model} | "
            f"langue: {target_lang}"
        )

    # ══════════════════════════════════════════════════════════
    # API PUBLIQUE
    # ══════════════════════════════════════════════════════════

    def translate_document(
        self,
        paragraphs: list[Paragraph],
    ) -> TranslationResult:
        """
        Traduit tous les paragraphes du document.
        Remplit para.translated_text sur chaque Paragraph.

        Retourne un TranslationResult avec les statistiques.
        """
        # ── Découpage en batches ──────────────────────────────
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

        # ── Traduction batch par batch ────────────────────────
        for i, batch in enumerate(batches):
            logger.info(
                f"Batch {i+1}/{len(batches)} — "
                f"{len(batch.paragraphs)} para(s)"
            )

            success = self._translate_batch_with_retry(batch)

            if not success:
                # Marque les paragraphes échoués
                for para in batch.paragraphs:
                    para.translated_text = f"[TRANSLATION FAILED] {para.text}"
                    failed.append(id(para))
                logger.error(
                    f"Batch {i+1} échoué après {_MAX_RETRIES} tentatives."
                )

            # Callback de progression (pour la barre de progression UI)
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
        """
        Traduit un texte brut (hors pipeline).
        Utile pour tester la connexion ou traduire une chaîne isolée.
        """
        batch_data = [{"id": 0, "text": text}]
        result = self._call_llm(batch_data)
        if result and result[0].get("translated"):
            return result[0]["translated"]
        return f"[TRANSLATION FAILED] {text}"

    # ══════════════════════════════════════════════════════════
    # RETRY LOGIC
    # ══════════════════════════════════════════════════════════

    def _translate_batch_with_retry(self, batch: Batch) -> bool:
        """
        Tente de traduire un batch avec jusqu'à _MAX_RETRIES tentatives.
        Retourne True si succès, False si toutes les tentatives échouent.
        """
        batch_data = [
            {"id": i, "text": para.text}
            for i, para in enumerate(batch.paragraphs)
        ]

        for attempt in range(_MAX_RETRIES):
            try:
                if attempt > 0:
                    delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
                    logger.warning(
                        f"  Tentative {attempt + 1}/{_MAX_RETRIES} "
                        f"(attente {delay}s...)"
                    )
                    time.sleep(delay)

                results = self._call_llm(batch_data)

                if results is None:
                    continue

                # ── Injecte les traductions dans les Paragraphs ──
                id_to_para = {i: p for i, p in enumerate(batch.paragraphs)}
                for item in results:
                    idx = item.get("id")
                    translated = item.get("translated", "").strip()
                    if idx in id_to_para and translated:
                        id_to_para[idx].translated_text = translated

                # Vérifie que tous les paragraphes ont été traduits
                all_translated = all(
                    p.translated_text for p in batch.paragraphs
                )
                if all_translated:
                    return True

                logger.warning(
                    f"  Traductions incomplètes "
                    f"({sum(1 for p in batch.paragraphs if p.translated_text)}"
                    f"/{len(batch.paragraphs)})"
                )

            except Exception as e:
                logger.warning(f"  Erreur tentative {attempt + 1}: {e}")

        return False

    # ══════════════════════════════════════════════════════════
    # APPEL LLM
    # ══════════════════════════════════════════════════════════

    def _call_llm(self, batch_data: list[dict]) -> list[dict] | None:
        """
        Appel LiteLLM et parsing de la réponse JSON.
        Retourne la liste des traductions ou None si erreur.
        """
        system_prompt = get_system_prompt(self.target_lang)
        user_message  = get_user_message(batch_data)

        kwargs = {
            "model":    self.model,
            "messages": [
                {"role": "system",  "content": system_prompt},
                {"role": "user",    "content": user_message},
            ],
            "temperature": 0.1,     # faible pour la cohérence scientifique
            "max_tokens":  65536,    # réponse max par appel
        }

        # Ajoute la clé API si fournie
        if self.api_key:
            kwargs["api_key"] = self.api_key

        response = self._litellm.completion(**kwargs)
        raw_text = response.choices[0].message.content.strip()

        logger.debug(f"  Réponse brute ({len(raw_text)} chars) : {raw_text[:120]}…")

        # ── Parsing JSON robuste ──────────────────────────────
        return self._parse_json_response(raw_text)

    def _parse_json_response(self, raw: str) -> list[dict] | None:
        """
        Parse la réponse JSON du LLM.
        Gère les cas où le LLM enveloppe le JSON dans des backticks.
        """
        # Nettoie les fences markdown ```json ... ```
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

            # Tentative de récupération : cherche [ ... ] dans la réponse
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
        """Déduit la variable d'env à partir du provider."""
        model_lower = model.lower()
        if "gemini" in model_lower:
            return os.getenv("GEMINI_API_KEY")
        if "gpt" in model_lower or "openai" in model_lower:
            return os.getenv("OPENAI_API_KEY")
        if "claude" in model_lower or "anthropic" in model_lower:
            return os.getenv("ANTHROPIC_API_KEY")
        # Ollama local : pas de clé
        return None