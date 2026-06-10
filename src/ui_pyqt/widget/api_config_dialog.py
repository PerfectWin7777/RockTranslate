# src/ui_pyqt/widget/api_config_dialog.py

import os
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, 
    QComboBox, QLineEdit, QCheckBox, QPushButton, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import Qt, QSettings

# Configuration des modèles de départ suggérés par fournisseur
DEFAULT_PROVIDERS = {
    "Google Gemini": {
        "prefix": "gemini/",
        "key_env": "GEMINI_API_KEY",
        "models": [
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-pro",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-exp-1206"
        ]
    },

    "OpenAI": {
        "prefix": "openai/",
        "key_env": "OPENAI_API_KEY",
        "models": [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-5.5",
            "gpt-5.4",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
            "chatgpt-4o-latest",
            "o1",
            "o1-mini",
            "o1-preview",
            "o3",
            "o3-mini",
            "o4-mini"
        ]
    },

    "Anthropic": {
        "prefix": "anthropic/",
        "key_env": "ANTHROPIC_API_KEY",
        "models": [
            "claude-4.8-opus",           
            "claude-4.6-sonnet",         
            "claude-4.5-haiku",
            "claude-4-opus",
            "claude-4-sonnet",
            "claude-3-7-sonnet",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]
    },

    "DeepSeek": {
        "prefix": "deepseek/",
        "key_env": "DEEPSEEK_API_KEY",
        "models": [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v3",
            "deepseek-r1"
        ]
    },

    "Mistral AI": {
        "prefix": "mistral/",
        "key_env": "MISTRAL_API_KEY",
        "models": [
            "mistral-medium-3.5",        # Modèle dense unifié de 128B (général, vision, code)
            "mistral-small-latest",
            "mistral-large-latest",
            "mistral-medium-latest",
            "mistral-small-latest",
            "pixtral-large-latest",
            "pixtral-12b",
            "ministral-8b-latest",
            "ministral-3b-latest",
            "open-mistral-nemo",
            "open-mixtral-8x22b",
            "open-mixtral-8x7b"
        ]
    },

    "Groq": {
        "prefix": "groq/",
        "key_env": "GROQ_API_KEY",
        "models": [
            "llama-4-scout-groq",        
            "llama-3.3-70b-versatile",   
            "llama3-70b-8192",
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
            "qwen-qwq-32b",
            "deepseek-r1-distill-llama-70b"
        ]
    },

    "Together AI": {
        "prefix": "together_ai/",
        "key_env": "TOGETHERAI_API_KEY",
        "models": [
            "meta-llama/Llama-4-Maverick",         
            "meta-llama/Llama-4-Scout",            
            "meta-llama/Meta-Llama-3.1-405B-Instruct",
            "meta-llama/Meta-Llama-3.3-70B-Instruct",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "meta-llama/Llama-3.1-405B-Instruct-Turbo",
            "meta-llama/Llama-3.1-70B-Instruct-Turbo",
            "meta-llama/Llama-3.1-8B-Instruct-Turbo",
            "Qwen/Qwen3-235B-A22B",
            "Qwen/Qwen3-32B",
            "Qwen/Qwen2.5-72B-Instruct",
            "deepseek-ai/DeepSeek-V4-Pro",
            "deepseek-ai/DeepSeek-R1",
            "deepseek-ai/DeepSeek-V3",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
             "mistralai/Mixtral-8x22B-Instruct-v0.1",
            "moonshotai/Kimi-K2",
            "zai-org/GLM-4.7"
        ]
    },

    "Moonshot (Kimi)": {
        "prefix": "moonshot/",
        "key_env": "MOONSHOT_API_KEY",
        "models": [
            "kimi-k2.6",                 
            "kimi-k2.5",              
            "kimi-k2",
            "kimi-k2-instruct",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k"
        ]
    },

    "Alibaba DashScope (Qwen)": {
        "prefix": "dashscope/",
        "key_env": "DASHSCOPE_API_KEY",
        "models": [
            "qwen3.7-max-preview",       
            "qwen3.5-plus",                  
            "qwen-max",                  
            "qwen-plus",
            "qwen-turbo"
            "qwen-max",
            "qwen-plus",
            "qwen-turbo",
            "qwen-long",
            "qwen2.5-72b-instruct",
            "qwen2.5-32b-instruct",
            "qwen2.5-14b-instruct",
            "qwen2.5-7b-instruct",
            "qwen3-235b-a22b",
            "qwen3-32b",
            "qwq-32b"
        ]
    },

    "Zhipu AI (GLM)": {
        "prefix": "zai/",
        "key_env": "ZAI_API_KEY",
        "models": [
            "glm-5.1",                   
            "glm-5",                   
            "glm-4.7",
            "glm-4.5"
            "glm-4.7",
            "glm-4.6",
            "glm-4.5",
            "glm-4-air",
            "glm-4-airx",
            "glm-4-plus",
            "glm-4-long"
        ]
    },

    "xAI (Grok)": {
        "prefix": "xai/",
        "key_env": "XAI_API_KEY",
        "models": [
            "grok-4",
            "grok-3",
            "grok-3-mini",
            "grok-2-1212",
            "grok-beta"
        ]
    },

    "OpenRouter": {
        "prefix": "openrouter/",
        "key_env": "OPENROUTER_API_KEY",
        "models": [
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "openai/gpt-4.1",
            "openai/gpt-4o",

            "anthropic/claude-4-opus",
            "anthropic/claude-4-sonnet",
            "anthropic/claude-4.6-sonnet",
            "anthropic/claude-4.8-opus",
            "anthropic/claude-4.5-haiku",
            "anthropic/claude-3.7-sonnet",

            "google/gemini-2.5-pro",
            "google/gemini-2.5-flash",
            "google/gemini-3.5-flash",
            "google/gemini-3.1-flash-lite",


            "deepseek/deepseek-r1",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-v3",
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",

            "x-ai/grok-4",
            "x-ai/grok-3",

            "qwen/qwen3-235b-a22b",
            "qwen/qwen2.5-72b-instruct",
            "qwen/qwen-3.5-397b-instruct",

            "meta-llama/llama-3.3-70b-instruct",
            "meta-llama/llama-3.1-405b-instruct",

            "mistralai/mistral-large",
            "mistralai/mistral-medium-3.5"
            "moonshotai/kimi-k2",
            "z-ai/glm-4.7"
        ]
    },

    "Ollama (Local)": {
        "prefix": "ollama/",
        "key_env": "",
        "models": [
            "llama3",
            "llama3.1",
            "llama3.2",
            "llama3.3",
            "deepseek-v4-flash",
            "qwen2.5",
            "qwen3",
            "qwen3.6-27b",
            "deepseek-r1",
            "deepseek-v3",
            "mistral",
            "mixtral",
            "codestral",
            "gemma2",
            "phi4",
            "phi3",
            "command-r",
            "command-r-plus",
            "yi",
            "granite3.3"
        ]
    }
}


