from __future__ import annotations

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
        if request.url.host == "public.example.com":
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
