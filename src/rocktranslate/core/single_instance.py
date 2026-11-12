"""
RockTranslate — Single instance & "Open with RockTranslate"
Path: src/rocktranslate/core/single_instance.py

When RockTranslate is the PDF reader of the system, double-clicking a PDF
starts `RockTranslate.exe "C:\\path\\paper.pdf"`. If the app is already running,
the file must open in the existing window instead of a second app:

- the running instance listens on a loopback port (random, with a random
  token) recorded in <config>/instance.json;
- a new launch first tries to hand its file to that instance, and exits if
  the hand-off succeeded.

Author: RockTranslate Contributors
License: MIT License
"""

import json
import os
import secrets
import socket
import threading
from typing import Callable, List, Optional

from loguru import logger

from .config_manager import config_db

_INFO_FILE = "instance.json"


def documents_from_argv(argv: List[str]) -> List[str]:
    """PDF paths and http(s) links given on the command line (absolute paths)."""
    out = []
    for arg in argv:
        if arg.lower().startswith(("http://", "https://")):
            out.append(arg)
        elif arg.lower().endswith(".pdf") and os.path.isfile(arg):
            out.append(os.path.abspath(arg))
    return out


def _info_path() -> str:
    return str(config_db.config_dir / _INFO_FILE)


def hand_off(documents: List[str], timeout: float = 1.5) -> bool:
    """
    Sends `documents` to an already running instance. True if it accepted
    them (the caller then exits); False when no instance is running.
    """
    try:
        with open(_info_path(), encoding="utf-8") as f:
            info = json.load(f)
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=timeout) as s:
            s.sendall((json.dumps({"token": info["token"], "open": documents}) + "\n").encode("utf-8"))
            s.settimeout(timeout)
            return s.recv(16).startswith(b"OK")
    except (OSError, ValueError, KeyError):
        return False


def serve(on_open: Callable[[List[str]], None]) -> Optional[int]:
    """
    Starts the listener of the running instance (daemon thread). on_open
    receives the documents sent by later launches (empty list = just show
    the window). Returns the port, or None if it could not start.
    """
    token = secrets.token_urlsafe(16)
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(4)
    except OSError as e:
        logger.warning(f"Single-instance listener unavailable: {e}")
        return None
    port = server.getsockname()[1]
    try:
        with open(_info_path(), "w", encoding="utf-8") as f:
            json.dump({"port": port, "token": token, "pid": os.getpid()}, f)
    except OSError:
        pass

    def loop() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(3)
                    raw = b""
                    while not raw.endswith(b"\n") and len(raw) < 65536:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        raw += chunk
                    msg = json.loads(raw.decode("utf-8") or "{}")
                    if msg.get("token") != token:
                        continue
                    docs = [d for d in msg.get("open", []) if isinstance(d, str)]
                    conn.sendall(b"OK\n")
                    on_open(docs)
                except (OSError, ValueError) as e:
                    logger.debug(f"Single-instance message ignored: {e}")

    threading.Thread(target=loop, name="rocktranslate-instance", daemon=True).start()
    return port
