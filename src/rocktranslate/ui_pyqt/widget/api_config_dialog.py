"""
RockTranslate — Contextual and Dynamic API Configuration Dialog
Path: src/rocktranslate/ui_pyqt/widget/api_config_dialog.py

This module implements the settings panel (similar to Cline's interface), 
allowing developers and users to configure API keys, custom base URLs, 
and fallback model pipelines.

All provider structures are imported from core.constants, and all user-facing
elements are wrapped in QObject.tr() for full i18n support.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import json
from typing import Dict, Any, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, 
    QComboBox, QLineEdit, QCheckBox, QPushButton, QDialogButtonBox, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt, QSettings

# Safe fallback imports supporting both standard package modules and direct scripts
try:
    from src.rocktranslate.core.constants import DEFAULT_PROVIDERS
except ImportError:
    from src.rocktranslate.core.constants import DEFAULT_PROVIDERS


class ApiKeyLineEdit(QLineEdit):
    """
    Custom QLineEdit component that dynamically updates its placeholder hint 
    text during active focus events.
    """

    def focusInEvent(self, event: Any) -> None:
        self.setPlaceholderText(self.tr("Enter your API key"))
        super().focusInEvent(event)

    def focusOutEvent(self, event: Any) -> None:
        self.setPlaceholderText("")
        super().focusOutEvent(event)


class APIConfigDialog(QDialog):
    """
    Modular AI Configuration dialog allowing direct integration with 
    multiple LLM providers (Gemini, OpenAI, Claude, DeepSeek, local Ollama, etc.).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the configuration modal, loading settings, stylesheets, and grids.

        Args:
            parent: Optional parent QWidget container.
        """
        super().__init__(parent)
        self.setWindowTitle(self.tr("API Configuration"))
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

        # Settings memory mapping properties
        self.settings = QSettings("RockTranslate", "APIConfig")
        self.current_provider: str = "Google Gemini"
        self.custom_base_url: str = "http://localhost:11434"
        self.use_custom_base: bool = False
        self.keys_dict: Dict[str, str] = {}

        self._load_settings()
        self._build_ui()
        self._on_provider_changed(self.combo_provider.currentText())

    def _load_settings(self) -> None:
        """ Retrieves persisted system settings from the registry database. """
        self.current_provider = self.settings.value("provider", "Google Gemini")
        self.custom_base_url = self.settings.value("custom_base_url", "http://localhost:11434")
        self.use_custom_base = self.settings.value("use_custom_base", False, type=bool)
        
        # Load local dynamic API Key dictionary
        raw_keys = self.settings.value("api_keys_by_provider", {})
        if isinstance(raw_keys, str):
            try:
                self.keys_dict = json.loads(raw_keys)
            except Exception:
                self.keys_dict = {}
        elif isinstance(raw_keys, dict):
            self.keys_dict = raw_keys
        else:
            self.keys_dict = {}

    def _build_ui(self) -> None:
        """ Renders the configuration input form structures. """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        form = QFormLayout()
        form.setSpacing(12)

        # 1. API Provider Selector Dropdown
        self.combo_provider = QComboBox(self)
        self.combo_provider.addItems(list(DEFAULT_PROVIDERS.keys()))
        self.combo_provider.setCurrentText(self.current_provider)
        self.combo_provider.currentTextChanged.connect(self._on_provider_changed)
        form.addRow(self.tr("API Provider"), self.combo_provider)

        # 2. Dynamic Masked API Key Input Field
        self.lbl_key = QLabel(self.tr("API Key"), self)
        self.edit_key = ApiKeyLineEdit(self)
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        
        # Stylized Delete Key button
        self.btn_delete_key = QPushButton(self.tr("🗑️ Delete"), self)
        self.btn_delete_key.setObjectName("DeleteBtn")
        self.btn_delete_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete_key.clicked.connect(self._on_delete_key)
        
        key_layout = QHBoxLayout()
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self.edit_key, 1)
        key_layout.addWidget(self.btn_delete_key)
        
        form.addRow(self.lbl_key, key_layout)

        # Green success feedback text (Hidden by default)
        self.lbl_success_msg = QLabel(self)
        self.lbl_success_msg.setStyleSheet(
            "color: #38a169; font-weight: bold; font-size: 11px; background: transparent; border: none;"
        )
        self.lbl_success_msg.setVisible(False)
        form.addRow("", self.lbl_success_msg)

        # 3. Custom Base URL checkbox triggers
        self.chk_custom_base = QCheckBox(self.tr("Use custom base URL"), self)
        self.chk_custom_base.setChecked(self.use_custom_base)
        self.chk_custom_base.toggled.connect(self._on_custom_base_toggled)
        form.addRow("", self.chk_custom_base)

        self.edit_base_url = QLineEdit(self)
        self.edit_base_url.setText(self.custom_base_url)
        self.edit_base_url.setVisible(self.use_custom_base)
        form.addRow(self.tr("Custom Base URL"), self.edit_base_url)

        # 4. Target LLM Model selection
        self.combo_model = QComboBox(self)
        self.combo_model.setEditable(True)
        form.addRow(self.tr("Model"), self.combo_model)

        layout.addLayout(form)

        # System security disclosure
        info_lbl = QLabel(
            self.tr(
                "This key is stored locally and only used to make secure, "
                "direct API requests from this application."
            ),
            self
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #718096; font-size: 14px; font-weight: normal; margin-top: 10px;")
        layout.addWidget(info_lbl)

        # Standard dialog confirmation button maps
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

    def _on_provider_changed(self, provider_name: str) -> None:
        """ Updates visual components dynamically to match the selected API provider. """
        self.lbl_success_msg.setVisible(False)
        config: Dict[str, Any] = DEFAULT_PROVIDERS[provider_name]

        # --- FIX: Load the basic URL option in a way that is specific to EACH provider ---
        use_custom_base = self.settings.value(f"use_custom_base_{provider_name}", False, type=bool)
        custom_base_url = self.settings.value(
            f"custom_base_url_{provider_name}", 
            "http://localhost:11434" if provider_name == "Ollama (Local)" else ""
        )
        
        if provider_name == "Ollama (Local)":
            self.lbl_key.setVisible(False)
            self.edit_key.setVisible(False)
            self.chk_custom_base.setChecked(True)
            self.chk_custom_base.setEnabled(False)  # Enforce custom endpoint for Ollama
            # Forcer l'URL d'Ollama
            self.edit_base_url.setText(custom_base_url if custom_base_url else "http://localhost:11434")
            self.edit_base_url.setVisible(True)
            self.btn_delete_key.setVisible(False)
        else:
            self.lbl_key.setVisible(True)
            self.lbl_key.setText(self.tr("{provider_name} API Key").format(provider_name=provider_name))
            self.edit_key.setVisible(True)
            
            # Load the specific settings for this third-party provider
            self.chk_custom_base.setEnabled(True)
            self.chk_custom_base.setChecked(use_custom_base)
            self.edit_base_url.setText(custom_base_url)
            self.edit_base_url.setVisible(use_custom_base)
            self.btn_delete_key.setVisible(True)
            
            # Load locally active key
            saved_key = self.keys_dict.get(provider_name, "")
            self.edit_key.setText(saved_key)

        # Populate suggested model lists
        self.combo_model.clear()
        self.combo_model.addItems(config["models"])
        
        # Load last used model for the selected provider
        saved_model = self.settings.value(f"last_model_{provider_name}", config["models"][0])
        self.combo_model.setCurrentText(saved_model)

    def _on_custom_base_toggled(self, checked: bool) -> None:
        """ Displays or hides the custom URL input field. """
        self.edit_base_url.setVisible(checked)
    
    def _on_delete_key(self) -> None:
        """ Securely deletes the selected API Key from memory and OS environment space. """
        provider_name = self.combo_provider.currentText()
        config: Dict[str, Any] = DEFAULT_PROVIDERS[provider_name]
        
        self.edit_key.clear()
        
        if provider_name in self.keys_dict:
            self.keys_dict.pop(provider_name, None)
            
        self.settings.setValue("api_keys_by_provider", json.dumps(self.keys_dict))
        
        # Wipe the active system OS environment variable
        env_key = config.get("key_env")
        if env_key and isinstance(env_key, str) and env_key in os.environ:
            os.environ.pop(env_key, None)
            
        # Display localized success message
        success_text = self.tr("API Key for '{provider}' successfully deleted.").format(provider=provider_name)
        self.lbl_success_msg.setText(f"✓ {success_text}")
        self.lbl_success_msg.setVisible(True)

    def _on_save_settings(self) -> None:
        """ Validates entries and saves current configuration settings. """
        provider_name = self.combo_provider.currentText()
        model_name = self.combo_model.currentText().strip()
        api_key = self.edit_key.text().strip()
        base_url = self.edit_base_url.text().strip()
        use_custom_base = self.chk_custom_base.isChecked()

        if not model_name:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Please specify or choose an AI model."))
            return

        if provider_name != "Ollama (Local)" and not api_key:
            QMessageBox.information(
                self, 
                self.tr("Information"), 
                self.tr(
                    "Warning: You have not entered an API key for {provider}.\n"
                    "Translation may not work."
                ).format(provider=provider_name)
            )

        # Update persisted fields
        self.settings.setValue("provider", provider_name)
        self.settings.setValue(f"last_model_{provider_name}", model_name)

        # --- FIX: Save in ISOLATION per API provider ---
        self.settings.setValue(f"use_custom_base_{provider_name}", use_custom_base)
        self.settings.setValue(f"custom_base_url_{provider_name}", base_url)
        
        # Doublons de secours pour la lecture globale par les Workers actifs
        self.settings.setValue("use_custom_base", use_custom_base)
        self.settings.setValue("custom_base_url", base_url)

        if provider_name != "Ollama (Local)":
            self.keys_dict[provider_name] = api_key
            self.settings.setValue("api_keys_by_provider", json.dumps(self.keys_dict))

        # Inject standard OS environment keys for dynamic LiteLLM router execution
        config: Dict[str, Any] = DEFAULT_PROVIDERS[provider_name]
        env_key = config.get("key_env")
        if env_key and isinstance(env_key, str):
            os.environ[env_key] = api_key
            
        if use_custom_base:
            prefix = config.get("prefix")
            if prefix and isinstance(prefix, str):
                os.environ[f"{prefix.upper()}API_BASE"] = base_url

        self.accept()