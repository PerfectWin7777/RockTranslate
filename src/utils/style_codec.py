# src/utils/style_codec.py


import re

def decode_styled_text(text: str) -> str:
    """Convertit les balises custom en HTML natif Chromium."""
    # <color_HEX> → <span style="color:#HEX;">
    text = re.sub(
        r'<color_([0-9a-fA-F]{6})>(.*?)</color_\1>',
        r'<span style="color:#\1;">\2</span>',
        text, flags=re.DOTALL
    )
    # <fs_N> → <span style="font-size:Npx;">
    text = re.sub(
        r'<fs_(\d+)>(.*?)</fs_\1>',
        r'<span style="font-size:\1px;">\2</span>',
        text, flags=re.DOTALL
    )
    # <b>, <i>, <sup> sont déjà du HTML natif — Chromium les gère directement
    return text