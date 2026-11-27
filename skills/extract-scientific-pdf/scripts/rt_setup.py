#!/usr/bin/env python3
"""
RockTranslate setup for agent skills (Windows, macOS, Linux).

Finds a working `rocktranslate` command, or installs it in a private virtual
environment (no change to the system Python, works where `pip install --user`
is blocked), then runs `rocktranslate doctor`.

Prints, on its last line:  RT=<absolute path of the rocktranslate command>
Exit code 0 when the engine is ready, 1 otherwise (the doctor report says why).

Usage:  python3 rt_setup.py            (python rt_setup.py on Windows)
        python3 rt_setup.py --upgrade  (update to the latest release)
"""

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

MIN_VERSION = (2, 0, 8)
PACKAGE = "rocktranslate>=2.0.8"


def _data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "rocktranslate-skill"


def _venv_bin(env: Path, name: str) -> Path:
    return env / ("Scripts" if os.name == "nt" else "bin") / (name + (".exe" if os.name == "nt" else ""))


def _version(cmd: str):
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=120).stdout
        parts = out.strip().split()[-1].split(".")
        return tuple(int(p) for p in parts[:3])
    except Exception:
        return None


def main() -> int:
    upgrade = "--upgrade" in sys.argv
    if sys.version_info < (3, 9):
        print("Python 3.9 or newer is required (found %s)." % sys.version.split()[0])
        return 1

    env = _data_dir() / "venv"
    private = _venv_bin(env, "rocktranslate")
    candidates = [str(private)] if private.exists() else []
    on_path = shutil.which("rocktranslate")
    if on_path:
        candidates.append(on_path)

    command = next((c for c in candidates if (_version(c) or (0,)) >= MIN_VERSION), None)
    if command is None or upgrade:
        print(f"Installing {PACKAGE} in {env} ...", flush=True)
        if not env.exists():
            venv.EnvBuilder(with_pip=True).create(env)
        pip = [str(_venv_bin(env, "python")), "-m", "pip", "install", "--quiet", "--upgrade"]
        subprocess.run(pip + ["pip"], check=False)
        result = subprocess.run(pip + [PACKAGE])
        if result.returncode != 0:
            print("Installation failed (see the pip output above).")
            return 1
        command = str(private)

    if sys.platform == "darwin" and not shutil.which("pdf2htmlEX"):
        print("macOS: the pdf2htmlEX engine comes from Homebrew. Run:  brew install pdf2htmlex")

    doctor = subprocess.run([command, "doctor"], capture_output=True, text=True, timeout=900)
    print(doctor.stdout.strip() or doctor.stderr.strip())
    print(f"RT={command}")
    return 0 if "Result: ready" in doctor.stdout else 1


if __name__ == "__main__":
    sys.exit(main())
