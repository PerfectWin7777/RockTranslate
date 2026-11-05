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


def _linux_tree_cpu(root_pid: int) -> Optional[float]:
    """User+system CPU seconds of a process and all its descendants (Linux /proc)."""
    import os
    try:
        tick = float(os.sysconf("SC_CLK_TCK"))
    except (ValueError, OSError, AttributeError):
        tick = 100.0
    stats = {}
    children: dict = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as f:
                raw = f.read().decode("ascii", "replace")
        except OSError:
            continue
        # comm may contain spaces: fields start after the closing parenthesis
        fields = raw[raw.rfind(")") + 2:].split()
        try:
            ppid, utime, stime = int(fields[1]), int(fields[11]), int(fields[12])
        except (IndexError, ValueError):
            continue
        stats[int(entry)] = (utime + stime) / tick
        children.setdefault(ppid, []).append(int(entry))
    if root_pid not in stats:
        return None
    total, stack = 0.0, [root_pid]
    while stack:
        pid = stack.pop()
        total += stats.get(pid, 0.0)
        stack.extend(children.get(pid, []))
    return total


def _windows_cpu(pid: int) -> Optional[float]:
    """User+kernel CPU seconds of a process (Windows GetProcessTimes)."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        creation, exit_, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_),
                                        ctypes.byref(kernel), ctypes.byref(user)):
            return None
        to_s = lambda ft: ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7
        return to_s(kernel) + to_s(user)
    finally:
        kernel32.CloseHandle(handle)


def process_cpu_seconds(pid: int) -> Optional[float]:
    """
    CPU time consumed so far by a process (and, on Linux, its descendants).
    A process that is silent but still burning CPU is working, not hung.
    Returns None when it cannot be measured on this platform.
    """
    try:
        if sys.platform == "win32":
            return _windows_cpu(pid)
        if sys.platform.startswith("linux"):
            return _linux_tree_cpu(pid)
    except Exception:
        return None
    return None
