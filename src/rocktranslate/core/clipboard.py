"""
RockTranslate — read what the user copied, to open a PDF from it.

Ctrl+C on a file in the Windows Explorer / macOS Finder copies the FILE (not
its path as text): the web view cannot see that path, so it is read here.
Returns the copied file paths first, then the copied text (a link, a path).
Every platform call is best-effort: nothing found -> empty list.

Path: src/rocktranslate/core/clipboard.py
Author: RockTranslate Contributors
License: MIT License
"""

import os
import shutil
import subprocess
import sys
from typing import List

from loguru import logger

from .proc import NO_WINDOW


def _windows() -> List[str]:
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT, CF_HDROP = 13, 15
    user32, kernel32, shell32 = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.shell32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]

    out: List[str] = []
    if not user32.OpenClipboard(None):
        return out
    try:
        if user32.IsClipboardFormatAvailable(CF_HDROP):
            handle = user32.GetClipboardData(CF_HDROP)
            if handle:
                count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
                for i in range(count):
                    size = shell32.DragQueryFileW(handle, i, None, 0) + 1
                    buffer = ctypes.create_unicode_buffer(size)
                    shell32.DragQueryFileW(handle, i, buffer, size)
                    out.append(buffer.value)
        if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            pointer = kernel32.GlobalLock(handle) if handle else None
            if pointer:
                try:
                    out.append(ctypes.wstring_at(pointer))
                finally:
                    kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    return out


def _run(cmd: List[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3, **NO_WINDOW)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _macos() -> List[str]:
    out: List[str] = []
    path = _run(["osascript", "-e", "POSIX path of (the clipboard as «class furl»)"]).strip()
    if path:
        out.append(path)
    text = _run(["pbpaste"])
    if text.strip():
        out.append(text)
    return out


def _linux() -> List[str]:
    out: List[str] = []
    if shutil.which("wl-paste"):
        uris = _run(["wl-paste", "--no-newline", "--type", "text/uri-list"])
        text = _run(["wl-paste", "--no-newline"])
    elif shutil.which("xclip"):
        uris = _run(["xclip", "-selection", "clipboard", "-o", "-t", "text/uri-list"])
        text = _run(["xclip", "-selection", "clipboard", "-o"])
    else:
        return out
    out += [u.strip() for u in uris.splitlines() if u.strip() and not u.startswith("#")]
    if text.strip():
        out.append(text)
    return out


def read_clipboard() -> List[str]:
    """Copied file paths first, then the copied text. Empty list if nothing usable."""
    try:
        if os.name == "nt":
            return _windows()
        if sys.platform == "darwin":
            return _macos()
        return _linux()
    except Exception as e:                     # never break the UI for a clipboard read
        logger.warning(f"Clipboard could not be read: {e}")
        return []
