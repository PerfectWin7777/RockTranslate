"""
RockTranslate — Subprocess helpers
Path: src/rocktranslate/core/proc.py

Killing a browser or pdf2htmlEX must never hang or crash the caller, and must
not leave orphan child processes behind (Chromium spawns many on Windows).

License: MIT License
"""

import subprocess
import sys
from typing import List, Optional, Tuple


def kill_tree(proc: "subprocess.Popen") -> None:
    """Kills a process and its children; never raises."""
    try:
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def run_with_timeout(cmd: List[str], timeout: float) -> Tuple[Optional[int], bytes, bytes]:
    """Runs a command; on timeout kills the whole tree. Returns (returncode|None, stdout, stderr)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out, err = b"", b""
        return None, out or b"", err or b""
