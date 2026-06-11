"""
RockTranslate — Multi-language Translation Extraction Script
Path: extract_translations.py

This helper script automates the execution of pylupdate6 across all python
source files to generate or update the XML-based .ts translation files
for French, Spanish, and German locales.

Usage:
    python extract_translations.py
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
    project_root = os.path.dirname(os.path.abspath(__file__))
    output_ts_dir = os.path.join(project_root, "src", "assets", "translations")
    os.makedirs(output_ts_dir, exist_ok=True)
    
    # Target locales to generate
    locales = ["fr", "es", "de"]
    
    # Source files list to scan
    source_files = [
        "main.py",
        "src/ui_pyqt/main_window.py",
        "src/ui_pyqt/utils/recent_files_manager.py",
        "src/ui_pyqt/utils/pdf_exporter.py",
        "src/ui_pyqt/widget/api_config_dialog.py",
        "src/ui_pyqt/widget/translation_settings_dialog.py",
        "src/ui_pyqt/widget/system_settings_dialog.py",
        "src/ui_pyqt/widget/progress_panel.py",
        "src/ui_pyqt/widget/properties_dialog.py",
        "src/ui_pyqt/widget/workspace_viewer.py",
        "src/ui_pyqt/widget/zoom_widget.py",
    ]
    
    # Filter out missing files to avoid command failures
    existing_sources = [f for f in source_files if os.path.exists(os.path.join(project_root, f))]
    
    if not existing_sources:
        print("❌ Error: No valid source files were detected for scanning.")
        sys.exit(1)
        
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