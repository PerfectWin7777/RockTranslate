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
from loguru import logger
import json
import shutil
import threading
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
        self._lock = threading.RLock()

        # Safely populate active configurations from local storage
        self.data = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        """
        Parses the configuration file. A corrupt file falls back to the last
        good backup (config.json.bak) and is kept aside for inspection instead
        of being silently overwritten: saved API keys are never lost.
        """
        for path in (self.filepath, self._backup_path()):
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    if path != self.filepath:
                        logger.warning(f"[Config] Restored settings from backup: {path}")
                    return loaded_data
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                logger.error(f"[Config] Unreadable settings file {path}: {e}")
                if path == self.filepath:
                    try:
                        os.replace(path, path.with_name(path.name + ".corrupt"))
                    except OSError:
                        pass
        return {}

    def _backup_path(self) -> Path:
        return self.filepath.with_name(self.filepath.name + ".bak")

    def _save(self) -> None:
        """
        Thread-safe, atomic write: serialized under a lock, written to a
        temporary file, then swapped in. A crash or two threads saving at once
        can no longer leave a truncated config.json behind.
        """
        with self._lock:
            try:
                payload = json.dumps(self.data, indent=4, ensure_ascii=False)
                self.config_dir.mkdir(parents=True, exist_ok=True)
                tmp = self.filepath.with_name(self.filepath.name + ".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                if self.filepath.exists():
                    try:
                        shutil.copyfile(self.filepath, self._backup_path())
                    except OSError:
                        pass
                os.replace(tmp, self.filepath)
            except (OSError, TypeError, ValueError, RuntimeError) as e:
                logger.error(f"[Config] Error writing settings database: {e}")

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
        with self._lock:
            if section not in self.data:
                self.data[section] = {}
            self.data[section][key] = value
            self._save()

    def get_runtime_dir(self) -> Path:
        """
        Returns a user-writable directory for downloaded engines (pdf2htmlEX,
        chrome-headless-shell). Never inside site-packages, which is often
        read-only (system Python, shared virtualenvs).
        """
        runtime_dir = self.config_dir / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir

    def get_cache_dir(self) -> Path:
        """
        Returns the application cache directory (created on demand), used to
        store per-document prepared workspaces keyed by file hash.
        """
        cache_dir = self.config_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def clear(self) -> None:
        """
        Wipes all configuration categories from runtime memory and saves
        an empty database state to disk.
        """
        self.data = {}
        self._save()


# Global singleton instance for standardized use across logical and bridge modules
config_db = ConfigManager()