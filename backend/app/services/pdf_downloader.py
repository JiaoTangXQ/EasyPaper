"""PDF Downloader Service – downloads PDFs from URLs with validation and security."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
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

MAX_REDIRECTS = 5


@dataclass
class DownloadResult:
    file_bytes: bytes
    filename: str
    content_type: str


class PdfDownloader:
    def __init__(
        self,
        max_download_mb: int = DEFAULT_MAX_DOWNLOAD_MB,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.max_download_bytes = max_download_mb * 1024 * 1024
        # ``transport`` is a test seam; production callers leave it as None.
        self._transport = transport

    async def download(self, url: str) -> DownloadResult:
        """Download a PDF from *url*, validate it, and return the bytes.

        Raises ``ValueError`` for invalid/blocked URLs or non-PDF content,
        ``httpx.HTTPStatusError`` for HTTP errors, and
        ``httpx.TimeoutException`` on timeout.
        """
        normalized_url = self._normalize_url(url)

        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={"User-Agent": "EasyPaper/1.0 (Academic PDF Downloader)"},
            transport=self._transport,
        ) as client:
            current_url = normalized_url
            for _ in range(MAX_REDIRECTS + 1):
                # Re-validate every hop: a redirect can point at an internal host.
                self._validate_url_security(current_url)
                response = await client.get(current_url)
                if not response.is_redirect:
                    break
                location = response.headers.get("location")
                if not location:
                    break
                current_url = str(response.url.join(location))
            else:
                raise ValueError("Too many redirects")

            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            self._validate_content_type(content_type, current_url)

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

            filename = self._extract_filename(current_url, response)

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

        # Resolve DNS and validate every address. A public-looking hostname can
        # still resolve to a loopback/private/link-local address (SSRF), and the
        # regex above only catches IPv4 literals — DNS resolution closes both gaps.
        for ip in self._resolve_addresses(hostname):
            self._assert_public_ip(ip)

    def _resolve_addresses(self, hostname: str) -> list[str]:
        # An IP literal needs no DNS lookup, but still must be validated.
        try:
            ipaddress.ip_address(hostname)
            return [hostname]
        except ValueError:
            pass

        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise ValueError(f"Could not resolve host: {hostname}") from exc
        return [info[4][0] for info in infos]

    @staticmethod
    def _assert_public_ip(ip_str: str) -> None:
        # IPv6 scope id (e.g. fe80::1%eth0) is irrelevant for the range check.
        ip = ipaddress.ip_address(ip_str.split("%")[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("URL resolves to a non-public address")

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
