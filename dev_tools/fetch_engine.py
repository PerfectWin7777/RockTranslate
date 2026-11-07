"""
RockTranslate — Fetch the Windows pdf2htmlEX engine into the source tree
Path: dev_tools/fetch_engine.py

Downloads the native Windows x64 pdf2htmlEX build published by this
repository (engine release), verifies its SHA-256 and extracts it to
src/rocktranslate/assets/pdf2htmlEX/ — the same layout the installer ships:

    src/rocktranslate/assets/pdf2htmlEX/bin/pdf2htmlEX.exe

That folder is git-ignored. Usage (from the repository root):

    python dev_tools/fetch_engine.py           # skip if already present
    python dev_tools/fetch_engine.py --force   # replace the existing engine

License: MIT License
"""

import argparse
import hashlib
import io
import os
import re
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONSTANTS = os.path.join(ROOT, "src", "rocktranslate", "core", "constants.py")
TARGET = os.path.join(ROOT, "src", "rocktranslate", "assets", "pdf2htmlEX")


def engine_url() -> str:
    """Download URL from core/constants.py (single source of truth)."""
    text = open(CONSTANTS, encoding="utf-8").read()
    version = re.search(r'PDF2HTMLEX_WINDOWS_VERSION: Final\[str\] = "([^"]+)"', text).group(1)
    return (f"https://github.com/PerfectWin7777/RockTranslate/releases/download/"
            f"engine-pdf2htmlex-{version}/pdf2htmlEX-{version}.zip")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the Windows pdf2htmlEX engine into assets/.")
    parser.add_argument("--force", action="store_true", help="replace an existing engine")
    args = parser.parse_args()

    exe = os.path.join(TARGET, "bin", "pdf2htmlEX.exe")
    if os.path.isfile(exe) and not args.force:
        print(f"Engine already present: {exe} (use --force to replace it)")
        return 0

    url = engine_url()
    print(f"Downloading {url}")
    data = urllib.request.urlopen(url, timeout=120).read()
    expected = urllib.request.urlopen(url + ".sha256", timeout=60).read().decode().split()[0]
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        print(f"Checksum mismatch: expected {expected}, got {actual}")
        return 1

    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(TARGET)
    print(f"Engine ready: {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
