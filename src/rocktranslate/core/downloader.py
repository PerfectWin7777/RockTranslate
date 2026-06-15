"""
RockTranslate — Cross-Platform Dependency Downloader and Validator
Path: src/rocktranslate/core/downloader.py

This module manages external binary engines required by RockTranslate:
1. PDF.js (Mozilla's offline visual PDF renderer)
2. pdf2htmlEX (High-fidelity HTML geometric converter)

=== MULTI-PLATFORM RUNTIME ARCHITECTURE ===
To ensure cross-platform execution without requiring tedious user installations:
- On Windows: Checks for a local binary. If missing, automatically downloads and 
  extracts a pre-bundled win32 distribution containing all Poppler DLL dependencies.
- On Linux: Solves shared library linkage issues (.so mismatches) by automatically 
  downloading the official standalone 'AppImage' package from GitHub. The file is 
  locally renamed to 'pdf2htmlEX', flagged with execution permissions (chmod +x), 
  and ran sandbox-free, requiring zero apt/yum commands from the end-user.
- On macOS: Relies on system-wide installations (Homebrew) during source execution 
  to match active CPU architectures (Apple Silicon M1/M2/M3 vs Intel), preventing 
  mismatched emulation bottlenecks. Native bundle injections (.app) occur at release packaging.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.1
"""

import os
import sys
import zipfile
import platform
import shutil
import stat
import urllib.request
from typing import Optional
from loguru import logger
# Safe imports supporting both standard module launches and localized directory scripts
from .config_manager import config_db
from .constants import (
    DEFAULT_ASSETS_DIR,
    PDFJS_DOWNLOAD_URL,
    PDF2HTMLEX_DOWNLOAD_URL,
)

# Official standalone AppImage for Linux x86_64 distributions
LINUX_APPIMAGE_URL: str = (
    "https://github.com/pdf2htmlEX/pdf2htmlEX/releases/download/v0.18.8.rc1/"
    "pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-focal-x86_64.AppImage"
)


