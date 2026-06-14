"""
RockTranslate — Standard JSON-Backed Persistent Settings Manager
Path: src/rocktranslate/core/config_manager.py

Handles cross-platform storage of configuration dictionaries inside standard 
OS filesystems without relying on PyQt6 registries. Integrates automatic 
migration hooks for legacy QSettings databases.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from PyQt6.QtCore import QSettings
except ImportError:
    QSettings = None


class ConfigManager:
    """
    Unified JSON config reader/writer.
    Stored under:
      - Windows: AppData/Local/RockTranslate/config.json
      - macOS/Linux: ~/.config/rocktranslate/config.json
    """
    def __init__(self, filename: str = "config.json") -> None:
        if os.name == "nt":
            app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
            self.config_dir = Path(app_data) / "RockTranslate"
        else:
            self.config_dir = Path.home() / ".config" / "rocktranslate"

        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self.config_dir / filename
        self.data: Dict[str, Dict[str, Any]] = {}

        if self.filepath.exists():
            self.data = self._load()
        else:
            # First-run safe recovery migration from legacy QSettings registries
            self.data = self._load()
            if QSettings is not None:
                self._migrate_legacy_settings()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Error writing database file: {e}")

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Retrieves a configuration value from a specific category section."""
        return self.data.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any) -> None:
        """Sets a configuration value and serializes immediately."""
        if section not in self.data:
            self.data[section] = {}
        self.data[section][key] = value
        self._save()

    def clear(self) -> None:
        """Wipes the local settings file completely."""
        self.data = {}
        self._save()

    def _migrate_legacy_settings(self) -> None:
        """Imports configurations from system registry spaces on migration runs."""
        print("[Config] Initiating legacy settings migration...")
        migrated = False

        # 1. API Configurations
        try:
            old_api = QSettings("RockTranslate", "APIConfig")
            if old_api.allKeys():
                self.data["APIConfig"] = {
                    "provider": old_api.value("provider", "Google Gemini"),
                    "custom_base_url": old_api.value("custom_base_url", "http://localhost:11434"),
                    "use_custom_base": old_api.value("use_custom_base", False, type=bool)
                }
                
                # Migrate provider API keys
                keys_raw = old_api.value("api_keys_by_provider", "{}")
                try:
                    self.data["APIConfig"]["api_keys_by_provider"] = (
                        json.loads(keys_raw) if isinstance(keys_raw, str) else keys_raw
                    )
                except Exception:
                    self.data["APIConfig"]["api_keys_by_provider"] = {}
                
                # Migrate last selected model for each provider
                for k in old_api.allKeys():
                    if k.startswith("last_model_"):
                        self.data["APIConfig"][k] = old_api.value(k, "")
                migrated = True
        except Exception as e:
            print(f"[Config] Failed migrating APIConfig: {e}")

        # 2. System Configurations
        try:
            old_sys = QSettings("RockTranslate", "SystemConfig")
            if old_sys.allKeys():
                self.data["SystemConfig"] = {
                    "clear_cache_on_exit": old_sys.value("clear_cache_on_exit", True, type=bool),
                    "pdf2htmlex_path_override": old_sys.value("pdf2htmlex_path_override", "", type=str),
                    "pdfjs_path_override": old_sys.value("pdfjs_path_override", "", type=str),
                    "ui_language": old_sys.value("ui_language", "en", type=str)
                }
                migrated = True
        except Exception as e:
            print(f"[Config] Failed migrating SystemConfig: {e}")

        # 3. Recent Files Registry
        try:
            old_rec = QSettings("RockTranslate", "RecentFiles")
            if old_rec.allKeys():
                rec_raw = old_rec.value("recent_list", [])
                try:
                    recent_list = json.loads(rec_raw) if isinstance(rec_raw, str) else list(rec_raw)
                except Exception:
                    recent_list = []
                self.data["RecentFiles"] = {
                    "recent_list": recent_list
                }
                migrated = True
        except Exception as e:
            print(f"[Config] Failed migrating RecentFiles: {e}")

        if migrated:
            self._save()
            print("[Config] Settings successfully migrated to JSON.")


# Global singleton instance for easy imports across domains
config_db = ConfigManager()