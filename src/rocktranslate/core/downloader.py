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


# Hardcoded known good stable version of Chrome Headless Shell
CHROME_SHELL_VERSION: str = "134.0.6998.88"



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
        
        # Progress through the logger every 10% (no raw console writes: the
        # frozen GUI has no stdout, and writes from a daemon thread crashed
        # the interpreter at shutdown)
        last_step = [-1]

        def progress_callback(block_count: int, block_size: int, total_size: int) -> None:
            if total_size > 0:
                percent = min(100, int(block_count * block_size * 100 / total_size))
                if percent // 10 != last_step[0]:
                    last_step[0] = percent // 10
                    logger.info(f"Download progress: {percent}%")

        urllib.request.urlretrieve(url, zip_path, reporthook=progress_callback)
        
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


def pdf2htmlex_data_dir(executable: str) -> Optional[str]:
    """
    Returns the data directory to pass with --data-dir for an extracted
    AppImage build (whose compiled-in /usr/local/share path does not exist on
    the host), or None when the binary finds its own data.
    """
    base = os.path.dirname(os.path.abspath(executable))
    for candidate in (
        os.path.join(base, "usr", "local", "share", "pdf2htmlEX"),
        os.path.join(base, "usr", "share", "pdf2htmlEX"),
    ):
        if os.path.exists(os.path.join(candidate, "manifest")):
            return candidate
    return None


