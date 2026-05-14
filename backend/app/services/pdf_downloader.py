"""PDF Downloader Service – downloads PDFs from URLs with validation and security."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

ACADEMIC_HOSTS = frozenset(
    {
        "arxiv.org",
        "www.arxiv.org",
        "export.arxiv.org",
        "openreview.net",
        "proceedings.neurips.cc",
        "aclanthology.org",
        "dl.acm.org",
        "ieeexplore.ieee.org",
        "link.springer.com",
        "www.biorxiv.org",
        "www.medrxiv.org",
        "github.com",
        "raw.githubusercontent.com",
    }
)

BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})

DEFAULT_MAX_DOWNLOAD_MB = 50


@dataclass
class DownloadResult:
    file_bytes: bytes
    filename: str
    content_type: str


class PdfDownloader:
    def __init__(self, max_download_mb: int = DEFAULT_MAX_DOWNLOAD_MB) -> None:
        self.max_download_bytes = max_download_mb * 1024 * 1024

    async def download(self, url: str) -> DownloadResult:
        """Download a PDF from *url*, validate it, and return the bytes.

        Raises ``ValueError`` for invalid/blocked URLs or non-PDF content,
        ``httpx.HTTPStatusError`` for HTTP errors, and
        ``httpx.TimeoutException`` on timeout.
        """
        normalized_url = self._normalize_url(url)
        self._validate_url_security(normalized_url)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={"User-Agent": "EasyPaper/1.0 (Academic PDF Downloader)"},
        ) as client:
            response = await client.get(normalized_url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            self._validate_content_type(content_type, normalized_url)

            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.max_download_bytes:
                raise ValueError(
                    f"File too large: {int(content_length) // (1024 * 1024)}MB "
                    f"(max {self.max_download_bytes // (1024 * 1024)}MB)"
                )

            file_bytes = response.content
            if len(file_bytes) > self.max_download_bytes:
                raise ValueError(f"Downloaded file too large: {len(file_bytes) // (1024 * 1024)}MB")

            if not file_bytes.startswith(b"%PDF"):
                raise ValueError("Downloaded file is not a valid PDF")

            filename = self._extract_filename(normalized_url, response)

        return DownloadResult(
            file_bytes=file_bytes,
            filename=filename,
            content_type="application/pdf",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_url(self, url: str) -> str:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        parsed = urlparse(url)

        # arXiv /abs/ → /pdf/
        if parsed.hostname in ("arxiv.org", "www.arxiv.org"):
            abs_match = re.match(r"/abs/(.+?)/?$", parsed.path)
            if abs_match:
                return f"https://arxiv.org/pdf/{abs_match.group(1)}.pdf"
            pdf_match = re.match(r"/pdf/(.+?)/?$", parsed.path)
            if pdf_match and not parsed.path.endswith(".pdf"):
                return f"https://arxiv.org/pdf/{pdf_match.group(1)}.pdf"

        # GitHub blob → raw download
        if parsed.hostname in ("github.com", "www.github.com"):
            blob_match = re.match(r"/([^/]+/[^/]+)/blob/(.+)", parsed.path)
            if blob_match:
                return f"https://raw.githubusercontent.com/{blob_match.group(1)}/{blob_match.group(2)}"

        return url

    def _validate_url_security(self, url: str) -> None:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            raise ValueError("Only HTTP and HTTPS URLs are supported")

        hostname = parsed.hostname or ""
        if hostname in BLOCKED_HOSTS:
            raise ValueError("URL points to a blocked host")

        if re.match(
            r"^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|0\.)",
            hostname,
        ):
            raise ValueError("URL points to a private network")

        # Block hostnames that resolve to common internal patterns
        if hostname.endswith(".local") or hostname.endswith(".internal"):
            raise ValueError("URL points to a private network")

    def _validate_content_type(self, content_type: str, url: str) -> None:
        base_ct = content_type.lower().split(";")[0].strip()
        if base_ct in {"application/pdf", "application/octet-stream"}:
            return

        parsed = urlparse(url)
        if parsed.hostname in ACADEMIC_HOSTS:
            return  # trust known hosts; magic-byte check is the final guard

        raise ValueError(f"URL does not appear to serve a PDF (content-type: {content_type})")

    def _extract_filename(self, url: str, response: httpx.Response) -> str:
        cd = response.headers.get("content-disposition", "")
        if "filename=" in cd:
            match = re.search(r'filename[*]?=(?:"([^"]+)"|(\S+))', cd)
            if match:
                name = match.group(1) or match.group(2)
                if name and name.lower().endswith(".pdf"):
                    return name

        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path:
            last_segment = path.split("/")[-1]
            if last_segment:
                return last_segment if "." in last_segment else f"{last_segment}.pdf"

        return "downloaded_paper.pdf"
