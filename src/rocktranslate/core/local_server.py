"""
RockTranslate — Hardened local assets & document server
Path: src/rocktranslate/core/local_server.py

Serves the static UI assets and streams the active documents to the webview
over a same-origin loopback HTTP server.

Security model (the server listens on 127.0.0.1, which any web page opened
in the user's regular browser can also reach):

1. ``/local-file`` requires a random per-session token (``t`` query param).
2. Only explicitly registered files, or files inside registered directories
   (the workspace cache), can be streamed. Everything else is a 403.
3. The ``Host`` header must be the loopback address (blocks DNS rebinding).
4. No wildcard CORS header is ever emitted.

License: MIT License
"""

import http.server
import os
import secrets
import socket
import socketserver
import threading
from typing import Optional, Set
from urllib.parse import parse_qs, unquote, urlparse

from loguru import logger

SESSION_TOKEN: str = secrets.token_urlsafe(24)

_allowed_files: Set[str] = set()
_allowed_dirs: Set[str] = set()
_registry_lock = threading.Lock()

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def allow_file(path: str) -> None:
    """Registers a single file (e.g. the opened PDF) as streamable."""
    if path:
        with _registry_lock:
            _allowed_files.add(_norm(path))


def allow_directory(path: str) -> None:
    """Registers a directory tree (e.g. the workspace cache) as streamable."""
    if path:
        with _registry_lock:
            _allowed_dirs.add(_norm(path))


def is_path_allowed(path: str) -> bool:
    """True when the path is a registered file or lives in a registered directory."""
    target = _norm(path)
    with _registry_lock:
        if target in _allowed_files:
            return True
        for root in _allowed_dirs:
            try:
                if os.path.commonpath([target, root]) == root:
                    return True
            except ValueError:  # different drives on Windows
                continue
    return False


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_handler(directory: str, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class SecureHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass  # keep the console quiet; errors are logged explicitly

        def _host_ok(self) -> bool:
            return (self.headers.get("Host") or "") in allowed_hosts

        def do_GET(self) -> None:
            if not self._host_ok():
                self.send_error(403, "Forbidden host")
                return
            if self.path.startswith("/local-file"):
                self._serve_local_file()
                return
            if self.path.startswith("/doc/"):
                self._serve_document_file()
                return
            super().do_GET()

        def do_HEAD(self) -> None:
            if not self._host_ok() or self.path.startswith("/local-file"):
                self.send_error(403, "Forbidden")
                return
            super().do_HEAD()

        def _serve_local_file(self) -> None:
            params = parse_qs(urlparse(self.path).query)
            token = (params.get("t") or [""])[0]
            if not secrets.compare_digest(token, SESSION_TOKEN):
                self.send_error(403, "Invalid session token")
                return
            raw_path = (params.get("path") or [""])[0]
            self._send_file(unquote(raw_path))

        def _serve_document_file(self) -> None:
            """
            /doc/<token>/<url-encoded folder>/<file>: a document page and its
            sibling resources (page images written by pdf2htmlEX) share one URL
            folder, so the HTML's relative references resolve naturally.
            """
            parts = urlparse(self.path).path.split("/")
            # ['', 'doc', token, folder, file]
            if len(parts) != 5:
                self.send_error(404, "Not found")
                return
            token, folder, name = parts[2], unquote(parts[3]), unquote(parts[4])
            if not secrets.compare_digest(token, SESSION_TOKEN):
                self.send_error(403, "Invalid session token")
                return
            if not name or name in (".", "..") or "/" in name or "\\" in name:
                self.send_error(403, "Invalid file name")
                return
            self._send_file(os.path.join(folder, name))

        def _send_file(self, file_path: str) -> None:
            if not file_path or not os.path.isfile(file_path):
                self.send_error(404, "File not found")
                return
            if not is_path_allowed(file_path):
                logger.warning(f"Blocked local-file request outside the allowlist: {file_path}")
                self.send_error(403, "Path not allowed")
                return
            ext = os.path.splitext(file_path)[1].lower()
            try:
                with open(file_path, "rb") as f:
                    content = f.read()
            except OSError as e:
                self.send_error(500, f"Error reading file: {e}")
                return
            self.send_response(200)
            self.send_header("Content-Type", _CONTENT_TYPES.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("X-Content-Type-Options", "nosniff")
            super().end_headers()

    return SecureHandler


class _ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        """A viewer that cancels a download (navigation, reload) is not an error."""
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        logger.warning(f"Local server error for {client_address}: {exc!r}")


def start_local_server(port: int, directory: str, ready: Optional[threading.Event] = None) -> None:
    """Runs the hardened server forever (call from a daemon thread)."""
    with _ThreadingServer(("127.0.0.1", port), _make_handler(directory, port)) as httpd:
        logger.info(f"Local assets server running at: http://127.0.0.1:{port}")
        if ready is not None:
            ready.set()
        httpd.serve_forever()
