"""
RockTranslate — Standalone Application Compilation Script (Web Engine Edition)
Path: dev_tools/build_app.py

This helper script automates the execution of PyInstaller across all platform
targets, bundling all core assets, offline translators, and the headless Chromium
engine into a distribution-ready directory.
Optimized to exclude redundant modules

Usage:
    python dev_tools/build_app.py
"""

import os
import sys
import shutil
import subprocess


def clean_outdated_build_directories(project_root: str) -> None:
    """Cleans up outdated build and dist directories before compiling."""
    print("🧹 Cleaning previous compilation cache...")
    for folder in ["build", "dist"]:
        path = os.path.join(project_root, folder)
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                print(f"   -> Removed old directory: {folder}/")
            except OSError as e:
                print(f"   -> Warning: Failed to clean {folder} directory: {e}")


def main() -> None:
    """
    Main compilation routine. Resolves system variables, builds arguments,
    and runs PyInstaller to compile the standalone binary.
    """
    print("⚙️ Initiating standalone compilation pipeline via PyInstaller...")
    
    # 1. Resolve Project Paths
    dev_tools_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(dev_tools_dir, ".."))
    
    clean_outdated_build_directories(project_root)

    # 2. Configure PyInstaller Arguments
    entry_point = os.path.join(project_root, "src", "rocktranslate", "web_gui.py")
    if not os.path.exists(entry_point):
        print(f"❌ Error: Entry point web_gui.py not found at: {entry_point}")
        sys.exit(1)

    # Dynamic path data separator (; on Windows, : on Unix)
    path_sep = ";" if os.name == "nt" else ":"
    
    # Include all web asset files (html templates, stylesheets, scripts, splash, etc.)
    # Target path inside _MEIPASS extraction folder matches standard constants layout rules
    assets_src = os.path.abspath(os.path.join(project_root, "src", "rocktranslate", "assets"))
    assets_dest = os.path.join("rocktranslate", "assets")
    
    if not os.path.exists(assets_src):
        print(f"❌ Error: Required assets folder not found at: {assets_src}")
        sys.exit(1)

    # Core PyInstaller execution parameters
    pyinstaller_args = [
        entry_point,
        "--name=RockTranslate",
        "--clean",  # Clears PyInstaller cache
        f"--paths={os.path.join(project_root, 'src')}", 
        "--noconsole",  # Hides the black terminal CMD window on startup
        f"--add-data={assets_src}{path_sep}{assets_dest}",
        "--collect-data=litellm",
        "--hidden-import=tiktoken_ext.openai_public",
        "--hidden-import=tiktoken_ext",
        # Webview runtime hidden imports (Critical for Windows .NET & WebKit)
        "--hidden-import=clr",
        "--hidden-import=webview.platforms.winforms",
        "--hidden-import=webview.platforms.cocoa",
    ]

    # --- ADVANCED SIZE OPTIMIZATION: EXCLUDE UNUSED MODULES ---
    # We explicitly exclude PyQt6, PySide6, and PyMuPDF (fitz) to reduce final binary weight.
    excluded_modules = [
        "PySide6", "shiboken6", "pyside6_essentials", "PySide2",
        "PyQt6", "PyQt5",
        # Exclude PyMuPDF (fitz) to save ~30MB of weight
        "fitz", "pymupdf"
    ]
    for module in excluded_modules:
        pyinstaller_args.append(f"--exclude-module={module}")

    # Discover and apply the application icon dynamically (Windows exe, taskbar, titlebar)
    icon_path = os.path.join(assets_src, "rocktranslate_icon.png")
    if os.path.exists(icon_path):
        # On Windows, PyInstaller preferred format is .ico (png is converted or used natively depending on targets)
        pyinstaller_args.append(f"--icon={icon_path}")
        print(f"🎨 Custom icon discovered and applied: {icon_path}")

    print("🚀 Running PyInstaller command with compiled parameters...")
    
    # Run PyInstaller as a subprocess
    try:
        cmd = ["pyinstaller"] + pyinstaller_args
        subprocess.run(cmd, check=True, cwd=project_root)
        print("\n🎉 Compilation Succeeded!")
        print(f"📂 Standalone executable is available inside: {os.path.join(project_root, 'dist', 'RockTranslate')}")
    except FileNotFoundError:
        print(
            "❌ Error: 'pyinstaller' command was not found in this environment.\n"
            "Please ensure you have installed pyinstaller inside your virtual environment:\n"
            "   pip install pyinstaller"
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: Compilation failed with code {e.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    main()