"""PDF Downloader Service – downloads PDFs from URLs with validation and security."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
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
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 240
RANGE_CHUNK_BYTES = 4 * 1024 * 1024
# Some academic CDNs throttle concurrent ranges from one address. Keep the
# number of in-flight ranges small while still resetting stalled streams.
RANGE_CONCURRENCY = 2
RANGE_REQUEST_TIMEOUT_SECONDS = 20
RANGE_ATTEMPTS = 3

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
        timeout_seconds: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
        proxy: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.max_download_bytes = max_download_mb * 1024 * 1024
        self.timeout_seconds = timeout_seconds
        # Public academic CDNs may throttle direct connections from cloud IPs.
        # A deployment can opt into its managed egress proxy without enabling
        # httpx's broad environment proxy handling.
        self.proxy = proxy if proxy is not None else os.getenv("EASYPAPER_DOWNLOAD_PROXY", "").strip() or None
        # ``transport`` is a test seam; production callers leave it as None.
        self._transport = transport

    async def download(self, url: str) -> DownloadResult:
        """Download a PDF from *url*, validate it, and return the bytes.

        Raises ``ValueError`` for invalid/blocked URLs or non-PDF content,
        ``httpx.HTTPStatusError`` for HTTP errors, and
        ``httpx.TimeoutException`` on timeout.
        """
        async with asyncio.timeout(self.timeout_seconds):
            return await self._download(url)

    async def _download(self, url: str) -> DownloadResult:
        normalized_url = self._normalize_url(url)

        async with httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            proxy=self.proxy,
            timeout=httpx.Timeout(self.timeout_seconds, connect=min(10.0, self.timeout_seconds)),
            limits=httpx.Limits(max_connections=RANGE_CONCURRENCY, max_keepalive_connections=0),
            headers={"User-Agent": "EasyPaper/1.0 (Academic PDF Downloader)", "Accept-Encoding": "identity"},
            transport=self._transport,
        ) as client:
            current_url = normalized_url
            for hop in range(MAX_REDIRECTS + 1):
                # Resolve once and validate every address before connecting. In
                # direct mode we connect to that exact address while preserving
                # Host/TLS SNI; proxy mode lets the trusted proxy resolve the
                # hostname after this public-address check.
                addresses = await asyncio.to_thread(self._validate_url_security, current_url)
                target = httpx.URL(current_url)
                pinned = target.copy_with(host=addresses[0])
                # An HTTP proxy terminates the CONNECT target selection. Keep
                # the hostname in that mode so TLS validates the academic
                # site's certificate; direct connections remain IP-pinned.
                request_target = target if self.proxy else pinned
                ranged_total = None
                async with client.stream(
                    "GET",
                    request_target,
                    headers={"Host": target.netloc.decode("ascii"), "Range": "bytes=0-0"},
                    extensions={"sni_hostname": target.host},
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location or hop == MAX_REDIRECTS:
                            raise ValueError("Too many redirects or missing redirect location")
                        current_url = str(target.join(location))
                        continue
                    response.raise_for_status()
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ValueError("Compressed HTTP responses are not supported")
                    self._validate_content_type(response.headers.get("content-type", ""), current_url)
                    content_range = response.headers.get("content-range", "")
                    range_match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                    if (
                        response.status_code == 206
                        and range_match
                        and range_match.group(1) == "0"
                        and range_match.group(2) == "0"
                    ):
                        ranged_total = int(range_match.group(3))
                        if ranged_total > self.max_download_bytes:
                            raise ValueError("Downloaded file too large")
                        filename = self._extract_filename(current_url, response)
                        continue_ranges = True
                    elif response.status_code != 200:
                        raise ValueError("Server returned an unsupported partial PDF response")
                    else:
                        continue_ranges = False
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > self.max_download_bytes:
                        raise ValueError("Downloaded file too large")
                    if not continue_ranges:
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                            size += len(chunk)
                            if size > self.max_download_bytes:
                                raise ValueError("Downloaded file too large")
                            chunks.append(chunk)
                        file_bytes = b"".join(chunks)
                        if not file_bytes.startswith(b"%PDF"):
                            raise ValueError("Downloaded file is not a valid PDF")
                        filename = self._extract_filename(current_url, response)
                if ranged_total is not None:
                    file_bytes = await self._download_ranges(client, request_target, target, ranged_total)
                    if not file_bytes.startswith(b"%PDF"):
                        raise ValueError("Downloaded file is not a valid PDF")
                    break
                break

        return DownloadResult(
            file_bytes=file_bytes,
            filename=filename,
            content_type="application/pdf",
        )

    async def _download_ranges(
        self, client: httpx.AsyncClient, pinned: httpx.URL, target: httpx.URL, total: int
    ) -> bytes:
        ranges = [
            (start, min(total - 1, start + RANGE_CHUNK_BYTES - 1)) for start in range(0, total, RANGE_CHUNK_BYTES)
        ]
        semaphore = asyncio.Semaphore(RANGE_CONCURRENCY)

        async def fetch(start: int, end: int) -> tuple[int, bytes]:
            expected = end - start + 1
            for attempt in range(1, RANGE_ATTEMPTS + 1):
                try:
                    async with semaphore:
                        response = await client.get(
                            pinned,
                            headers={"Host": target.netloc.decode("ascii"), "Range": f"bytes={start}-{end}"},
                            extensions={"sni_hostname": target.host},
                            timeout=httpx.Timeout(
                                min(RANGE_REQUEST_TIMEOUT_SECONDS, self.timeout_seconds),
                                connect=min(10.0, self.timeout_seconds),
                            ),
                        )
                    if response.status_code != 206:
                        raise ValueError("Server did not honor PDF range request")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ValueError("Compressed HTTP responses are not supported")
                    content_range = response.headers.get("content-range", "")
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                    if (
                        not match
                        or tuple(map(int, match.groups())) != (start, end, total)
                        or len(response.content) != expected
                    ):
                        raise ValueError("Server returned an invalid PDF range")
                    return start, response.content
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == RANGE_ATTEMPTS:
                        raise
                    await asyncio.sleep(0.5 * attempt)
            raise AssertionError("unreachable")

        chunks = await asyncio.gather(*(fetch(start, end) for start, end in ranges))
        chunks.sort(key=lambda item: item[0])
        return b"".join(data for _, data in chunks)

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

    def _validate_url_security(self, url: str) -> list[str]:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            raise ValueError("Only HTTP and HTTPS URLs are supported")

        if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            raise ValueError("URL credentials and non-standard ports are not supported")
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
        addresses = self._resolve_addresses(hostname)
        if not addresses:
            raise ValueError("No public address found")
        for ip in addresses:
            self._assert_public_ip(ip)
        return addresses

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
            not ip.is_global
            or ip.is_private
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
                    return Path(name.replace("\\", "/")).name

        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path:
            last_segment = path.split("/")[-1]
            if last_segment:
                return last_segment if "." in last_segment else f"{last_segment}.pdf"

        return "downloaded_paper.pdf"
