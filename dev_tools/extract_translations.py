"""
RockTranslate — Multi-language Translation Extraction Script
Path: dev_tools/extract_translations.py
"""

import os
import subprocess
import sys

def main() -> None:
    """
    Executes pylupdate6 targeting multiple locales (French, Spanish, German)
    to generate three distinct translation templates.
    """
    print("⚙️ Running translation extraction pipeline for all target languages...")
    
    # Define directories
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__),   ".."))
    print(project_root)
    
    # Correct path to the packaged assets
    output_ts_dir = os.path.join(project_root, "src", "rocktranslate", "assets", "translations")
    print(output_ts_dir)
    os.makedirs(output_ts_dir, exist_ok=True)
    
    # Target locales to generate
    locales = ["fr", "es", "de"]
    
    # Automatically scan and discover all Python source files recursively
    # This prevents the script from breaking when new files or directories are added
    source_dir = os.path.join(project_root, "src", "rocktranslate")
    existing_sources = []
    
    # Also look for main.py at the project root if present
    root_main = os.path.join(source_dir, "gui.py")
    ui_pyqt_dir = os.path.join(source_dir, "ui_pyqt")
    print(ui_pyqt_dir)
    if os.path.exists(root_main):
        existing_sources.append(os.path.relpath(root_main, project_root))

    for root, _, files in os.walk(ui_pyqt_dir):
        for file in files:
            if file.endswith(".py"):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, project_root)
                existing_sources.append(rel_path)
    
    if not existing_sources:
        print("❌ Error: No valid source files were detected for scanning.")
        sys.exit(1)
        
    print(f"📂 Scanned and registered {len(existing_sources)} Python source files.")

    for locale in locales:
        output_ts_file = os.path.join(output_ts_dir, f"rocktranslate_{locale}.ts")
        
        # Build and execute the pylupdate6 command for the active locale
        cmd = ["pylupdate6"] + existing_sources + ["-ts", output_ts_file]
        
        try:
            subprocess.run(cmd, check=True)
            print(f"✅ Success: Extracted {locale.upper()} sources at: {output_ts_file}")
        except FileNotFoundError:
            print(
                "❌ Error: 'pylupdate6' command line tool was not found.\n"
                "Please ensure you have installed pyqt6-dev-tools using pip:\n"
                "   pip install pyqt6-dev-tools"
            )
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"❌ Error: Extraction process failed for {locale} with code {e.returncode}")


if __name__ == "__main__":
    main()