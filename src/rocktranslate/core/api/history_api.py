"""
RockTranslate — Persistent Recent Files and Dialog Web API Mixin
Path: src/rocktranslate/core/api/history_api.py

Handles native platform file/folder dialogues and verified recent files tracking.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.1
"""

import os
import webview
from typing import List, Dict, Any

from ..config_manager import config_db


class HistoryApiMixin:
    """
    Mixin class handling document historical registries and native file operations.
    """
    def get_recent_files(self) -> List[Dict[str, str]]:
        try:
            files_list = config_db.get("RecentFiles", "recent_list", [])
            if not isinstance(files_list, list):
                files_list = []

            verified_files = []
            for file_path in files_list:
                if os.path.exists(file_path):
                    verified_files.append({
                        "name": os.path.basename(file_path),
                        "path": file_path
                    })
            return verified_files
        except Exception as error:
            print(f"[API Error] Could not read recent files JSON registry: {error}")
            return []

    def open_file_dialog(self) -> Dict[str, str]:
        if not hasattr(self, "_window") or not self._window:
            return {"status": "error", "message": "Host window not resolved."}

        file_types = ("PDF Documents (*.pdf)", "All files (*.*)")
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=file_types
        )

        if result and len(result) > 0:
            file_path = result[0]
            return {"status": "success", "path": file_path}
            
        return {"status": "cancelled"}

    # ── PATH BROWSER DIALOG TRIGGERS ──
    def browse_folder_dialog(self) -> Dict[str, str]:
        """
        Triggers native platform directories selection popups.
        """
        if not hasattr(self, "_window") or not self._window:
            return {"status": "error", "message": "Host window not resolved."}

        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return {"status": "success", "path": os.path.normpath(result[0])}
        return {"status": "cancelled"}

    def browse_binary_dialog(self) -> Dict[str, str]:
        """
        Triggers native platform executables selector popups.
        """
        if not hasattr(self, "_window") or not self._window:
            return {"status": "error", "message": "Host window not resolved."}

        file_filter = "Executables (*.exe)" if os.name == "nt" else "All Files (*)"
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(file_filter, "All files (*.*)")
        )

        if result and len(result) > 0:
            return {"status": "success", "path": os.path.normpath(result[0])}
        return {"status": "cancelled"}

    def clear_recent_history(self) -> None:
        config_db.set("RecentFiles", "recent_list", [])
        print("[API] Recent files history cleared successfully.")


    def get_document_properties(self, file_path: str) -> Dict[str, Any]:
        """
        Extracts structural PDF metadata and merges dynamic translation session stats on-demand.
        """
        from ..pdf_metadata import get_pdf_metadata
        
        # We can construct or fetch some mock/real translation stats for the modal.
        # These will be updated dynamically during the workspace integration pass.
        trans_stats = {
            "trans_status": "Not translated",
            "trans_lang": "None",
            "trans_model": "None",
            "trans_segments": "0 / 0",
            "trans_scale_avg": "100.0%",
            "trans_date": "Unknown"
        }
        
        try:
            return get_pdf_metadata(file_path, trans_stats)
        except Exception as error:
            print(f"[API Error] Could not extract PDF metadata: {error}")
            return {"file_path": file_path, "file_size": "Unknown"}