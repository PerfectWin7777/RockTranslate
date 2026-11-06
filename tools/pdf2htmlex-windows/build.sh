#!/usr/bin/env bash
# Native 64-bit Windows build of pdf2htmlEX 0.18.8.rc1 (MSYS2 / MINGW64).
#
# Mirrors the official Linux recipe (buildScripts/ in the pdf2htmlEX repo):
# static Poppler 0.89.0 + static FontForge 20200314 + pdf2htmlEX, then packages
# a self-contained folder:
#   pdf2htmlEX-win64/bin/pdf2htmlEX.exe (+ DLLs, data/)
#   pdf2htmlEX-win64/etc/fonts/        (fontconfig configuration)
#   pdf2htmlEX-win64/share/poppler/    (poppler-data: CJK cmaps)
set -euxo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK:-$PWD/build-win}"
OUT="${OUT:-$PWD/pdf2htmlEX-win64}"
JOBS="${JOBS:-4}"
export PDF2HTMLEX_VERSION=0.18.8.rc1
POPPLER=poppler-0.89.0
FONTFORGE=20200314

# Old sources vs a recent GCC: keep pre-C23 semantics, downgrade the errors
# GCC 14+ introduced for legacy C, and add headers newer libstdc++ no longer
# pulls in transitively.
export CFLAGS="-O2 -std=gnu17 -Wno-error=incompatible-pointer-types -Wno-error=implicit-function-declaration -Wno-error=int-conversion"
export CXXFLAGS="-O2 -include cstdint -include cstring -include climits"

mkdir -p "$WORK" && cd "$WORK"

# ── Sources ──
[ -d pdf2htmlEX ] || git clone --depth 1 --branch v$PDF2HTMLEX_VERSION https://github.com/pdf2htmlEX/pdf2htmlEX.git pdf2htmlEX-src
[ -d pdf2htmlEX ] || mv pdf2htmlEX-src/pdf2htmlEX pdf2htmlEX
[ -d poppler ] || { curl -fsSLO https://poppler.freedesktop.org/$POPPLER.tar.xz; tar xf $POPPLER.tar.xz; mv $POPPLER poppler; }
[ -d poppler-data ] || { curl -fsSLO https://poppler.freedesktop.org/poppler-data-0.4.9.tar.gz; tar xf poppler-data-0.4.9.tar.gz; mv poppler-data-0.4.9 poppler-data; }
[ -d fontforge ] || { curl -fsSL -o ff.tar.gz https://github.com/fontforge/fontforge/archive/$FONTFORGE.tar.gz; tar xf ff.tar.gz; mv fontforge-$FONTFORGE fontforge; }

python "$HERE/patch_sources.py" "$WORK"

# ── Poppler (static, same options as the official build) ──
cmake -S poppler -B poppler/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
  -DENABLE_UNSTABLE_API_ABI_HEADERS=OFF -DBUILD_GTK_TESTS=OFF -DBUILD_QT5_TESTS=OFF \
  -DBUILD_CPP_TESTS=OFF -DENABLE_SPLASH=ON -DENABLE_UTILS=OFF -DENABLE_CPP=OFF \
  -DENABLE_GLIB=ON -DENABLE_GOBJECT_INTROSPECTION=OFF -DENABLE_GTK_DOC=OFF \
  -DENABLE_QT5=OFF -DENABLE_LIBOPENJPEG=none -DENABLE_CMS=none \
  -DENABLE_DCTDECODER=libjpeg -DENABLE_LIBCURL=OFF -DENABLE_ZLIB=ON \
  -DENABLE_ZLIB_UNCOMPRESS=OFF -DUSE_FLOAT=OFF -DRUN_GPERF_IF_PRESENT=OFF \
  -DEXTRA_WARN=OFF -DWITH_JPEG=ON -DWITH_PNG=ON -DWITH_TIFF=OFF -DWITH_NSS3=OFF \
  -DWITH_Cairo=ON
cmake --build poppler/build -j "$JOBS"

# ── FontForge (static library only, no GUI / Python) ──
cmake -S fontforge -B fontforge/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
  -DENABLE_GUI=OFF -DENABLE_X11=OFF -DENABLE_NATIVE_SCRIPTING=ON \
  -DENABLE_PYTHON_SCRIPTING=OFF -DENABLE_PYTHON_EXTENSION=OFF -DENABLE_LIBSPIRO=OFF \
  -DENABLE_LIBUNINAMESLIST=OFF -DENABLE_LIBGIF=OFF -DENABLE_LIBJPEG=ON -DENABLE_LIBPNG=ON \
  -DENABLE_LIBREADLINE=OFF -DENABLE_LIBTIFF=OFF -DENABLE_WOFF2=OFF -DENABLE_DOCS=OFF \
  -DENABLE_CODE_COVERAGE=OFF -DENABLE_DEBUG_RAW_POINTS=OFF -DENABLE_FONTFORGE_EXTRAS=OFF \
  -DENABLE_MAINTAINER_TOOLS=OFF -DENABLE_TILE_PATH=OFF -DENABLE_WRITE_PFM=OFF \
  -DENABLE_SANITIZER=none -DENABLE_FREETYPE_DEBUGGER= -DSPHINX_USE_VENV=OFF \
  -DREAL_TYPE=double -DTHEME=tango
cmake --build fontforge/build -j "$JOBS"

# ── pdf2htmlEX ──
cmake -S pdf2htmlEX -B pdf2htmlEX/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$WORK/prefix"
cmake --build pdf2htmlEX/build -j "$JOBS"
cmake --install pdf2htmlEX/build

# ── Package a self-contained folder ──
rm -rf "$OUT"
mkdir -p "$OUT/bin/data" "$OUT/etc" "$OUT/share/poppler"
cp "$WORK/prefix/bin/pdf2htmlEX.exe" "$OUT/bin/"
cp -r "$WORK/prefix/share/pdf2htmlEX/." "$OUT/bin/data/"
# Every non-system DLL the executable needs, recursively
ldd "$OUT/bin/pdf2htmlEX.exe" | awk '/\/mingw64\// {print $3}' | sort -u | xargs -r -I{} cp {} "$OUT/bin/"
cp -r /mingw64/etc/fonts "$OUT/etc/"
cp -r poppler-data/. "$OUT/share/poppler/"
cp pdf2htmlEX-src/LICENSE* "$OUT/" 2>/dev/null || true
ls -la "$OUT/bin"
