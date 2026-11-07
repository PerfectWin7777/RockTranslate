"""
RockTranslate — Cache diagnostic
Path: dev_tools/diag_cache.py

Prints, for every prepared document in the cache: the raw pdf2htmlEX text
lines count and the number of translatable segments of its workspace.

    python dev_tools/diag_cache.py

License: MIT License
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rocktranslate.core.config_manager import config_db  # noqa: E402

for folder in sorted(glob.glob(os.path.join(str(config_db.get_cache_dir()), "*"))):
    if not os.path.isdir(folder):
        continue
    raws = glob.glob(os.path.join(folder, "*_raw.html"))
    lines = 0
    for raw in raws:
        with open(raw, encoding="utf-8", errors="ignore") as f:
            lines += f.read().count('class="t ')
    segments = "?"
    for meta in glob.glob(os.path.join(folder, "*.json")):
        try:
            with open(meta, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "original_texts" in data:
                segments = len(data["original_texts"])
        except (OSError, ValueError):
            pass
    name = os.path.basename(raws[0]) if raws else "(no raw html)"
    print(f"{os.path.basename(folder)[:12]}  {name:60s} text lines={lines:6d}  segments={segments}")
