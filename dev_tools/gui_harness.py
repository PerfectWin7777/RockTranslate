"""
RockTranslate — Browser harness for the desktop UI (no native window).

Serves the real UI with the real Python API, but replaces pywebview by a small
HTTP bridge, so the whole app can be driven from Chromium/Playwright:

    python dev_tools/gui_harness.py            # prints the URL, Ctrl+C to stop

In the page, `window.pywebview.api.<method>(...)` becomes a POST to /call and
every `window.evaluate_js(code)` of the backend is queued and executed by the
page (polling /events). File dialogs return the path given in RT_HARNESS_SAVE.

Author: RockTranslate Contributors
License: MIT License
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from rocktranslate.core.config_manager import config_db  # noqa: E402
from rocktranslate.core.constants import DEFAULT_ASSETS_DIR  # noqa: E402
from rocktranslate.core.local_server import (SESSION_TOKEN, allow_directory, find_free_port,  # noqa: E402
                                             start_local_server)
from rocktranslate.core.web_api import RockTranslateAPI  # noqa: E402

BRIDGE_JS = r"""
(() => {
  if (window.top !== window) return;   // the app's own frames never run the bridge
  const RPC = '__RPC__';
  const call = (name) => async (...args) => {
    const r = await fetch(RPC + '/call', { method: 'POST', body: JSON.stringify({ name, args }) });
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    return data.result;
  };
  window.pywebview = { api: new Proxy({}, { get: (t, name) => (typeof name === 'string' && name !== 'then' ? call(name) : undefined),
                                            has: () => true }) };
  setInterval(async () => {
    try {
      const r = await fetch(RPC + '/events'); const codes = await r.json();
      codes.forEach((c) => { try { (0, eval)(c); } catch (e) { console.error('[bridge eval]', e, c.slice(0, 120)); } });
    } catch (e) { }
  }, 80);
  setTimeout(() => window.dispatchEvent(new Event('pywebviewready')), 50);
})();
"""


class HarnessWindow:
    """Stands in for webview.Window: queues evaluate_js, answers file dialogs."""

    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()

    def evaluate_js(self, code):
        with self.lock:
            self.queue.append(code)

    def drain(self):
        with self.lock:
            out, self.queue = self.queue, []
        return out

    def create_file_dialog(self, *args, **kwargs):
        target = os.environ.get("RT_HARNESS_SAVE") or os.environ.get("RT_HARNESS_OPEN")
        return [target] if target else None


def start(api_port=None, ui_port=None):
    """Starts the UI server and the bridge. Returns (ui_url, bridge_js, api)."""
    ui_port = ui_port or find_free_port()
    allow_directory(str(config_db.get_cache_dir()))
    ready = threading.Event()
    threading.Thread(target=start_local_server, args=(ui_port, DEFAULT_ASSETS_DIR, ready), daemon=True).start()
    ready.wait(5)

    api = RockTranslateAPI()
    window = HarnessWindow()
    api._window = window
    api._ui_ready = True

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, payload):
            body = json.dumps(payload, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

        def do_GET(self):
            self._send(window.drain() if self.path.startswith("/events") else {})

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            name = data.get("name", "")
            try:
                if name.startswith("_") or not hasattr(api, name):
                    raise AttributeError(name)
                self._send({"result": getattr(api, name)(*data.get("args", []))})
            except Exception as e:
                self._send({"error": f"{type(e).__name__}: {e}"})

    api_port = api_port or find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", api_port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{ui_port}/ui/index.html?t={SESSION_TOKEN}"
    return url, BRIDGE_JS.replace("__RPC__", f"http://127.0.0.1:{api_port}"), api


if __name__ == "__main__":
    url, js, _ = start(int(os.environ.get("RT_HARNESS_API_PORT", "0")) or None,
                       int(os.environ.get("RT_HARNESS_UI_PORT", "0")) or None)
    with open(os.environ.get("RT_HARNESS_INFO", "harness.json"), "w") as f:
        json.dump({"url": url, "bridge": js}, f)
    print(url, flush=True)
    while True:
        time.sleep(3600)
