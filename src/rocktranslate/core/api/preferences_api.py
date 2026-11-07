"""
RockTranslate — Preferences & usage statistics Web API mixin
Path: src/rocktranslate/core/api/preferences_api.py

One validated entry point for every user-tunable setting (auto-saved by the
Settings window), plus usage accounting (tokens, estimated cost, time) and
workspace cache management.

License: MIT License
"""

import os
import shutil
import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from ..config_manager import config_db
from ..constants import (
    DEFAULT_PARALLEL_REQUESTS, DEFAULT_TEMPERATURE, MAX_RETRIES, MAX_SEGMENTS_PER_BATCH,
    REQUEST_TIMEOUT_SECONDS, SLIDING_CONTEXT_MAX_SIZE, SUPPORTED_LANGUAGES, THRESHOLD_PX,
)

# key -> (config section, default, kind, min, max)
PREFERENCE_SCHEMA: Dict[str, Tuple[str, Any, str, Optional[float], Optional[float]]] = {
    # Translation engine
    "temperature": ("TranslationConfig", DEFAULT_TEMPERATURE, "float", 0.0, 2.0),
    "parallel_requests": ("TranslationConfig", DEFAULT_PARALLEL_REQUESTS, "int", 1, 16),
    "sliding_context_size": ("TranslationConfig", SLIDING_CONTEXT_MAX_SIZE, "int", 0, 20),
    "max_segments_per_batch": ("TranslationConfig", MAX_SEGMENTS_PER_BATCH, "int", 5, 200),
    "max_retries": ("TranslationConfig", MAX_RETRIES, "int", 1, 10),
    "request_timeout": ("TranslationConfig", REQUEST_TIMEOUT_SECONDS, "float", 20, 900),
    "disable_reasoning": ("TranslationConfig", True, "bool", None, None),
    "custom_glossary": ("TranslationConfig", "", "str", None, None),
    # Layout
    "threshold_px": ("TranslationConfig", THRESHOLD_PX, "float", 2, 80),
    # General / system
    "target_lang": ("SystemConfig", "French", "str", None, None),
    "ui_theme": ("SystemConfig", "system", "str", None, None),
    "clear_cache_on_exit": ("SystemConfig", False, "bool", None, None),
    "pdf2htmlex_path_override": ("SystemConfig", "", "str", None, None),
    "pdfjs_path_override": ("SystemConfig", "", "str", None, None),
    "browser_path_override": ("SystemConfig", "", "str", None, None),
    "show_cost_estimates": ("SystemConfig", True, "bool", None, None),
    "hover_original": ("SystemConfig", True, "bool", None, None),
}

_EMPTY_TOTALS = {
    "runs": 0, "segments": 0, "prompt_tokens": 0, "completion_tokens": 0,
    "requests": 0, "cost_usd": 0.0, "seconds": 0.0,
}


def _coerce(kind: str, value: Any, lo: Optional[float], hi: Optional[float]) -> Any:
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind in ("int", "float"):
        num = float(value)
        if lo is not None:
            num = max(lo, num)
        if hi is not None:
            num = min(hi, num)
        return int(round(num)) if kind == "int" else round(num, 3)
    return str(value if value is not None else "").strip()


