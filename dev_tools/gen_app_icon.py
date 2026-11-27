"""
Rebuilds the application icon with a larger glyph.

The source artwork (dev_tools/assets/rocktranslate_icon_source.png) is a rounded tile
that fills ~74 % of the canvas, with the "RT" letters using only ~60 % of it:
at 16-48 px (taskbar, desktop, title bar) the letters looked tiny. This crops
around the letters (inside the dark tile), so the tile now fills the canvas and
the letters cover about twice the area, then writes the PNG and a
multi-resolution ICO (16-256 px).

    python dev_tools/gen_app_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "src" / "rocktranslate" / "assets"
SOURCE = Path(__file__).resolve().parent / "assets" / "rocktranslate_icon_source.png"
OUT_PNG = ASSETS / "rocktranslate_icon.png"
OUT_ICO = ASSETS / "rocktranslate_icon.ico"

# Square crop of the 1024 px source centred on the letters, kept inside the tile.
CROP_CENTER = (515, 478)
CROP_SIDE = 700
SIZE = 1024
MARGIN = 16          # transparent margin around the tile, in px of the 1024 canvas
RADIUS = 0.2         # corner radius as a fraction of the tile side


def build() -> Image.Image:
    src = Image.open(SOURCE).convert("RGBA")
    if src.size != (1024, 1024):
        src = src.resize((1024, 1024), Image.LANCZOS)
    cx, cy = CROP_CENTER
    half = CROP_SIDE // 2
    tile_side = SIZE - 2 * MARGIN
    tile = src.crop((cx - half, cy - half, cx + half, cy + half)).resize((tile_side, tile_side), Image.LANCZOS)

    # Rounded mask, supersampled for smooth edges.
    k = 4
    mask = Image.new("L", (tile_side * k, tile_side * k), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile_side * k - 1, tile_side * k - 1),
                                           radius=int(tile_side * k * RADIUS), fill=255)
    mask = mask.resize((tile_side, tile_side), Image.LANCZOS)

    # Thin light rim, like the original tile edge.
    rim = Image.new("RGBA", (tile_side, tile_side), (0, 0, 0, 0))
    w = max(3, tile_side // 170)
    ImageDraw.Draw(rim).rounded_rectangle((w // 2, w // 2, tile_side - 1 - w // 2, tile_side - 1 - w // 2),
                                          radius=int(tile_side * RADIUS) - w // 2,
                                          outline=(120, 150, 190, 150), width=w)
    tile.alpha_composite(rim.filter(ImageFilter.GaussianBlur(0.6)))
    tile.putalpha(mask)

    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.alpha_composite(tile, (MARGIN, MARGIN))
    return out


def main() -> None:
    icon = build()
    icon.save(OUT_PNG, optimize=True)
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.save(OUT_ICO, sizes=sizes)
    print(f"wrote {OUT_PNG.name} and {OUT_ICO.name} ({len(sizes)} sizes)")


if __name__ == "__main__":
    main()
