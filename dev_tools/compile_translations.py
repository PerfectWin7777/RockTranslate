"""
RockTranslate — Light-weighted Translation Compilation Script
Path: dev_tools/extract_translations.py

This helper script automates the compilation of translated .ts (XML) files into
optimized .qm (binary) files. If no local Qt compilation tools are found on Windows,
it automatically downloads a lightweight static release of lrelease.exe (12MB)
to compile the files instantly.

Usage:
    python compile_translations.py
"""

import os
import sys
import zipfile
import subprocess
import urllib.request
from typing import Optional

def download_lightweight_lrelease(target_dir: str) -> Optional[str]:
    """
    Downloads a lightweight static Qt-Linguist package (12MB) on Windows,
    extracts the 2MB lrelease.exe binary, and returns its absolute path.
    """
    os.makedirs(target_dir, exist_ok=True)
    local_exe = os.path.join(target_dir, "lrelease.exe")
    
    if os.path.exists(local_exe):
        return local_exe
        
    print("⏳ No Qt compiler found. Downloading lightweight standalone compiler (12MB)...")
    
    # Official standalone lightweight Qt6 Linguist Tools release for Windows
    url = "https://github.com/thurask/Qt-Linguist/releases/download/20260425/linguist_6.11.0.zip"
    zip_path = os.path.join(target_dir, "qt_linguist.zip")
    "https://api.github.com/repos/thurask/Qt-Linguist/releases/latest"
    try:
        # Simple download progress logger
        def progress_callback(block_count, block_size, total_size):
            if total_size > 0:
                percent = int(block_count * block_size * 100 / total_size)
                sys.stdout.write(f"\r[Downloader] Progress: {min(percent, 100)}%")
                sys.stdout.flush()

        urllib.request.urlretrieve(url, zip_path, reporthook=progress_callback)
        sys.stdout.write("\n")
        
        print("📂 Extracting compiler binary...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Only extract the tiny lrelease.exe to save space
            zip_ref.extract("lrelease.exe", target_dir)
            
        # Clean up the downloaded temporary 12MB archive
        os.remove(zip_path)
        print(f"✅ Standalone compiler configured successfully at: {local_exe}")
        return local_exe
        
    except Exception as e:
        print(f"❌ Error: Failed to retrieve standalone compiler: {e}")
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        return None


def main() -> None:
    """
    Main compilation routine. Resolves the compiler path (local, system, or downloaded)
    and compiles all .ts files into production-ready .qm packages.
    """
    print("⚙️ Running translation compilation pipeline...")
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ts_dir = os.path.join(project_root, "src", "assets", "translations")
    locales = ["fr", "es", "de"]
    
    # 1. Resolve compiler tool executable
    lrelease_tool = "pyside6-lrelease"
    
    # Check if a custom system-wide lrelease command exists
    if not shutil_which(lrelease_tool) and not shutil_which("lrelease"):
        if os.name == "nt":
            # On Windows, trigger our automated lightweight download if missing
            assets_dir = os.path.join(project_root, "src", "assets")
            downloaded_exe = download_lightweight_lrelease(assets_dir)
            if downloaded_exe:
                lrelease_tool = downloaded_exe
            else:
                print("❌ Error: Could not resolve or download a valid Qt compiler.")
                sys.exit(1)
        else:
            lrelease_tool = "lrelease"

    # 2. Execute compilation sequentially
    for locale in locales:
        ts_path = os.path.join(ts_dir, f"rocktranslate_{locale}.ts")
        qm_path = os.path.join(ts_dir, f"rocktranslate_{locale}.qm")
        
        if not os.path.exists(ts_path):
            print(f"⚠️ Warning: Skipping missing file: {ts_path}")
            continue
            
        cmd = [lrelease_tool, ts_path, "-qm", qm_path]
        try:
            # Run without shell on Windows for absolute downloaded exe paths
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            print(f"✅ Success: Compiled {locale.upper()} to: {qm_path}")
        except FileNotFoundError:
            print(f"❌ Error: Compiled tools '{lrelease_tool}' failed to execute.")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"❌ Error: Compilation failed for {locale} with code {e.returncode}")


def shutil_which(cmd: str) -> bool:
    """ Helper to check command availability in system PATH. """
    import shutil
    return shutil.which(cmd) is not None


if __name__ == "__main__":
    main()