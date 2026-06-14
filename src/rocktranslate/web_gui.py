"""
RockTranslate — Main Web Application Launcher (Absolute File Server Version)
Path: src/rocktranslate/web_gui.py

Initializes the secure environment, configures file logger rotations,
spins up the local same-origin HTTP assets server with absolute file routing,
and launches the primary pywebview Chromium viewport window.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.1
"""

import os
import sys
import datetime
import socket
import threading
import http.server
import socketserver
import webview
from urllib.parse import urlparse, parse_qs, unquote
from loguru import logger

# ── TIKTOKEN PYINSTALLER RUNTIME HOOK ──
if hasattr(sys, "_MEIPASS"):
    try:
        import tiktoken.registry
        import tiktoken_ext.openai_public
        tiktoken.registry.ENCODING_CONSTRUCTORS = dict(
            tiktoken_ext.openai_public.ENCODING_CONSTRUCTORS
        )
    except ImportError:
        pass
# ───────────────────────────────────────

# ── DYNAMIC SYSTEM PATH RESOLUTION ──
current_dir = os.path.dirname(os.path.abspath(__file__))  # src/rocktranslate
src_parent_dir = os.path.dirname(current_dir)             # src

if src_parent_dir not in sys.path:
    sys.path.insert(0, src_parent_dir)
# ────────────────────────────────────

from rocktranslate.core.constants import DEFAULT_ASSETS_DIR
from rocktranslate.core.web_api import RockTranslateAPI


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def start_local_server(port: int, directory: str):
    """Launches a simple HTTP server locked to assets but supporting absolute files streaming."""
    class SafeHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def do_GET(self):
            # ── INTERCEPT ABSOLUTE FILES QUERIES ──
            # Allows the Web UI to stream any local PDF/HTML safely over same-origin
            if self.path.startswith("/local-file"):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                
                if "path" in params:
                    file_path = unquote(params["path"][0])
                    
                    if os.path.exists(file_path):
                        self.send_response(200)
                        
                        # Set proper content-types to trigger browser encoders
                        if file_path.lower().endswith(".pdf"):
                            self.send_header("Content-Type", "application/pdf")
                        elif file_path.lower().endswith(".html") or file_path.lower().endswith(".htm"):
                            self.send_header("Content-Type", "text/html; charset=utf-8")
                        else:
                            self.send_header("Content-Type", "application/octet-stream")
                            
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                        
                        # Read and stream the file bytes
                        try:
                            with open(file_path, "rb") as f:
                                content = f.read()
                            self.send_header("Content-Length", str(len(content)))
                            self.end_headers()
                            self.wfile.write(content)
                            return
                        except Exception as e:
                            self.send_error(500, f"Error reading file: {e}")
                            return
                
                self.send_error(404, "File path missing or invalid")
                return

            # Default behavior for serving static UI assets
            super().do_GET()

        def end_headers(self):
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            super().end_headers()

    handler = SafeHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        logger.info(f"Local assets server running at: http://localhost:{port}")
        httpd.serve_forever()


def main() -> None:
    try:
        if hasattr(sys, "_MEIPASS"):
            if os.name == "nt":
                app_data_dir = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
                log_dir = os.path.join(app_data_dir, "RockTranslate", "logs")
            else:
                log_dir = os.path.expanduser("~/.config/rocktranslate/logs")
        else:
            log_dir = os.path.join(current_dir, "logs")
            
        os.makedirs(log_dir, exist_ok=True)
        logger.add(
            os.path.join(log_dir, "app.log"),
            rotation="10 MB",
            retention="5 days",
            level="INFO",
            encoding="utf-8"
        )
    except Exception as e:
        print(f"Failed to initialize file logger: {e}")

    logger.info("Initializing RockTranslate Web UI lifecycle...")

    port = find_free_port()
    server_thread = threading.Thread(
        target=start_local_server, 
        args=(port, DEFAULT_ASSETS_DIR), 
        daemon=True
    )
    server_thread.start()

    api = RockTranslateAPI()

    window = webview.create_window(
        title="RockTranslate",
        url=f"http://localhost:{port}/ui/index.html",
        width=1440,
        height=900,
        min_size=(1024, 768),
        js_api=api
    )

    api._window = window

    try:
        logger.info("Launching pywebview main loop...")
        webview.start(debug=not hasattr(sys, "_MEIPASS"))
    except Exception as e:
        import traceback
        error_info = traceback.format_exc()
        logger.critical(f"Unhandled critical exception in webview loop: {e}")
        
        crash_file_path = os.path.join(os.path.expanduser("~"), "Desktop", "rocktranslate_crash_report.txt")
        try:
            with open(crash_file_path, "w", encoding="utf-8") as f:
                f.write("=== ROCKTRANSLATE EMERGENCY CRASH REPORT ===\n")
                f.write(f"Date: {datetime.datetime.now()}\n\n")
                f.write(error_info)
        except Exception:
            with open("rocktranslate_crash_report.txt", "w", encoding="utf-8") as f:
                f.write(error_info)
        sys.exit(1)


if __name__ == "__main__":
    main()