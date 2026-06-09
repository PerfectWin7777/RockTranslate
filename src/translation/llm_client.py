# translation/llm_client.py

import os
import time
import re
from typing import Callable, Optional, List, Dict
from loguru import logger
import json_repair

try:
    import litellm
    litellm.suppress_debug_info = True
except ImportError:
    litellm = None

from translation.prompts import (
    get_system_prompt,
    get_user_message,
    DEFAULT_LANG_NAME,
)

# Configuration de la tolérance aux pannes réseau
_MAX_RETRIES = 4
_RETRY_DELAYS = [2.0, 3.0, 6.0]  # Backoff exponentiel en secondes


class LLMClient:
    """
    Client de traduction universel et résistant aux pannes basé sur LiteLLM.
    
    Cette classe gère le routage des requêtes vers plus de 100 modèles d'IA (Gemini,
    GPT, Claude, Ollama local), s'auto-ajuste en cas de Rate-Limit, et nettoie
    les retours JSON défaillants.
    """

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: Optional[str] = None,
        target_lang: str = DEFAULT_LANG_NAME,
        max_tokens: Optional[int] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        self.model = model
        self.api_key = api_key or self._get_api_key_from_env(model)
        self.target_lang = target_lang
        self.max_tokens = max_tokens
        self.on_status = on_status

        if litellm is None:
            raise ImportError(
                "La bibliothèque 'litellm' est requise. Veuillez l'installer via pip install litellm."
            )

        logger.info(f"LLMClient initialisé : modèle='{self.model}' | langue cible='{self.target_lang}'")

    def _log_status(self, message: str):
        """Notifie l'UI (via le callback) et écrit l'état dans la console de debug."""
        logger.info(message)
        if self.on_status:
            self.on_status(message)

    # ══════════════════════════════════════════════════════════
    # API PUBLIQUE DE TRADUCTION
    # ══════════════════════════════════════════════════════════

    def translate_batch(
        self,
        batch_segments: List[Dict[str, str]],
        context: Optional[str] = None,
    ) -> Optional[List[Dict[str, str]]]:
        """
        Traduit un lot de segments textuels avec gestion robuste des erreurs et basculement automatique.
        
        Args:
            batch_segments: Liste de segments [{"id": "t-0", "text": "..."}]
            context: Contexte terminologique d'accompagnement (glissant).
            
        Returns:
            List[Dict] ou None : Liste des segments traduits [{"id": "t-0", "translated": "..."}] ou None si échec.
        """
        current_model = self.model
        current_key = self.api_key

        for attempt in range(_MAX_RETRIES):
            try:
                # En cas d'échecs répétés, tentative de basculement vers un modèle alternatif disponible
                if attempt >= 2:
                    fallback_model = self._get_fallback_model(current_model)
                    if fallback_model and fallback_model != current_model:
                        fallback_key = self._get_api_key_from_env(fallback_model)
                        if fallback_key:
                            self._log_status(
                                f"🔄 Modèle {current_model} saturé ou indisponible. "
                                f"Basculement sur {fallback_model} (Tentative {attempt + 1})..."
                            )
                            current_model = fallback_model
                            current_key = fallback_key

                # Appel réel de l'API LLM
                results = self._call_llm(batch_segments, model=current_model, api_key=current_key, context=context)
                
                if results is not None:
                     
                    print ('batch_segments : ', batch_segments)
                    print ('results : ', results)

                    return results
                
                    # Vérification de l'intégrité du retour
                    # if len(results) == len(batch_segments):
                    #     return results
                    # else:
                    #     self._log_status(
                    #         f"⚠️ Traduction incomplète : reçu {len(results)}/{len(batch_segments)} segments."
                    #     )

            except Exception as e:
                err_msg = str(e).lower()
                is_rate_limit = any(
                    x in err_msg for x in [
                        "rate_limit", "rate limit", "429", "overloaded", "RESOURCE_EXHAUSTED",
                        "resource_exhausted", "resource exhausted", "quota",
                        "UNAVAILABLE", "503", "timeout", "timed out", "connection error",
                    ]
                )

                wait_time = 6 * (attempt + 1) # Progression : 6s, 12s, 18s...

                if is_rate_limit:
                    for remaining in range(wait_time, 0, -1):
                        self._log_status(
                            f"⏳ Limite API atteinte (Rate-Limit) — reprise automatique dans {remaining}s..."
                        )
                        time.sleep(1)
                else:
                    self._log_status(
                        f"❌ Erreur de connexion ({type(e).__name__}) — pause de {wait_time}s..."
                    )
                    time.sleep(wait_time)

        logger.error(f"❌ Échec de la traduction du lot après {_MAX_RETRIES} tentatives.")
        return None

    def translate_single(self, text: str) -> str:
        """Traduit une chaîne de caractères brute (hors-pipeline principal)."""
        batch_data = [{"id": "t-single", "text": text}]
        result = self.translate_batch(batch_data)
        if result and result[0].get("translated"):
            return result[0]["translated"]
        return f"[TRADUCTION ÉCHOUÉE] {text}"

    # ══════════════════════════════════════════════════════════
    # SOUS-MÉTHODES ET MOTEUR INTERNE
    # ══════════════════════════════════════════════════════════

    def _call_llm(
        self,
        batch_segments: List[Dict[str, str]],
        model: str,
        api_key: Optional[str],
        context: Optional[str] = None,
    ) -> Optional[List[Dict[str, str]]]:
        """Exécute l'appel de l'API via LiteLLM et parse la réponse JSON."""
        try :
            system_prompt = get_system_prompt(self.target_lang)
            user_message = get_user_message(batch_segments, context=context)

            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.1,  # Faible créativité requise pour de la traduction scientifique
                "max_tokens": 16384, # Large budget pour éviter la troncature
            }

            if api_key:
                kwargs["api_key"] = api_key

            # Appel LiteLLM
            response = litellm.completion(**kwargs)
            raw_text = response.choices[0].message.content.strip()
        except Exception as e:
            import traceback; traceback.print_exc()
            logger.warning(f"Erreur lors de l'appel à l'API LLM : {e}")
            return None

        return self._parse_json_response(raw_text)



    def _parse_json_response(self, raw: str) -> Optional[List[Dict[str, str]]]:
        """Nettoie le texte renvoyé par le LLM pour en extraire un JSON valide."""
        cleaned = raw
        # Retrait des balises de code Markdown de type ```json ou ```
        if "```" in cleaned:
            lines = cleaned.split("\n")
            cleaned = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            )
        cleaned = cleaned.strip()

        try:
            # Utilisation de json_repair pour tolérer et corriger les erreurs de syntaxe de l'IA
            data = json_repair.loads(cleaned)
            if isinstance(data, list):
                return data
            logger.warning(f"Le JSON est valide mais n'est pas une liste : {type(data)}")
            return None
        except Exception as e:
            logger.warning(f"Échec de l'analyse du JSON : {e}")
            
            # Recherche de secours d'un tableau à l'intérieur de la réponse
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    return json_repair.loads(cleaned[start:end + 1])
                except Exception:
                    pass
            return None

    def _get_fallback_model(self, current_model: str) -> Optional[str]:
        """Détermine un modèle de secours logique en cas de saturation de l'API principale."""
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

    @staticmethod
    def _get_api_key_from_env(model: str) -> Optional[str]:
        """Récupère dynamiquement la clé API requise depuis l'environnement système."""
        model_lower = model.lower()
        if "gemini" in model_lower:
            return os.getenv("GEMINI_API_KEY")
        if "gpt" in model_lower or "openai" in model_lower:
            return os.getenv("OPENAI_API_KEY")
        if "claude" in model_lower or "anthropic" in model_lower:
            return os.getenv("ANTHROPIC_API_KEY")
        return None