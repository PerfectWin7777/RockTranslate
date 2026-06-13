"""
RockTranslate — Observer-Pattern Persisted Recent Files Manager
Path: src/rocktranslate/ui_pyqt/utils/recent_files_manager.py

This module implements a standard QSettings-backed history manager.
It handles retrieving, adding, and pruning recent document paths.
It inherits from QObject to emit asynchronous 'history_changed' signals,
coordinating visual refreshes across multiple visual panels simultaneously.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
from typing import List, Optional
from PyQt6.QtCore import QObject, pyqtSignal, QSettings


class RecentFilesManager(QObject):
    """
    Centralized registry tracking the 10 most recently opened PDF documents.
    Validates physical filesystem availability on the fly.
    """
    # Signal emitted when files are appended or the history list is cleared
    history_changed = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """
        Initializes the manager, loading standard QSettings profiles.

        Args:
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self.settings = QSettings("RockTranslate", "RecentFiles")
        self.settings_key: str = "recent_list"
        self.max_limit: int = 20

    def get_recent_files(self) -> List[str]:
        """
        Retrieves the persisted list of files, automatically filtering out
        documents that no longer physically exist on the local disk.

        Returns:
            List[str]: Clean list of verified absolute file paths.
        """
        raw_list = self.settings.value(self.settings_key, [])
        recent_list: List[str] = []
        
        # Safe format adaptation to prevent QSettings serialization type bugs
        if isinstance(raw_list, str):
            recent_list = [raw_list]
        elif isinstance(raw_list, list):
            recent_list = [str(item) for item in raw_list]

        # Filter out files deleted from the local disk
        validated_list: List[str] = [
            path for path in recent_list if os.path.exists(path)
        ]

        # If files were missing, clean the registry database silently
        if len(validated_list) != len(recent_list):
            self.settings.setValue(self.settings_key, validated_list)
            
        return validated_list

    def add_file(self, file_path: str) -> None:
        """
        Appends an absolute document path to the top of the history list,
        enforcing historical limits and cleaning duplicates.

        Args:
            file_path: Absolute path to the PDF document.
        """
        if not file_path:
            return

        # Normalize slash directions and resolve the absolute filesystem path
        absolute_path: str = os.path.normpath(os.path.abspath(file_path))
        recent_list: List[str] = self.get_recent_files()

        # Create a normalized footprint for cross-platform case-insensitive comparisons
        normalized_target = os.path.normcase(absolute_path)

        # Filter out any duplicate pointing to the same physical file.
        # This cleanly handles variations in casing (e.g., drive letters) and slash directions.
        recent_list = [
            path for path in recent_list
            if os.path.normcase(os.path.normpath(path)) != normalized_target
        ]
            
        # Insert the new normalized path at the top of the history list
        recent_list.insert(0, absolute_path)
        recent_list = recent_list[:self.max_limit]  # Truncate to maximum limit boundaries

        self.settings.setValue(self.settings_key, recent_list)
        self.history_changed.emit()  # Signal connected visual panels to rebuild
        

    def clear_history(self) -> None:
        """ Securely purges all historical files from the registry database. """
        self.settings.setValue(self.settings_key, [])
        self.history_changed.emit()  # Notify all panels to clear displays