"""
RockTranslate — Minimal Chrome DevTools Protocol client (stdlib only)
Path: src/rocktranslate/core/cdp.py

Desktop Chrome / Edge never finish the `--dump-dom` command-line shortcut in
their (new) headless mode, but they work perfectly when driven through the
DevTools protocol — the way Playwright or Puppeteer drive them. This module
starts the browser with --remote-debugging-port=0, opens one page and
evaluates a script in it. No third-party dependency (a tiny WebSocket client).

License: MIT License
"""

import base64
import json
import os
import re
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from typing import Any, Callable, Optional


class _WebSocket:
    """Just enough RFC 6455 for CDP: text frames, client masking, no TLS."""

    def __init__(self, url: str, timeout: float) -> None:
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)", url)
        if not m:
            raise ValueError(f"Unsupported WebSocket URL: {url}")
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake failed")
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise ConnectionError("WebSocket upgrade refused")
        self._buf = response.split(b"\r\n\r\n", 1)[1]

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("WebSocket closed")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def send(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def recv(self) -> str:
        message = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data = self._read(n)
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise ConnectionError("WebSocket closed by the browser")
            if opcode in (0x0, 0x1, 0x2):
                message += data
                if b0 & 0x80:
                    return message.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _launch(browser: str, profile: str) -> "subprocess.Popen":
    from .proc import NO_WINDOW
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--disable-extensions", "--disable-background-networking", "--disable-sync",
           "--disable-component-update", "--remote-debugging-port=0", "--remote-allow-origins=*",
           f"--user-data-dir={profile}", "--window-size=1600,1200", "about:blank"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **NO_WINDOW)


class _Session:
    """One headless browser + one page, driven over the DevTools protocol."""

    def __init__(self, browser: str, url: str, timeout: float) -> None:
        self.deadline = time.monotonic() + timeout
        self.profile = tempfile.mkdtemp(prefix="rocktranslate-cdp-")
        self.proc = _launch(browser, self.profile)
        self.ws: Optional[_WebSocket] = None
        self._id = 0
        port_file = os.path.join(self.profile, "DevToolsActivePort")
        port = None
        while time.monotonic() < self.deadline and self.proc.poll() is None:
            if os.path.exists(port_file):
                try:
                    with open(port_file, encoding="utf-8") as f:
                        first = f.readline().strip()
                except OSError:
                    first = ""      # Windows: still locked by the browser writing it
                if first.isdigit():
                    port = int(first)
                    break
            time.sleep(0.1)
        if not port:
            raise TimeoutError("browser did not expose a DevTools port")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?{urllib.request.quote(url, safe=':/')}", method="PUT")
        # Never through a system proxy (Windows registry proxies catch 127.0.0.1)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        target = json.loads(opener.open(req, timeout=10).read().decode())
        self.ws = _WebSocket(target["webSocketDebuggerUrl"], timeout=max(1.0, self.remaining()))

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def call(self, method: str, params: Optional[dict] = None) -> dict:
        self._id += 1
        call_id = self._id
        self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while self.remaining() > 0:
            self.ws.sock.settimeout(max(0.5, self.remaining()))
            msg = json.loads(self.ws.recv())
            if msg.get("id") == call_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "CDP error"))
                return msg.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def evaluate(self, expression: str) -> Any:
        """Evaluates until the page (not the initial blank document) answers."""
        while self.remaining() > 0:
            result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                    "returnByValue": True})
            value = result.get("result", {}).get("value")
            if value is not None and "exceptionDetails" not in result:
                return value
            time.sleep(0.2)
        return None

    def close(self) -> None:
        import shutil
        from .proc import kill_tree
        if self.ws is not None:
            self.ws.close()
        kill_tree(self.proc)
        shutil.rmtree(self.profile, ignore_errors=True)


