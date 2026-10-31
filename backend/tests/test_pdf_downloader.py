from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services import pdf_downloader as pdf_downloader_module
from app.services.pdf_downloader import PdfDownloader


def _patch_dns(monkeypatch, mapping: dict[str, str]) -> None:
    """Make socket.getaddrinfo return a deterministic IP per hostname."""

    def fake_getaddrinfo(host, *args, **kwargs):
        ip = mapping[host]
        return [(2, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(pdf_downloader_module.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.asyncio
async def test_blocks_host_resolving_to_loopback(monkeypatch) -> None:
    # A public-looking hostname that secretly resolves to loopback.
    _patch_dns(monkeypatch, {"evil.example.com": "127.0.0.1"})
    downloader = PdfDownloader()
    with pytest.raises(ValueError):
        await downloader.download("https://evil.example.com/paper.pdf")


@pytest.mark.asyncio
async def test_blocks_host_resolving_to_cloud_metadata(monkeypatch) -> None:
    _patch_dns(monkeypatch, {"meta.example.com": "169.254.169.254"})
    downloader = PdfDownloader()
    with pytest.raises(ValueError):
        await downloader.download("https://meta.example.com/paper.pdf")


@pytest.mark.asyncio
async def test_blocks_redirect_to_internal_host(monkeypatch) -> None:
    _patch_dns(monkeypatch, {"public.example.com": "93.184.216.34", "internal.example.com": "127.0.0.1"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "public.example.com":
            return httpx.Response(302, headers={"location": "https://internal.example.com/secret"})
        return httpx.Response(200, content=b"%PDF-1.4 leaked", headers={"content-type": "application/pdf"})

    downloader = PdfDownloader(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        await downloader.download("https://public.example.com/paper.pdf")


@pytest.mark.asyncio
async def test_allows_public_pdf(monkeypatch) -> None:
    _patch_dns(monkeypatch, {"arxiv.org": "151.101.3.42"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4 hello", headers={"content-type": "application/pdf"})

    downloader = PdfDownloader(transport=httpx.MockTransport(handler))
    result = await downloader.download("https://arxiv.org/pdf/1234.5678.pdf")
    assert result.file_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_pins_validated_ip_and_preserves_host_and_tls_name(monkeypatch):
    _patch_dns(monkeypatch, {"public.example.com": "93.184.216.34"})

    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "public.example.com"
        assert request.extensions["sni_hostname"] == "public.example.com"
        return httpx.Response(200, content=b"%PDF-1.4 test", headers={"content-type": "application/pdf"})

    result = await PdfDownloader(transport=httpx.MockTransport(handler)).download("https://public.example.com/file.pdf")
    assert result.filename == "file.pdf"


@pytest.mark.asyncio
async def test_stops_stream_at_limit_without_trusting_content_length(monkeypatch):
    _patch_dns(monkeypatch, {"public.example.com": "93.184.216.34"})
    reads = []

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(100):
                reads.append(i)
                yield (b"%PDF-" if i == 0 else b"xxxxx") + b"x" * (65536 - 5)

    def handler(request):
        return httpx.Response(200, stream=Chunks(), headers={"content-type": "application/pdf"})

    downloader = PdfDownloader(max_download_mb=1, transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="too large"):
        await downloader.download("https://public.example.com/file.pdf")
    assert len(reads) <= 18  # Reject before receiving the remaining 6 MB.


@pytest.mark.asyncio
async def test_slow_public_download_uses_configured_timeout(monkeypatch):
    _patch_dns(monkeypatch, {"public.example.com": "93.184.216.34"})

    class SlowPdf(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.02)
            yield b"%PDF-1.4 slow"

    def handler(request):
        return httpx.Response(200, stream=SlowPdf(), headers={"content-type": "application/pdf"})

    with pytest.raises(TimeoutError):
        await PdfDownloader(timeout_seconds=0.001, transport=httpx.MockTransport(handler)).download(
            "https://public.example.com/file.pdf"
        )
    result = await PdfDownloader(timeout_seconds=0.2, transport=httpx.MockTransport(handler)).download(
        "https://public.example.com/file.pdf"
    )
    assert result.file_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_assembles_public_ranged_download(monkeypatch):
    _patch_dns(monkeypatch, {"public.example.com": "93.184.216.34"})
    source = b"%PDF-1.4 " + b"x" * (4 * 1024 * 1024 + 17)

    def handler(request):
        start, end = (int(part) for part in request.headers["range"].removeprefix("bytes=").split("-"))
        return httpx.Response(
            206,
            content=source[start : end + 1],
            headers={
                "content-type": "application/pdf",
                "content-range": f"bytes {start}-{end}/{len(source)}",
            },
        )

    result = await PdfDownloader(max_download_mb=10, transport=httpx.MockTransport(handler)).download(
        "https://public.example.com/file.pdf"
    )
    assert result.file_bytes == source


@pytest.mark.asyncio
async def test_retries_transient_range_network_errors(monkeypatch):
    _patch_dns(monkeypatch, {"public.example.com": "93.184.216.34"})
    source = b"%PDF-1.4 " + b"x" * (4 * 1024 * 1024 + 17)
    attempts = {}

    def handler(request):
        start, end = (int(part) for part in request.headers["range"].removeprefix("bytes=").split("-"))
        attempts[start] = attempts.get(start, 0) + 1
        if attempts[start] == 1 and start:
            raise httpx.ReadTimeout("temporary CDN stall", request=request)
        return httpx.Response(
            206,
            content=source[start : end + 1],
            headers={"content-type": "application/pdf", "content-range": f"bytes {start}-{end}/{len(source)}"},
        )

    result = await PdfDownloader(max_download_mb=10, transport=httpx.MockTransport(handler)).download(
        "https://public.example.com/file.pdf"
    )
    assert result.file_bytes == source
    assert attempts[4 * 1024 * 1024] == 2


def test_download_proxy_can_be_configured(monkeypatch):
    monkeypatch.setenv("EASYPAPER_DOWNLOAD_PROXY", "http://172.18.0.1:7894")
    assert PdfDownloader().proxy == "http://172.18.0.1:7894"
    assert PdfDownloader(proxy="http://proxy.example:8080").proxy == "http://proxy.example:8080"


@pytest.mark.parametrize(
    "url",
    ["http://100.100.100.200/", "http://100.64.0.1/", "http://example.com:8000/", "http://user:pass@example.com/"],
)
def test_blocks_cloud_shared_address_space_and_credentials(url):
    with pytest.raises(ValueError):
        PdfDownloader()._validate_url_security(url)
