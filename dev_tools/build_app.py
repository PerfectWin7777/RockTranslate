"""
RockTranslate — Standalone Application Compilation Script
Path: dev_tools/build_app.py

This helper script automates the execution of PyInstaller across all platform
targets, bundling all core assets, offline translators, and the headless Chromium
engine into a distribution-ready directory.

Usage:
    python dev_tools/build_app.py
"""

import os
import sys
import shutil
import subprocess


def clean_outdated_build_directories(project_root: str) -> None:
    """ Cleans up outdated build and dist directories before compiling. """
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
    entry_point = os.path.join(project_root, "main.py")
    if not os.path.exists(entry_point):
        print(f"❌ Error: Entry point main.py not found at: {entry_point}")
        sys.exit(1)

    # Dynamic path data separator (; on Windows, : on Unix)
    path_sep = ";" if os.name == "nt" else ":"
    
    # Include all asset files (splash, logos, translations, pdfjs, lrelease)
    # Target path inside _MEIPASS extraction folder matches standard structures
    assets_src = os.path.join(project_root, "src", "assets")
    assets_dest = os.path.join("src", "assets")
    
    if not os.path.exists(assets_src):
        print(f"❌ Error: Required assets folder not found at: {assets_src}")
        sys.exit(1)

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
    ]

    # Optional: If you have placed an icon.ico inside src/assets/, apply it dynamically
    icon_path = os.path.join(assets_src, "rocktranslate_icon.png")
    if os.path.exists(icon_path):
        pyinstaller_args.append(f"--icon={icon_path}")
        print(f"🎨 Custom icon discovered and applied: {icon_path}")
    

    print(f"🚀 Running PyInstaller command with compiled parameters...")
    
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