def evaluate_in_page(browser: str, url: str, expression: str, timeout: float) -> Optional[Any]:
    """
    Opens `url` in a fresh headless instance of `browser` and returns the
    value of `expression` (which may return a Promise). None on any failure;
    the browser process tree is always killed.
    """
    session = None
    try:
        session = _Session(browser, url, timeout)
        return session.evaluate(expression)
    except Exception as e:
        from loguru import logger
        logger.warning(f"DevTools evaluation failed with {os.path.basename(browser)}: {type(e).__name__}: {e}")
        return None
    finally:
        if session is not None:
            session.close()


_READY_FOR_PRINT = r"""
(async () => {
  if (!location.href.startsWith('file:')) return null;
  if (document.readyState !== 'complete') await new Promise(r => window.addEventListener('load', r, {once: true}));
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  await new Promise(r => setTimeout(r, 600));   // paragraph re-layout after fonts
  return true;
})()
"""


# Export page published by renderer.apply_translations_offline: its progress
# while the translations are applied page by page, then whether it is ready.
_EXPORT_STATE = r"""
(() => {
  if (!location.href.startsWith('file:')) return null;
  const p = window.__rtExportProgress;
  if (!p) return document.readyState === 'complete' ? 'plain' : null;
  return JSON.stringify({ stage: p.stage, done: p.done, total: p.total, ready: window.__rtExportReady === true });
})()
"""

ExportProgress = Callable[[str, int, int], None]


def _wait_until_printable(session: "_Session", progress: Optional[ExportProgress]) -> bool:
    """
    Waits for an export page to be ready, reporting its progress
    (stage, done, total): 'pages' while translations are applied page by page,
    'fonts' while fonts load. Pages without the export hook use the plain
    readiness check.
    """
    last = None
    while session.remaining() > 0:
        state = session.evaluate(_EXPORT_STATE)
        if state is None:
            return False
        if state == "plain":
            return session.evaluate(_READY_FOR_PRINT) is True
        info = json.loads(state)
        current = (info.get("stage"), info.get("done", 0), info.get("total", 0))
        if progress and current != last:
            try:
                progress(*current)
            except Exception:
                pass
            last = current
        if info.get("ready"):
            return True
        time.sleep(0.25)
    return False


def print_to_pdf(browser: str, html_path: str, output_pdf: str, timeout: float,
                 progress: Optional[ExportProgress] = None) -> bool:
    """
    Vector PDF of an HTML file through Page.printToPDF (CSS @page sizes).
    progress(stage, done, total) is called with stage 'pages' (translations
    applied page by page), 'fonts', then 'print' while Chrome writes the PDF.
    """
    import base64 as b64
    url = "file:///" + os.path.abspath(html_path).replace(os.sep, "/").lstrip("/")
    session = None
    try:
        t0 = time.monotonic()
        session = _Session(browser, url, timeout)
        t1 = time.monotonic()
        ready = _wait_until_printable(session, progress)
        t2 = time.monotonic()
        if ready is not True:
            from loguru import logger
            logger.warning(f"DevTools: the page never became ready to print ({os.path.basename(browser)}).")
            return False
        if progress:
            try:
                progress("print", 0, 0)
            except Exception:
                pass
        result = session.call("Page.printToPDF", {"printBackground": True, "preferCSSPageSize": True,
                                                  "displayHeaderFooter": False, "marginTop": 0,
                                                  "marginBottom": 0, "marginLeft": 0, "marginRight": 0})
        data = result.get("data")
        if not data:
            return False
        t3 = time.monotonic()
        tmp = output_pdf + ".part"
        with open(tmp, "wb") as f:
            f.write(b64.b64decode(data))
        os.replace(tmp, output_pdf)
        from loguru import logger
        logger.info(f"Export timing: browser start {t1 - t0:.1f}s | page load + fonts {t2 - t1:.1f}s | "
                    f"print {t3 - t2:.1f}s | PDF {len(data) * 3 / 4 / 1e6:.1f} MB")
        return os.path.getsize(output_pdf) > 0
    except Exception as e:
        from loguru import logger
        logger.warning(f"DevTools printing failed with {os.path.basename(browser)}: {type(e).__name__}: {e}")
        return False
    finally:
        if session is not None:
            session.close()