def _download_and_extract(url: str, dest_dir: str, zip_name: str) -> bool:
    """
    Downloads a ZIP archive from a secure remote URL and extracts its content locally.

    Args:
        url: The absolute HTTP/HTTPS path to the archive file.
        dest_dir: Local destination folder where contents should be extracted.
        zip_name: The temporary filename assigned to the downloaded ZIP container.

    Returns:
        bool: True if the file was downloaded and extracted successfully, False otherwise.
    """
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, zip_name)
    
    try:
        logger.info(f"Downloading external assets from: {url}")
        
        # Safe command-line download progress tracker
        def progress_callback(block_count: int, block_size: int, total_size: int) -> None:
            if total_size > 0:
                percent = int(block_count * block_size * 100 / total_size)
                sys.stdout.write(f"\r[Downloader] Progress: {min(percent, 100)}%")
                sys.stdout.flush()

        urllib.request.urlretrieve(url, zip_path, reporthook=progress_callback)
        sys.stdout.write("\n")  # Release console line carriage
        
        logger.info("Extracting archive archive content...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(dest_dir)
            
        os.remove(zip_path)  # Clean up temporary zip file
        logger.info("Extraction complete. Temporary archive cleaned.")
        return True
        
    except Exception as e:
        logger.error(f"Failed to download and extract archive '{zip_name}': {e}")
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        return False


def check_and_download_pdf2htmlex(assets_dir: str = DEFAULT_ASSETS_DIR) -> Optional[str]:
    """
    Verifies if pdf2htmlEX is accessible on the host machine.
    
    Checks in order:
    1. The system environment variable PATH (ideal for macOS and system packages).
    2. Local execution folders in the target assets directory.
    3. Initiates an automated download if running on Windows or Linux.

    Args:
        assets_dir: The directory where downloaded local components are stored.

    Returns:
        Optional[str]: The absolute path to the executable binary if found or configured,
                       otherwise None.
    """
    # Check if a custom system override path is specified in the JSON config  by the user
    override_path = str(config_db.get("SystemConfig", "pdf2htmlex_path_override", "")).strip()
    if override_path and os.path.exists(override_path):
        logger.info(f"Using user-defined pdf2htmlEX binary override: {override_path}")
        return override_path
    
    # 1. Look for a globally pre-installed instance in the system path (any platform)
    system_binary: Optional[str] = shutil.which("pdf2htmlEX")
    if system_binary:
        logger.info(f"Discovered system-wide pdf2htmlEX installation: {system_binary}")
        return system_binary

    system_os: str = platform.system().lower()
    binary_name: str = "pdf2htmlEX.exe" if system_os == "windows" else "pdf2htmlEX"
    
    pdf2html_dir: str = os.path.join(assets_dir, "pdf2htmlEX")
    local_binary_path: str = os.path.join(pdf2html_dir, binary_name)

    # 2. Check if a local version is already downloaded and present in the local directory
    if os.path.exists(local_binary_path):
        return local_binary_path

    # 3. If missing, attempt platform-based recovery
    if system_os == "windows":
        logger.warning("Local pdf2htmlEX binary missing on Windows. Launching automated download...")
        success = _download_and_extract(PDF2HTMLEX_DOWNLOAD_URL, pdf2html_dir, "pdf2htmlEX.zip")
        if success:
            # Recursive scan to find nested binaries in case sub-folders are created during extraction
            for root, _, files in os.walk(pdf2html_dir):
                if binary_name in files:
                    resolved_path = os.path.join(root, binary_name)
                    logger.info(f"Successfully resolved local Windows binary: {resolved_path}")
                    return resolved_path
        logger.critical("Failed to retrieve or compile pdf2htmlEX automatically.")
        return None

    elif system_os == "linux":
        logger.warning("Local pdf2htmlEX binary missing on Linux. Launching automated AppImage download...")
        os.makedirs(pdf2html_dir, exist_ok=True)
        try:
            # Download Linux AppImage and rename it locally to match generic call names
            urllib.request.urlretrieve(LINUX_APPIMAGE_URL, local_binary_path)
            
            # Grant execute permission to the AppImage (equivalent to chmod +x)
            current_permissions = os.stat(local_binary_path)
            os.chmod(local_binary_path, current_permissions.st_mode | stat.S_IEXEC)
            
            logger.info(f"Successfully configured Linux AppImage executable at: {local_binary_path}")
            return local_binary_path
        except Exception as e:
            logger.error(f"Failed to automatically set up Linux AppImage: {e}")
            return None

    else:
        # macOS systems cannot safely share dynamic pre-compiled binaries due to Poppler linkage mismatches.
        # Direct terminal instructions are provided to avoid crash-loops.
        logger.critical(
            f"Required dependency 'pdf2htmlEX' was not found on this macOS system.\n"
            f"Please install it using Homebrew:\n"
            f" - macOS (Homebrew):  brew install pdf2htmlex\n"
            f"Once installed, restart RockTranslate to continue."
        )
        return None


def check_and_download_pdfjs(assets_dir: str = DEFAULT_ASSETS_DIR) -> Optional[str]:
    """
    Verifies if Mozilla's PDF.js offline reader is available locally.
    If missing, downloads and configures the static web package.

    Args:
        assets_dir: Target directory holding static layout components.

    Returns:
        Optional[str]: Path to the local static 'viewer.html' if loaded, otherwise None.
    """
    # Check if a custom system folder override is specified in the JSON config  by the user
    override_path = str(config_db.get("SystemConfig", "pdfjs_path_override", "")).strip()
    if override_path and os.path.exists(override_path):
        viewer_path = os.path.join(override_path, "web", "viewer.html")
        if os.path.exists(viewer_path):
            return viewer_path
        
    pdfjs_dir: str = os.path.join(assets_dir, "pdfjs")
    local_viewer: str = os.path.join(pdfjs_dir, "web", "viewer.html")
    
    if os.path.exists(local_viewer):
        return local_viewer
        
    logger.warning("Local PDF.js static package missing. Initiating download...")
    success = _download_and_extract(PDFJS_DOWNLOAD_URL, pdfjs_dir, "pdfjs.zip")
    
    if success and os.path.exists(local_viewer):
        logger.info("PDF.js static web package configured successfully.")
        return local_viewer
        
    logger.error("Failed to extract or configure the PDF.js web package.")
    return None


if __name__ == "__main__":
    # Standard terminal diagnostic wrapper
    logger.info("Executing diagnostic run of Downloader...")
    logger.info(f"Resolved Assets Directory: {DEFAULT_ASSETS_DIR}")
    
    pdfjs_status = check_and_download_pdfjs()
    pdf_exe_status = check_and_download_pdf2htmlex()
    
    logger.info(f"Diagnostic result -> PDF.js: {pdfjs_status} | pdf2htmlEX: {pdf_exe_status}")