class ApiKeyLineEdit(QLineEdit):
    def focusInEvent(self, event):
        self.setPlaceholderText("Entrez votre clé API")
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.setPlaceholderText("")
        super().focusOutEvent(event)


class APIConfigDialog(QDialog):
    """
    Interface de configuration d'IA contextuelle et dynamique (style Cline).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration de l'API")
        self.resize(700, 360)
        self.setStyleSheet("""
            QDialog {
                background-color: #f7fafc;
            }
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                color: #4a5568;
                font-weight: bold;
            }
            QComboBox, QLineEdit {
                background-color: #ffffff;
                border: 1px solid #cbd5e0;
                border-radius: 4px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #2d3748;
            }
            QComboBox:focus, QLineEdit:focus {
                border-color: #4f8ef7;
            }
            QCheckBox {
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                color: #4a5568;
            }
           /* Style épuré pour le bouton de suppression rouge */
            QPushButton#DeleteBtn {
                background-color: #fff5f5;
                border: 1px solid #feb2b2;
                border-radius: 4px;
                color: #c53030;
                padding: 6px 12px;
                font-family: 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton#DeleteBtn:hover {
                background-color: #fed7d7;
            }
                           
        """)

        self._load_settings()
        self._build_ui()
        self._on_provider_changed(self.combo_provider.currentText())

    def _load_settings(self):
        """Récupère les réglages persistés du système."""
        self.settings = QSettings("RockTranslate", "APIConfig")
        self.current_provider = self.settings.value("provider", "Google Gemini")
        self.custom_base_url = self.settings.value("custom_base_url", "http://localhost:11434")
        self.use_custom_base = self.settings.value("use_custom_base", False, type=bool)
        
        # Dictionnaire persistant pour conserver les clés de chaque API séparément
        self.keys_dict = self.settings.value("api_keys_by_provider", {})
        if isinstance(self.keys_dict, str):
            try:
                self.keys_dict = json.loads(self.keys_dict)
            except Exception:
                self.keys_dict = {}

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        form = QFormLayout()
        form.setSpacing(12)

        # 1. Sélection du Fournisseur d'API (API Provider)
        self.combo_provider = QComboBox(self)
        self.combo_provider.addItems(list(DEFAULT_PROVIDERS.keys()))
        self.combo_provider.setCurrentText(self.current_provider)
        self.combo_provider.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("API Provider", self.combo_provider)

        # 2. Saisie de la Clé API dynamique
        self.lbl_key = QLabel("API Key", self)
        self.edit_key = ApiKeyLineEdit(self)
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        # self.edit_key.setPlaceholderText("Entrez votre clé API")
        # Bouton rouge de suppression
        self.btn_delete_key = QPushButton("🗑️ Supprimer", self)
        self.btn_delete_key.setObjectName("DeleteBtn")
        self.btn_delete_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete_key.clicked.connect(self._on_delete_key)
        
        key_layout = QHBoxLayout()
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self.edit_key, 1)
        key_layout.addWidget(self.btn_delete_key)
        
        form.addRow(self.lbl_key, key_layout)

        # Message de retour visuel vert de réussite (masqué par défaut)
        self.lbl_success_msg = QLabel(self)
        self.lbl_success_msg.setStyleSheet("color: #38a169; font-weight: bold; font-size: 11px; background: transparent; border: none;")
        self.lbl_success_msg.setVisible(False)
        form.addRow("", self.lbl_success_msg)


        # 3. Activation d'un point d'accès personnalisé (Custom Base URL)
        self.chk_custom_base = QCheckBox("Use custom base URL", self)
        self.chk_custom_base.setChecked(self.use_custom_base)
        self.chk_custom_base.toggled.connect(self._on_custom_base_toggled)
        form.addRow("", self.chk_custom_base)

        self.edit_base_url = QLineEdit(self)
        self.edit_base_url.setText(self.custom_base_url)
        self.edit_base_url.setVisible(self.use_custom_base)
        form.addRow("Custom Base URL", self.edit_base_url)

        # 4. Sélection du Modèle (Editable pour permettre à l'utilisateur d'écrire son propre modèle)
        self.combo_model = QComboBox(self)
        self.combo_model.setEditable(True)
        form.addRow("Model", self.combo_model)

        layout.addLayout(form)

        # Note d'information de sécurité
        info_lbl = QLabel(
            "This key is stored locally and only used to make secure, "
            "direct API requests from this application.", self
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #718096; font-size: 10px; font-weight: normal; margin-top: 10px;")
        layout.addWidget(info_lbl)

        # Boutons OK / Annuler
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #edf2f7;
                border: 1px solid #cbd5e0;
                border-radius: 4px;
                color: #2d3748;
                padding: 6px 16px;
                font-family: 'Segoe UI', sans-serif;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4f8ef7;
                color: white;
                border-color: #4f8ef7;
            }
        """)
        buttons.accepted.connect(self._on_save_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_provider_changed(self, provider_name):
        """Met à jour dynamiquement les formulaires selon le fournisseur d'API."""
        # Masquer le message vert de réussite de l'ancienne suppression
        self.lbl_success_msg.setVisible(False)
        
        config = DEFAULT_PROVIDERS[provider_name]
        
        # Gérer la visibilité de la clé d'API (Masqué pour Ollama Local)
        if provider_name == "Ollama (Local)":
            self.lbl_key.setVisible(False)
            self.edit_key.setVisible(False)
            self.chk_custom_base.setChecked(True)
            self.chk_custom_base.setEnabled(False)  # Toujours activé pour Ollama
            self.edit_base_url.setVisible(True)
        else:
            self.lbl_key.setVisible(True)
            self.lbl_key.setText(f"{provider_name} API Key")
            self.edit_key.setVisible(True)
            self.chk_custom_base.setEnabled(True)
            self.chk_custom_base.setChecked(self.chk_custom_base.isChecked())
            
            # Charger la clé enregistrée pour ce fournisseur spécifique si elle existe
            saved_key = self.keys_dict.get(provider_name, "")
            self.edit_key.setText(saved_key)

        # Mettre à jour la liste des modèles suggérés
        self.combo_model.clear()
        self.combo_model.addItems(config["models"])
        
        # Restaurer le dernier modèle sélectionné pour ce fournisseur
        saved_model = self.settings.value(f"last_model_{provider_name}", config["models"][0])
        self.combo_model.setCurrentText(saved_model)

    def _on_custom_base_toggled(self, checked):
        """Affiche ou masque le champ de l'adresse IP de base."""
        self.edit_base_url.setVisible(checked)
    
    def _on_delete_key(self):
        """Supprime de manière sécurisée la clé d'API de la mémoire et du système."""
        provider_name = self.combo_provider.currentText()
        config = DEFAULT_PROVIDERS[provider_name]
        
        # 1. Vider le champ de texte visuellement
        self.edit_key.clear()
        
        # 2. Supprimer la clé du dictionnaire en mémoire vive
        if provider_name in self.keys_dict:
            self.keys_dict.pop(provider_name, None)
            
        # 3. Enregistrer le dictionnaire vidé de manière persistante sur le disque
        self.settings.setValue("api_keys_by_provider", json.dumps(self.keys_dict))
        
        # 4. Supprimer la clé de la variable d'environnement système active
        if config["key_env"] and config["key_env"] in os.environ:
            os.environ.pop(config["key_env"], None)
            
        # 5. Afficher le message vert de réussite
        self.lbl_success_msg.setText(f"✓ Clé API pour '{provider_name}' supprimée avec succès.")
        self.lbl_success_msg.setVisible(True)


    def _on_save_settings(self):
        """Valide et enregistre la configuration."""
        provider_name = self.combo_provider.currentText()
        model_name = self.combo_model.currentText().strip()
        api_key = self.edit_key.text().strip()
        base_url = self.edit_base_url.text().strip()
        use_custom_base = self.chk_custom_base.isChecked()

        if not model_name:
            QMessageBox.warning(self, "Erreur", "Veuillez spécifier ou choisir un modèle d'IA.")
            return

        if provider_name != "Ollama (Local)" and not api_key:
            # Simple avertissement (l'utilisateur peut vouloir la configurer plus tard)
            QMessageBox.information(
                self, "Information", 
                f"Attention : Vous n'avez pas entré de clé d'API pour {provider_name}.\n"
                "La traduction risque de ne pas fonctionner."
            )

        # Sauvegarde persistante des variables
        self.settings.setValue("provider", provider_name)
        self.settings.setValue("use_custom_base", use_custom_base)
        self.settings.setValue("custom_base_url", base_url)
        self.settings.setValue(f"last_model_{provider_name}", model_name)

        # Enregistrer la clé d'API spécifique dans notre dictionnaire local
        if provider_name != "Ollama (Local)":
            self.keys_dict[provider_name] = api_key
            self.settings.setValue("api_keys_by_provider", json.dumps(self.keys_dict))

        # Configurer les variables d'environnement système pour que LiteLLM puisse les lire
        config = DEFAULT_PROVIDERS[provider_name]
        if config["key_env"]:
            os.environ[config["key_env"]] = api_key
            
        if use_custom_base:
            # Enregistrer la variable d'environnement de base URL pour les services compatibles
            os.environ[f"{config['prefix'].upper()}_API_BASE"] = base_url

        self.accept()