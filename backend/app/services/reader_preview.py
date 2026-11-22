"""Single-page JPEG previews, so a reader can see a page before the whole PDF arrives.

The browser viewer needs the complete file before it can render anything, and
papers with figures are often 10–30 MB. A preview is one page, ~100–300 KB, and
is cached on disk beside the immutable (content-addressed) version file.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections import defaultdict
from pathlib import Path

import fitz

# A few fixed widths bound the cache to three files per page at most.
PREVIEW_WIDTHS = (800, 1200, 1600)
JPEG_QUALITY = 80


def preview_width(requested: int) -> int:
    return min(PREVIEW_WIDTHS, key=lambda width: (abs(width - requested), width))


def _render(pdf_path: str, page_index: int, width: int) -> bytes:
    with fitz.open(pdf_path) as pdf:
        if not 0 <= page_index < pdf.page_count:
            raise IndexError(page_index)
        page = pdf[page_index]
        zoom = width / max(page.rect.width, 1)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, annots=True)
        return pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)


class PagePreviews:
    def __init__(self, max_concurrent: int = 2):
        # Rendering is CPU work on a small server; never let previews starve requests.
        self._slots = asyncio.Semaphore(max_concurrent)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def cache_path(self, pdf_path: str, fingerprint: str, page_index: int, width: int) -> Path:
        return Path(pdf_path).parent / "previews" / f"{fingerprint}-p{page_index}-w{width}.jpg"

    async def get(self, pdf_path: str, fingerprint: str, page_index: int, requested_width: int) -> bytes:
        """Return a JPEG for one page. Raises IndexError for a page outside the document."""
        width = preview_width(requested_width)
        target = self.cache_path(pdf_path, fingerprint, page_index, width)
        if target.is_file():
            return await asyncio.to_thread(target.read_bytes)
        key = str(target)
        async with self._locks[key]:
            if target.is_file():
                return await asyncio.to_thread(target.read_bytes)
            async with self._slots:
                data = await asyncio.to_thread(_render, pdf_path, page_index, width)
            await asyncio.to_thread(self._store, target, data)
        self._locks.pop(key, None)
        return data

    @staticmethod
    def _store(target: Path, data: bytes) -> None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{uuid.uuid4().hex}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
        except OSError:
            # The preview is still returned; only the disk cache is skipped.
            pass
