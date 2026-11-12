"""
RockTranslate — PDF sources: local paths and web links
Path: src/rocktranslate/core/sources.py

Every entry point (GUI, CLI, Python API) accepts either a local PDF path or
an http(s) link. A link is downloaded once into the application cache
(keyed by the URL) and the local copy is used from then on, so translating
the same arXiv paper twice does not download it twice.

    >>> resolve_pdf_source("https://arxiv.org/abs/2109.03697")
    '.../cache/downloads/3f2a.../2109.03697.pdf'

Author: RockTranslate Contributors
License: MIT License
"""

import hashlib
import os
import re
import urllib.parse
import urllib.request
from email.message import Message
from typing import Optional

from loguru import logger

from .config_manager import config_db

MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024   # a scientific PDF is far below this
TIMEOUT_SECONDS = 60
USER_AGENT = "Mozilla/5.0 (compatible; RockTranslate PDF translator)"


def is_url(source: str) -> bool:
    """True for http(s) links (anything else is treated as a local path)."""
    return bool(re.match(r"^https?://", (source or "").strip(), re.I))


def normalize_pdf_url(url: str) -> str:
    """
    Turns known landing pages into their direct PDF link:
    arXiv  /abs/ID  -> /pdf/ID ; OpenReview forum?id= -> pdf?id= .
    Other links are kept as they are.
    """
    url = url.strip()
    m = re.match(r"^https?://(?:www\.)?arxiv\.org/abs/([^?#]+)", url, re.I)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    m = re.match(r"^https?://(?:www\.)?openreview\.net/forum\?id=([^&#]+)", url, re.I)
    if m:
        return f"https://openreview.net/pdf?id={m.group(1)}"
    return url


def _file_name(url: str, content_disposition: Optional[str]) -> str:
    """Readable file name for the downloaded PDF (server name, else URL path)."""
    name = ""
    if content_disposition:
        msg = Message()
        msg["content-disposition"] = content_disposition
        name = msg.get_filename() or ""
    if not name:
        path = urllib.parse.urlparse(url).path.rstrip("/")
        name = urllib.parse.unquote(path.rsplit("/", 1)[-1]) or "document"
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .") or "document"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:150]


def download_pdf(url: str) -> str:
    """
    Downloads a PDF link into the cache and returns the local path.

    Raises:
        ValueError: the link does not lead to a PDF (HTML page, paywall...).
        OSError: network error.
    """
    url = normalize_pdf_url(url)
    folder = os.path.join(str(config_db.get_cache_dir()), "downloads",
                          hashlib.sha256(url.encode("utf-8")).hexdigest()[:16])
    if os.path.isdir(folder):
        for entry in os.listdir(folder):
            if entry.lower().endswith(".pdf"):
                cached = os.path.join(folder, entry)
                logger.info(f"Using the PDF already downloaded from {url}: {cached}")
                return cached

    logger.info(f"Downloading {url} ...")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        head = response.read(5)
        if head != b"%PDF-":
            raise ValueError(
                f"This link does not lead to a PDF file ({response.headers.get('Content-Type', 'unknown type')}). "
                "Use the direct link of the PDF (for example the 'Download PDF' button of the page).")
        chunks = [head]
        size = len(head)
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            if size > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"The PDF is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB.")
            chunks.append(block)
        name = _file_name(response.geturl() or url, response.headers.get("Content-Disposition"))

    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        for block in chunks:
            f.write(block)
    os.replace(tmp, path)
    logger.info(f"Downloaded {size / 1e6:.1f} MB -> {path}")
    return path


def resolve_pdf_source(source: str) -> str:
    """Local path unchanged; http(s) link -> path of its downloaded copy."""
    return download_pdf(source) if is_url(source) else source


def default_output_dir(source: str, local_path: str) -> str:
    """
    Where outputs go by default: next to a local PDF, but in the current
    directory for a link (never inside the hidden download cache).
    """
    return os.getcwd() if is_url(source) else os.path.dirname(os.path.abspath(local_path))