def record_run_usage(model: str, usage: Dict[str, Any], seconds: float, segments: int) -> Dict[str, Any]:
    """Adds one translation run to the persistent usage statistics."""
    stats = config_db.get("UsageStats", "totals", None) or dict(_EMPTY_TOTALS)
    stats = {**_EMPTY_TOTALS, **stats}
    stats["runs"] += 1
    stats["segments"] += int(segments)
    stats["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
    stats["completion_tokens"] += int(usage.get("completion_tokens", 0))
    stats["requests"] += int(usage.get("requests", 0))
    stats["cost_usd"] = round(stats["cost_usd"] + float(usage.get("cost_usd", 0.0)), 6)
    stats["seconds"] = round(stats["seconds"] + float(seconds), 1)
    config_db.set("UsageStats", "totals", stats)

    by_model = config_db.get("UsageStats", "by_model", None) or {}
    entry = {**_EMPTY_TOTALS, **by_model.get(model, {})}
    entry["runs"] += 1
    entry["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
    entry["completion_tokens"] += int(usage.get("completion_tokens", 0))
    entry["cost_usd"] = round(entry["cost_usd"] + float(usage.get("cost_usd", 0.0)), 6)
    by_model[model] = entry
    config_db.set("UsageStats", "by_model", by_model)

    last = {
        "model": model, "segments": int(segments), "seconds": round(float(seconds), 1),
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": int(usage.get("completion_tokens", 0)),
        "cost_usd": round(float(usage.get("cost_usd", 0.0)), 6),
        "finished_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    config_db.set("UsageStats", "last_run", last)
    return last


class PreferencesApiMixin:
    """Settings window backend: get/set every preference, usage stats, cache."""

    def get_app_version(self) -> str:
        from ... import __version__
        return __version__

    def get_preferences(self) -> Dict[str, Any]:
        prefs = {key: config_db.get(section, key, default)
                 for key, (section, default, _k, _lo, _hi) in PREFERENCE_SCHEMA.items()}
        prefs["supported_languages"] = list(SUPPORTED_LANGUAGES.values())
        prefs["config_dir"] = str(config_db.config_dir)
        return prefs

    def set_preference(self, key: str, value: Any) -> Dict[str, Any]:
        """Validates, clamps and saves ONE preference. Returns the stored value."""
        if key not in PREFERENCE_SCHEMA:
            return {"status": "error", "message": f"Unknown setting: {key}"}
        section, _default, kind, lo, hi = PREFERENCE_SCHEMA[key]
        try:
            stored = _coerce(kind, value, lo, hi)
        except (TypeError, ValueError):
            return {"status": "error", "message": f"Invalid value for {key}"}
        if key == "ui_theme" and stored not in ("light", "dark", "system"):
            return {"status": "error", "message": "Invalid theme"}
        if key.endswith("_path_override") and stored and not os.path.exists(stored):
            return {"status": "error", "message": f"Path not found: {stored}"}
        config_db.set(section, key, stored)
        return {"status": "success", "value": stored}

    def reset_preferences(self) -> Dict[str, Any]:
        """Restores every engine/layout preference to its default (keys and paths kept)."""
        for key, (section, default, _k, _lo, _hi) in PREFERENCE_SCHEMA.items():
            if section == "TranslationConfig" and key != "custom_glossary":
                config_db.set(section, key, default)
        return {"status": "success", "preferences": self.get_preferences()}

    # ── Usage statistics ──

    def get_usage_stats(self) -> Dict[str, Any]:
        totals = {**_EMPTY_TOTALS, **(config_db.get("UsageStats", "totals", None) or {})}
        return {
            "totals": totals,
            "by_model": config_db.get("UsageStats", "by_model", None) or {},
            "last_run": config_db.get("UsageStats", "last_run", None),
        }

    def reset_usage_stats(self) -> Dict[str, str]:
        config_db.set("UsageStats", "totals", dict(_EMPTY_TOTALS))
        config_db.set("UsageStats", "by_model", {})
        config_db.set("UsageStats", "last_run", None)
        return {"status": "success"}

    # ── Cache management ──

    def get_cache_info(self) -> Dict[str, Any]:
        cache_dir = str(config_db.get_cache_dir())
        total, documents = 0, 0
        try:
            for entry in os.scandir(cache_dir):
                if entry.is_dir():
                    documents += 1
                    for root, _dirs, files in os.walk(entry.path):
                        for name in files:
                            try:
                                total += os.path.getsize(os.path.join(root, name))
                            except OSError:
                                pass
        except OSError:
            pass
        return {"path": cache_dir, "documents": documents, "size_mb": round(total / 1e6, 1)}

    def clear_translation_cache(self) -> Dict[str, Any]:
        """Deletes cached workspaces and translations, except the open document's."""
        cache_dir = str(config_db.get_cache_dir())
        keep = getattr(self, "_document_hash", None)
        removed = 0
        try:
            for entry in os.scandir(cache_dir):
                if entry.is_dir() and entry.name != keep:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    removed += 1
        except OSError as e:
            logger.warning(f"Cache cleanup failed: {e}")
        return {"status": "success", "removed": removed, **self.get_cache_info()}

    def open_config_folder(self) -> None:
        """Reveals the configuration folder (logs, cache) in the file manager."""
        import subprocess
        import sys
        path = str(config_db.config_dir)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            logger.warning(f"Could not open {path}: {e}")