def _extract_appimage(appimage_path: str, target_dir: str) -> Optional[str]:
    """
    Extracts an AppImage once (no FUSE needed: Docker, WSL and Ubuntu >= 22.04
    ship without libfuse2) and returns the path of its AppRun entry point.
    """
    import subprocess
    work_dir = os.path.dirname(os.path.abspath(appimage_path))
    try:
        subprocess.run(
            [os.path.abspath(appimage_path), "--appimage-extract"],
            cwd=work_dir, check=True, timeout=300,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.error(f"Could not extract the pdf2htmlEX AppImage: {e}")
        return None
    extracted = os.path.join(work_dir, "squashfs-root")
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
    shutil.move(extracted, target_dir)
    app_run = os.path.join(target_dir, "AppRun")
    return app_run if os.path.exists(app_run) else None


def check_and_download_pdf2htmlex(assets_dir: str = DEFAULT_ASSETS_DIR) -> Optional[str]:
    """
    Resolves a working pdf2htmlEX executable.

    Order: user override -> system PATH -> bundled assets (Windows installer)
    -> previously downloaded engine in the user runtime dir -> download.
    Downloads always go to the user-writable runtime dir, never site-packages.

    Returns:
        Optional[str]: Absolute path to the executable, or None.
    """
    override_path = str(config_db.get("SystemConfig", "pdf2htmlex_path_override", "") or "").strip()
    if override_path and os.path.isfile(override_path):
        logger.info(f"Using user-defined pdf2htmlEX binary override: {override_path}")
        return override_path

    system_binary: Optional[str] = shutil.which("pdf2htmlEX")
    if system_binary:
        logger.info(f"Discovered system-wide pdf2htmlEX installation: {system_binary}")
        return system_binary

    system_os: str = platform.system().lower()
    binary_name: str = "pdf2htmlEX.exe" if system_os == "windows" else "pdf2htmlEX"

    # Bundled engine (Windows installer / source checkout). The directory may
    # also be a custom assets folder passed by the caller.
    for base in {assets_dir, DEFAULT_ASSETS_DIR}:
        if not base:
            continue
        bundled = os.path.join(base, "pdf2htmlEX", binary_name)
        if os.path.isfile(bundled) and system_os == "windows":
            return bundled
        extracted = os.path.join(base, "pdf2htmlEX", "appimage", "AppRun")
        if os.path.isfile(extracted):
            return extracted

    runtime_dir = os.path.join(str(config_db.get_runtime_dir()), "pdf2htmlEX")

    if system_os == "windows":
        for root, _, files in os.walk(runtime_dir) if os.path.isdir(runtime_dir) else []:
            if binary_name in files:
                return os.path.join(root, binary_name)
        logger.warning("pdf2htmlEX missing on Windows. Launching automated download...")
        if _download_and_extract(PDF2HTMLEX_DOWNLOAD_URL, runtime_dir, "pdf2htmlEX.zip"):
            for root, _, files in os.walk(runtime_dir):
                if binary_name in files:
                    resolved_path = os.path.join(root, binary_name)
                    logger.info(f"Successfully resolved local Windows binary: {resolved_path}")
                    return resolved_path
        logger.critical("Failed to retrieve pdf2htmlEX automatically.")
        return None

    if system_os == "linux":
        app_run = os.path.join(runtime_dir, "appimage", "AppRun")
        if os.path.isfile(app_run):
            return app_run
        if platform.machine().lower() not in ("x86_64", "amd64"):
            logger.critical(
                "The official pdf2htmlEX AppImage only exists for x86_64. "
                "Install pdf2htmlEX with your package manager and put it on PATH."
            )
            return None
        logger.warning("pdf2htmlEX missing on Linux. Downloading the official AppImage...")
        os.makedirs(runtime_dir, exist_ok=True)
        appimage_path = os.path.join(runtime_dir, "pdf2htmlEX.AppImage")
        try:
            urllib.request.urlretrieve(LINUX_APPIMAGE_URL, appimage_path)
            os.chmod(appimage_path, os.stat(appimage_path).st_mode | stat.S_IEXEC)
        except Exception as e:
            logger.error(f"Failed to download the pdf2htmlEX AppImage: {e}")
            return None
        resolved = _extract_appimage(appimage_path, os.path.join(runtime_dir, "appimage"))
        try:
            os.remove(appimage_path)
        except OSError:
            pass
        if resolved:
            logger.info(f"pdf2htmlEX ready (extracted AppImage, no FUSE needed): {resolved}")
        return resolved

    # macOS: no portable binary exists (Poppler linkage), Homebrew is required.
    logger.critical(
        "Required dependency 'pdf2htmlEX' was not found on this macOS system.\n"
        "Install it with Homebrew:  brew install pdf2htmlex\n"
        "Then restart RockTranslate."
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
    local_core: str = os.path.join(pdfjs_dir, "build", "pdf.js")

    # The viewer is useless without the core bundle it loads from ../build/
    if os.path.exists(local_viewer) and os.path.exists(local_core):
        return local_viewer
        
    logger.warning("Local PDF.js static package missing. Initiating download...")
    success = _download_and_extract(PDFJS_DOWNLOAD_URL, pdfjs_dir, "pdfjs.zip")
    
    if success and os.path.exists(local_viewer) and os.path.exists(local_core):
        logger.info("PDF.js static web package configured successfully.")
        return local_viewer
        
    logger.error("Failed to extract or configure the PDF.js web package.")
    return None


def get_headless_shell_platform_config() -> Optional[tuple[str, str]]:
    """
    Resolves the Google Chrome for Testing platform suffix and binary path 
    based on the current operating system architecture.

    Returns:
        Optional[tuple[str, str]]: (platform_suffix, relative_binary_path) or None.
    """
    sys_os = platform.system().lower()
    machine = platform.machine().lower()

    if sys_os == "windows":
        if "64" in machine:
            return "win64", os.path.join("chrome-headless-shell-win64", "chrome-headless-shell.exe")
        return "win32", os.path.join("chrome-headless-shell-win32", "chrome-headless-shell.exe")

    elif sys_os == "darwin":
        if "arm" in machine or "aarch" in machine:
            return "mac-arm64", os.path.join(
                "chrome-headless-shell-mac-arm64", 
                "chrome-headless-shell"
            )
        return "mac-x64", os.path.join(
            "chrome-headless-shell-mac-x64", 
            "chrome-headless-shell"
        )

    elif sys_os == "linux":
        if "64" in machine:
            return "linux64", os.path.join(
                "chrome-headless-shell-linux64", 
                "chrome-headless-shell"
            )

    return None


def find_downloaded_headless_shell(assets_dir: str = DEFAULT_ASSETS_DIR) -> Optional[str]:
    """Returns an already-downloaded chrome-headless-shell, without downloading."""
    config = get_headless_shell_platform_config()
    if not config:
        return None
    _, rel_binary_path = config
    for candidate in (
        os.path.join(str(config_db.get_runtime_dir()), "chromium_headless", CHROME_SHELL_VERSION, rel_binary_path),
        os.path.join(assets_dir, "chromium_headless", rel_binary_path),
    ):
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def check_and_download_headless_shell(assets_dir: str = DEFAULT_ASSETS_DIR) -> Optional[str]:
    """
    Checks if a local copy of Google Chrome Headless Shell is downloaded and extracted.
    If missing, automatically downloads the lightweight (~50MB) stable binaire ZIP
    from Google's official testing archives and extracts it to the assets folder.

    Args:
        assets_dir: Directory where local dependencies are stored.

    Returns:
        Optional[str]: Absolute path to the headless shell binary, or None if failed.
    """
    config = get_headless_shell_platform_config()
    if not config:
        logger.error("Could not resolve current OS platform architecture for Chrome Headless Shell.")
        return None

    platform_suffix, rel_binary_path = config
    # 1. Reuse a copy from a previous version (assets dir) or the runtime dir
    legacy_binary = os.path.join(assets_dir, "chromium_headless", rel_binary_path)
    if os.path.exists(legacy_binary):
        return os.path.abspath(legacy_binary)

    shell_dir = os.path.join(str(config_db.get_runtime_dir()), "chromium_headless", CHROME_SHELL_VERSION)
    local_binary_path = os.path.join(shell_dir, rel_binary_path)
    if os.path.exists(local_binary_path):
        return os.path.abspath(local_binary_path)

    # 2. Formulate the official Google Cloud Storage URL
    download_url = (
        f"https://storage.googleapis.com/chrome-for-testing-public/"
        f"{CHROME_SHELL_VERSION}/{platform_suffix}/"
        f"chrome-headless-shell-{platform_suffix}.zip"
    )

    logger.warning(
        f"Local vector rendering browser not found. "
        f"Downloading ultra-lightweight Headless Chromium ({CHROME_SHELL_VERSION})..."
    )

    zip_name = f"chrome-headless-shell-{platform_suffix}.zip"
    success = _download_and_extract(download_url, shell_dir, zip_name)

    if success and os.path.exists(local_binary_path):
        # On Unix systems (Linux, macOS), ensure execution permissions are active
        if platform.system().lower() != "windows":
            try:
                current_permissions = os.stat(local_binary_path)
                os.chmod(local_binary_path, current_permissions.st_mode | stat.S_IEXEC)
            except Exception as e:
                logger.warning(f"Could not automatically set executable flags on Linux/Mac: {e}")

        logger.info(f"Successfully configured local Headless Chromium at: {local_binary_path}")
        return os.path.abspath(local_binary_path)

    logger.error("Failed to automatically retrieve or configure Headless Chromium.")
    return None



if __name__ == "__main__":
    # Standard terminal diagnostic wrapper
    logger.info("Executing diagnostic run of Downloader...")
    logger.info(f"Resolved Assets Directory: {DEFAULT_ASSETS_DIR}")
    
    pdfjs_status = check_and_download_pdfjs()
    pdf_exe_status = check_and_download_pdf2htmlex()

    chrome_headless_status = check_and_download_headless_shell()
    
    logger.info(
        f"Diagnostic result -> PDF.js: {pdfjs_status} | pdf2htmlEX: {pdf_exe_status} | chromeHeadless: {chrome_headless_status}")