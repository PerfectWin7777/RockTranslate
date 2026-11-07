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
from typing import Any, Optional


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


def evaluate_in_page(browser: str, url: str, expression: str, timeout: float) -> Optional[Any]:
    """
    Opens `url` in a fresh headless instance of `browser` and returns the
    value of `expression` (which may return a Promise). None on any failure;
    the browser process tree is always killed.
    """
    from .proc import kill_tree
    deadline = time.monotonic() + timeout
    import shutil
    profile = tempfile.mkdtemp(prefix="rocktranslate-cdp-")
    try:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--disable-extensions", "--disable-background-networking", "--disable-sync",
               "--disable-component-update", "--remote-debugging-port=0", "--remote-allow-origins=*",
               f"--user-data-dir={profile}", "--window-size=1600,1200", "about:blank"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws = None
        try:
            # The browser writes its debugging port to <profile>/DevToolsActivePort
            port_file = os.path.join(profile, "DevToolsActivePort")
            port = None
            while time.monotonic() < deadline and proc.poll() is None:
                if os.path.exists(port_file):
                    with open(port_file, encoding="utf-8") as f:
                        first = f.readline().strip()
                    if first.isdigit():
                        port = int(first)
                        break
                time.sleep(0.1)
            if not port:
                return None
            req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{urllib.request.quote(url, safe=':/')}",
                                         method="PUT")
            target = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
            ws = _WebSocket(target["webSocketDebuggerUrl"], timeout=max(1.0, deadline - time.monotonic()))
            # The first evaluation may hit the initial blank document while
            # the file is still being navigated to: retried until it returns.
            call_id = 0
            while time.monotonic() < deadline:
                call_id += 1
                ws.send(json.dumps({"id": call_id, "method": "Runtime.evaluate", "params": {
                    "expression": expression, "awaitPromise": True, "returnByValue": True}}))
                while time.monotonic() < deadline:
                    ws.sock.settimeout(max(0.5, deadline - time.monotonic()))
                    msg = json.loads(ws.recv())
                    if msg.get("id") == call_id:
                        break
                else:
                    return None
                value = msg.get("result", {}).get("result", {}).get("value")
                if value is not None and "exceptionDetails" not in msg.get("result", {}):
                    return value
                time.sleep(0.2)
            return None
        except Exception:
            return None
        finally:
            if ws is not None:
                ws.close()
            kill_tree(proc)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
