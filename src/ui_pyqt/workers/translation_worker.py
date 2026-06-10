# ui_pyqt/workers/translation_worker.py

from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

# Importation de nos modules purs de translation/
from translation.chunker import build_batches, Batch
from translation.llm_client import LLMClient

# Nombre d'éléments traduits à mémoriser pour assurer la cohérence sémantique inter-pages
_SLIDING_CONTEXT_MAX_SIZE = 5


class TranslationWorker(QThread):
    """
    Worker d'arrière-plan gérant l'orchestration des lots de traduction
    et le streaming progressif en temps réel vers l'interface.
    """
    status_update      = pyqtSignal(str)       # Met à jour le message de statut
    batch_progress     = pyqtSignal(int, int)  # Émet (lots_traites, lots_totaux)
    segment_translated = pyqtSignal(str, str)  # Émet (id_segment, texte_traduit_IA)
    finished           = pyqtSignal()          # Signal de fin de traduction globale
    error              = pyqtSignal(str)       # En cas de crash du client LLM

    def __init__(self, original_texts: dict, model: str, api_key: str, target_lang: str,  custom_base_url: str = None):
        super().__init__()
        self.original_texts = original_texts
        self.model = model
        self.api_key = api_key
        self.target_lang = target_lang
        self.custom_base_url = custom_base_url  

        self._stop = False
        self.client = None

    def run(self):
        try:
            self._stop = False
            self.status_update.emit("⚙️ Initialisation du traducteur IA...")
            
            # Étape A : Initialisation du client LLM asynchrone
            self.client = LLMClient(
                model=self.model,
                api_key=self.api_key,
                target_lang=self.target_lang,
                custom_base_url=self.custom_base_url,
                on_status=lambda msg: self.status_update.emit(msg)
            )

            # Étape B : Découpage sémantique du dictionnaire de texte en lots (batches)
            self.status_update.emit("⚙️ Construction des lots de traduction...")
            batches = build_batches(self.original_texts, self.model)
            total_batches = len(batches)
            
            if not batches:
                self.status_update.emit("⚠️ Aucun texte à traduire trouvé.")
                self.finished.emit()
                return

            logger.info(f"Départ de la traduction : {total_batches} lots identifiés.")
            
            # ── ÉTAPE B.2 : RÉVÉLATION INSTANTANÉE DES FORMULES ET TEXTES IGNORÉS ──
            # On extrait tous les identifiants qui vont être envoyés à l'IA
            translatable_ids = set()
            for batch in batches:
                translatable_ids.update(batch.ids)
            
            # Tous les autres identifiants du document sont des formules ou des chiffres ignorés
            skipped_ids = set(self.original_texts.keys()) - translatable_ids
            logger.info(f"Révélation instantanée de {len(skipped_ids)} segments ignorés (formules/chiffres).")
            
            # On émet immédiatement leur texte d'origine pour retirer leur Shimmer et les afficher
            for skipped_id in skipped_ids:
                print(f"🚫 Ignoré (Affiché de suite) : {skipped_id} ➡️ '{self.original_texts[skipped_id]}'")
                orig_text = self.original_texts[skipped_id]
                self.segment_translated.emit(skipped_id, orig_text)
            # ───────────────────────────────────────────────────────────────────────

            sliding_context = []

            # Étape C : Traduction séquentielle lot par lot
            for idx, batch in enumerate(batches):
                # Vérification de l'arrêt demandé par l'utilisateur
                if self._stop:
                    logger.info("Traduction interrompue par l'utilisateur.")
                    self.status_update.emit("Traduction interrompue par l'utilisateur.")
                    break

                self.batch_progress.emit(idx + 1, total_batches)
                self.status_update.emit(f"Traduction du lot {idx + 1}/{total_batches}...")

                # Formatage du contexte glissant terminologique
                context_str = "\n".join(sliding_context) if sliding_context else None

                # Appel réel de la traduction pure
                results = self.client.translate_batch(batch.segments, context=context_str)

                # Une double vérification après l'appel réseau pour ne pas émettre
                # de signaux si l'utilisateur a cliqué sur stop pendant la requête
                if self._stop:
                    self.status_update.emit("Traduction interrompue par l'utilisateur.")
                    break


                if results is None:
                    # En cas d'échec total persistant d'un lot, on affiche un message d'erreur
                    # sur chacun de ses segments à l'écran pour ne pas bloquer l'affichage
                    for item in batch.segments:
                        self.segment_translated.emit(item["id"], f"[ÉCHEC] {item['text']}")
                    continue

                # Émission des traductions segment par segment pour l'injection JS en temps réel !
                for item in results:
                    seg_id = item.get("id")
                    translated_text = item.get("translated", "").strip()
                    
                    if seg_id and translated_text:
                        # Émet vers MainWindow pour injection directe
                        self.segment_translated.emit(seg_id, translated_text)
                        
                        # Ajout au contexte glissant
                        sliding_context.append(translated_text)

                # Limitation de la mémoire glissante pour éviter l'explosion de tokens
                if len(sliding_context) > _SLIDING_CONTEXT_MAX_SIZE:
                    sliding_context = sliding_context[-_SLIDING_CONTEXT_MAX_SIZE:]

            self.status_update.emit("✅ Traduction du document finalisée.")
            self.finished.emit()

        except Exception as e:
            logger.error(f"Erreur critique lors de la traduction : {e}")
            self.error.emit(str(e))

    def stop(self):
        """Méthode d'interruption sécurisée du thread."""
        self._stop = True

    def is_stopped(self) -> bool:
        """Permet de savoir si le thread a été interrompu volontairement."""
        return self._stop