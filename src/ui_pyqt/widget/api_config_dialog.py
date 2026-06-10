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
        "models": ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-1.5-pro"]
    },
    "OpenAI": {
        "prefix": "openai/",
        "key_env": "OPENAI_API_KEY",
        "models": ["gpt-4o-mini", "gpt-4o"]
    },
    "DeepSeek": {
        "prefix": "deepseek/",
        "key_env": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"]
    },
    "Anthropic": {
        "prefix": "anthropic/",
        "key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022"]
    },
    "OpenRouter (Modèles Chinois etc.)": {
        "prefix": "openrouter/",
        "key_env": "OPENROUTER_API_KEY",
        "models": [
            "openrouter/deepseek/deepseek-chat",
            "openrouter/qwen/qwen-2.5-72b-instruct",
            "openrouter/google/gemini-2.5-flash"
        ]
    },
    "Mistral AI": {
        "prefix": "mistral/",
        "key_env": "MISTRAL_API_KEY",
        "models": ["mistral-large-latest", "open-mistral-nemo"]
    },
    "Moonshot (Kimi)": {
        "prefix": "moonshot/",
        "key_env": "MOONSHOT_API_KEY",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k"]
    },
    "Alibaba DashScope (Qwen)": {
        "prefix": "dashscope/",
        "key_env": "DASHSCOPE_API_KEY",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max"]
    },
    "Zhipu AI (GLM)": {
        "prefix": "zai/",
        "key_env": "ZAI_API_KEY",
        "models": ["glm-4.7", "glm-4.5"]
    },
    "Together AI": {
        "prefix": "together_ai/",
        "key_env": "TOGETHERAI_API_KEY",
        "models": ["togethercomputer/llama-2-70b-chat", "meta-llama/Llama-3-70b-chat-hf"]
    },
    "Groq": {
        "prefix": "groq/",
        "key_env": "GROQ_API_KEY",
        "models": ["llama3-70b-8192", "mixtral-8x7b-32768"]
    },
    "xAI (Grok)": {
        "prefix": "xai/",
        "key_env": "XAI_API_KEY",
        "models": ["grok-2-1212", "grok-beta"]
    },
    "Ollama (Local)": {
        "prefix": "ollama/",
        "key_env": "",
        "models": ["qwen2.5", "llama3", "mistral"]
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
        self.resize(500, 360)
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
        form.addRow(self.lbl_key, self.edit_key)

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