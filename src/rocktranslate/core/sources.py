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
from typing import Callable, Optional, Tuple

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


def download_pdf(url: str, progress: Optional[Callable[[int, int], None]] = None) -> str:
    """
    Downloads a PDF link into the cache and returns the local path.
    progress(bytes_done, bytes_total) is called as the file arrives
    (bytes_total is 0 when the server does not announce the size).

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
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except ValueError:
            total = 0
        while True:
            block = response.read(256 * 1024)
            if not block:
                break
            size += len(block)
            if progress:
                try:
                    progress(size, total)
                except Exception:
                    pass
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


_ARXIV_ID_RE = re.compile(r"^(?:arxiv:\s*)?(\d{4}\.\d{4,5}(?:v\d+)?)$", re.I)
_SCHEMELESS_URL_RE = re.compile(r"^(?:www\.|arxiv\.org/|openreview\.net/|doi\.org/)[^\s]+$", re.I)


def parse_pdf_source(text: str) -> Tuple[str, str]:
    """
    Interprets what a user pasted to open a PDF. Returns (kind, value):

        ("url",  "https://...")      http(s) link; also 'arxiv.org/abs/..', 'www..'
                                     without scheme, and a bare arXiv id ('1706.03762')
        ("path", "/abs/path.pdf")    an existing local PDF: Windows or POSIX path, with
                                     or without quotes (Explorer's 'Copy as path'),
                                     file:// URI, ~ and environment variables expanded
        ("error", key)               'empty', 'not_found', 'not_pdf', 'is_folder'

    Only the first non-empty line counts (a copied list of files opens the first one).
    """
    lines = [ln.strip() for ln in (text or "").replace("\r", "\n").split("\n") if ln.strip()]
    if not lines:
        return "error", "empty"
    raw = lines[0].strip().strip('"').strip("'").strip("\u201c\u201d\u2018\u2019").strip()
    if not raw:
        return "error", "empty"
    if is_url(raw):
        return "url", raw
    m = _ARXIV_ID_RE.match(raw)
    if m:
        return "url", f"https://arxiv.org/abs/{m.group(1)}"
    if _SCHEMELESS_URL_RE.match(raw):
        return "url", "https://" + raw
    path = raw
    if path.lower().startswith("file:"):
        parsed = urllib.parse.urlparse(path)
        path = urllib.request.url2pathname(urllib.parse.unquote(parsed.path))
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            path = f"//{parsed.netloc}{path}"          # UNC share: file://server/share/x.pdf
        elif os.name == "nt" and re.match(r"^[\\/][A-Za-z]:", path):
            path = path[1:]                              # file:///C:/x.pdf -> C:/x.pdf
    path = os.path.expandvars(os.path.expanduser(path))
    if os.path.isdir(path):
        return "error", "is_folder"
    if not os.path.isfile(path):
        return "error", "not_found"
    try:
        with open(path, "rb") as f:
            if f.read(5) != b"%PDF-" and not path.lower().endswith(".pdf"):
                return "error", "not_pdf"
    except OSError:
        return "error", "not_found"
    return "path", os.path.abspath(path)


def resolve_pdf_source(source: str) -> str:
    """Local path unchanged; http(s) link -> path of its downloaded copy."""
    return download_pdf(source) if is_url(source) else source


def default_output_dir(source: str, local_path: str) -> str:
    """
    Where outputs go by default: next to a local PDF, but in the current
    directory for a link (never inside the hidden download cache).
    """
    return os.getcwd() if is_url(source) else os.path.dirname(os.path.abspath(local_path))
