"""
RockTranslate — Standard JSON-Backed Persistent Settings Manager
Path: src/rocktranslate/core/config_manager.py

Provides cross-platform storage for application configuration settings using standard
OS filesystems, eliminating any runtime dependency on PyQt6 registry utilities.

Typical storage locations:
  - Windows: %LOCALAPPDATA%/RockTranslate/config.json
  - macOS/Linux: ~/.config/rocktranslate/config.json

Author: RockTranslate Contributors
License: MIT License
Version: 1.1.0
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """
    Unified JSON configuration file reader and writer.
    Handles configuration parsing, directory generation, and safe defaults fallback.
    """

    def __init__(self, filename: str = "config.json") -> None:
        """
        Initializes the configuration directory path based on the host OS platform,
        guarantees target directory existence, and loads stored settings.

        Args:
            filename: The target settings filename on disk (default is 'config.json').
        """
        if os.name == "nt":
            # Windows fallback chain for writable AppData directory routing
            app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
            self.config_dir = Path(app_data) / "RockTranslate"
        else:
            # macOS and Linux standard Unix configuration directories
            self.config_dir = Path.home() / ".config" / "rocktranslate"

        # Ensure configuration directory structure exists on host filesystem
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self.config_dir / filename
        self.data: Dict[str, Dict[str, Any]] = {}

        # Safely populate active configurations from local storage
        self.data = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        """
        Parses and decodes the configuration file from disk.

        Returns:
            Dict[str, Dict[str, Any]]: The loaded configuration dictionary, or an empty
                                       dictionary if the file is missing or invalid.
        """
        if not self.filepath.exists():
            return {}

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
                return loaded_data if isinstance(loaded_data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            # Prevent app startup crashes on corrupt settings files by returning an empty state
            print(f"[Config] Error decoding configuration database: {e}")
            return {}

    def _save(self) -> None:
        """
        Serializes current settings map and writes it to disk.
        """
        try:
            # Defensive target directory creation check
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except OSError as e:
            print(f"[Config] Error writing settings database: {e}")

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """
        Retrieves a setting value from a specific section category.

        Args:
            section: Name of the configuration section (e.g., 'SystemConfig').
            key: Name of the targeted configuration parameter (e.g., 'ui_language').
            default: The fallback value to return if the key/section is not found.

        Returns:
            Any: The stored configuration value, or the specified default value.
        """
        return self.data.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any) -> None:
        """
        Sets a configuration value under a specific section category and
        serializes the updated settings structure to disk instantly.

        Args:
            section: Name of the configuration section (e.g., 'APIConfig').
            key: Name of the configuration parameter (e.g., 'provider').
            value: The data payload to serialize (must be JSON serializable).
        """
        if section not in self.data:
            self.data[section] = {}
        self.data[section][key] = value
        self._save()

    def clear(self) -> None:
        """
        Wipes all configuration categories from runtime memory and saves
        an empty database state to disk.
        """
        self.data = {}
        self._save()


# Global singleton instance for standardized use across logical and bridge modules
config_db = ConfigManager()