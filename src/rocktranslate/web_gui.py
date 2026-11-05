"""
RockTranslate — Main Web Application Launcher (Absolute File Server Version)
Path: src/rocktranslate/web_gui.py

Initializes the secure environment, configures file logger rotations,
spins up the local same-origin HTTP assets server with absolute file routing,
subscribes to secure Python-side DOM Drag & Drop events, and launches the primary
pywebview Chromium viewport window.

Author: RockTranslate Contributors
License: MIT License
Version: 1.1.0
"""

import os
import sys
import datetime
import threading
from loguru import logger

# Safe dynamic import check to prevent crash if pywebview was not installed via extras
try:
    import webview
    from webview.dom import DOMEventHandler
except ImportError:
    print(
        "\n❌ Error: The 'pywebview' library is required to launch the Graphical User Interface (GUI).\n"
        "Please install the package with GUI support enabled using your terminal:\n"
        "   pip install \"rocktranslate[gui]\"\n"
    )
    sys.exit(1)


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
from rocktranslate.core.config_manager import config_db
from rocktranslate.core.local_server import (
    SESSION_TOKEN, allow_directory, find_free_port, start_local_server
)


def main() -> None:
    # Accurately record the Splash Screen startup time
    start_time = datetime.datetime.now()

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
    # Only the workspace cache (and documents explicitly opened) can be streamed
    allow_directory(str(config_db.get_cache_dir()))
    server_ready = threading.Event()
    server_thread = threading.Thread(
        target=start_local_server, 
        args=(port, DEFAULT_ASSETS_DIR, server_ready), 
        daemon=True
    )
    server_thread.start()
    server_ready.wait(timeout=5)

    api = RockTranslateAPI()

    # Robust coordinate calculation for perfect Splash Screen centering
    splash_width, splash_height = 850, 520
    splash_x, splash_y = None, None
    try:
        screens = webview.screens
        if screens:
            primary = screens[0]
            splash_x = (primary.width - splash_width) // 2
            splash_y = (primary.height - splash_height) // 2
    except Exception:
        pass

    # 1. Create a lightweight, frameless splash screen window
    splash = webview.create_window(
        title="RockTranslate Loading",
        url=f"http://127.0.0.1:{port}/ui/splash.html",
        width=splash_width,
        height=splash_height,
        x=splash_x,
        y=splash_y,
        frameless=True,
        easy_drag=True,
        background_color='#f7fafc'
    )

    # 2. Create the main workspace window (hidden on load)
    window = webview.create_window(
        title="RockTranslate",
        url=f"http://127.0.0.1:{port}/ui/index.html?t={SESSION_TOKEN}",
        width=1440,
        height=900,
        min_size=(1024, 768),
        js_api=api,
        confirm_close=True, # Option C : Native anti-crash closing prompt
        hidden=True         # Keep invisible until index.html is fully compiled
    )

    api._window = window

    # Option C : Silently execute cleanup operations upon complete app termination
    def on_window_closed() -> None:
        try:
            logger.info("Window closed natively. Initiating silent workspace cache cleanup...")
            api.close_document()
        except Exception as e:
            logger.error(f"Error during post-close cache cleanup: {e}")

    window.events.closed += on_window_closed

    # 3. Double-layer transition: Close splash and reveal main window upon completion
    def on_window_loaded() -> None:
        # Calculate elapsed time since program startup
        elapsed = (datetime.datetime.now() - start_time).total_seconds()
        # Keep the splash visible just long enough to avoid a flash (min 0.1s)
        remaining_delay = max(0.1, 1.5 - elapsed)
        
        def reveal_main_window():
            try:
                splash.destroy()
                window.show()
                window.maximize()
                logger.info("Workspace viewport successfully rendered. Splash screen closed.")
            except Exception as e:
                logger.error(f"Error transferring focus from splash screen: {e}")

        # Timer non bloquant s'exécutant sur le thread d'interface
        threading.Timer(remaining_delay, reveal_main_window).start()

    window.events.loaded += on_window_loaded

    # Callback to register native Python-side event handlers on Webview DOM
    def bind_native_events(window):
        
        
        def on_drag(e):
            pass # No-op, simply used to prevent default browser page opening behaviors
            
        def on_drop(e):
            files = e.get('dataTransfer', {}).get('files', [])
            if files and len(files) > 0:
                file_path = files[0].get('pywebviewFullPath')
                if file_path and file_path.lower().endswith('.pdf'):
                    # Start extraction natively with the verified absolute system path
                    api.extract_pdf(file_path)

        # Intercept HTML5 drag and drop events directly in Python to bypass JS security sandboxes
        window.dom.document.events.dragenter += DOMEventHandler(on_drag, prevent_default=True, stop_propagation=True)
        window.dom.document.events.dragover += DOMEventHandler(on_drag, prevent_default=True, stop_propagation=True, debounce=500)
        window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True, stop_propagation=True)

    
    try:
        logger.info("Launching pywebview main loop...")
        # Start application on splash, with the main window context passed as master loop
        webview.start(bind_native_events, window, 
                    #   debug=False
                      debug=not hasattr(sys, "_MEIPASS")
                      )
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