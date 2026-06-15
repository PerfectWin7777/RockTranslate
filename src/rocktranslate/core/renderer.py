"""
RockTranslate — Headless Browser PDF Vector Renderer
Path: src/rocktranslate/core/renderer.py

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import sys
import shutil
import json
import subprocess
from typing import Optional, Dict, Any

if sys.platform == "win32":
    import winreg
else:
    winreg = None



def find_system_chromium_browser() -> Optional[str]:
    """Scans the operating system to find the path of a Chromium-based browser.

    Filters out non-Chromium browsers (e.g., Firefox) to prevent printing hangs.

    Returns:
        The absolute path to the browser binary, or None if none are found.
    """
    # 1. Search system environment PATH (Linux/macOS)
    common_commands = [
        "google-chrome", "chrome", "chromium", 
        "chromium-browser", "microsoft-edge", "msedge"
    ]
    for cmd in common_commands:
        resolved_path = shutil.which(cmd)
        if resolved_path:
            return resolved_path

    # 2. Search Windows Registry if running on Win32
    if sys.platform == "win32" and winreg:
        registry_path = r"SOFTWARE\Clients\StartMenuInternet"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as hkey:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(hkey, index)
                        index += 1
                        cmd_path = rf"{registry_path}\{subkey_name}\shell\open\command"
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cmd_path) as command_key:
                            raw_command, _ = winreg.QueryValueEx(command_key, "")
                            if raw_command:
                                clean_path = raw_command.strip().strip('"')
                                if " -osint" in clean_path:
                                    clean_path = clean_path.split(" -osint")[0].strip('"')
                                
                                clean_path_lower = clean_path.lower()
                                if any(x in clean_path_lower for x in ["chrome", "edge", "chromium", "brave"]):
                                    if os.path.exists(clean_path):
                                        return clean_path
                    except OSError as e:
                        if e.winerror == 259:  # No more registry subkeys
                            break
                        raise
        except Exception:
            pass

    # 3. Search standard app bundles on macOS
    elif sys.platform == "darwin": # todo
        mac_apps = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        ]
        for path in mac_apps:
            if os.path.exists(path):
                return path
                
    return None


def apply_translations_offline(
    input_html_path: str, 
    output_html_path: str, 
    translations: Dict[str, str], 
    page_size_css: str = "A4"
) -> None:
    """Injects the translated segments dictionary into a script tag inside the HTML.

    Appends an automated headless execution hook that triggers the original scale-compression
    and layout engine inside Chrome before compiling the PDF.

    Args:
        input_html_path: Path to the template instrumented HTML workspace.
        output_html_path: Path where the compiled output HTML should be written.
        translations: Dictionary mapping element IDs to translated strings.
        page_size_css: Target page layout rules (e.g., 'A4' or custom cm scale).
    """
    with open(input_html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    translations_json = json.dumps(translations, ensure_ascii=False)

    page_size_style = f"""
    <style>
    @page {{
        size: {page_size_css};
        margin: 0;
    }}
    body {{
        margin: 0;
        padding: 0;
    }}
    </style>
    """

    automated_hook_script = f"""
    <script>
    var cliTranslations = {translations_json};
    window.addEventListener('load', function() {{
        document.querySelectorAll('[id^="glass-overlay-t-"]').forEach(function(glass) {{
            glass.style.display = 'none';
        }});
        
        for (var transId in cliTranslations) {{
            if (window.applyTranslation) {{
                window.applyTranslation(transId, cliTranslations[transId]);
            }}
        }}
        
        document.querySelectorAll('.shimmer-line').forEach(function(el) {{
            el.classList.remove('shimmer-line');
        }});
    }});
    </script>
    """

    optimized_html = html_content.replace("</head>", f"{page_size_style}\n</head>")
    optimized_html = optimized_html.replace("</body>", f"{automated_hook_script}\n</body>")

    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(optimized_html)



def resolve_pdf_renderer() -> Optional[str]:
    """
    Orchestrates the dual-layer Chromium resolver.
    Attempts to locate a system-installed browser first. If missing,
    automatically downloads and extracts the lightweight stable
    'chrome-headless-shell' as an isolated local fallback.

    Returns:
        Optional[str]: Absolute path to a valid Chromium-based binary, 
                       or None if resolution and download both failed.
    """
    # 1. Look for a system-installed browser (0MB overhead)
    system_browser = find_system_chromium_browser()
    if system_browser:
        return system_browser

    # 2. Fallback to automated chrome-headless-shell downloader
    try:
        from .downloader import check_and_download_headless_shell
        return check_and_download_headless_shell()
    except Exception:
        # Fallback to resolve direct relative imports in CLI/API execution loops
        try:
            from rocktranslate.core.downloader import check_and_download_headless_shell
            return check_and_download_headless_shell()
        except Exception:
            return None

            

def print_html_to_vector_pdf(browser_path: str, input_html_path: str, output_pdf_path: str) -> bool:
    """Executes a headless background process using the resolved browser to print HTML to PDF.

    Args:
        browser_path: Path to the discovered Chromium-based browser executable.
        input_html_path: Path to the completed offline translated HTML document.
        output_pdf_path: Path where the high-fidelity output vector PDF will be written.

    Returns:
        True if the PDF was generated successfully, False otherwise.
    """
    if not os.path.exists(input_html_path):
        return False
        
    cmd = [
        browser_path,
        "--headless",
        "--disable-gpu",
        "--no-margins",               
        "--no-pdf-header-footer",
        f"--print-to-pdf={os.path.abspath(output_pdf_path)}",
        os.path.abspath(input_html_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False
