"""Finished pages of a version that is still being generated.

pdf2zh writes the translated PDF only after its last page, and a 27-page paper
takes 10–40 minutes on the production server. Each page is rendered to JPEG as
soon as pdf2zh finishes it, so the reader can read along while the rest is
translated. The files are temporary: they are removed once the complete version
is published, when the build fails, or when a restart interrupts it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from pathlib import Path

import fitz

from .reader_preview import JPEG_QUALITY, PREVIEW_WIDTHS, preview_width

logger = logging.getLogger(__name__)

# Only translation renders page by page. Simplification rewrites sentences that
# cross pages, so pdf2zh finishes all of its pages together at the end.
PARTIAL_KINDS = frozenset({"chinese"})


class PartialPages:
    """Temporary page images for one build, in `<document folder>/partial/<kind>/`."""

    def __init__(self, folder: Path, kind: str):
        self.root = Path(folder) / "partial" / kind
        self._manifest = self.root / "manifest.json"

    def reset(self, total: int) -> None:
        self.clear()
        self.root.mkdir(parents=True, exist_ok=True)
        self._write(self._manifest, json.dumps({"total": total, "done": []}).encode())

    def publish(self, page_index: int, images: dict[int, bytes]) -> None:
        state = self.state()
        if state is None:
            return
        for width, data in images.items():
            self._write(self.image_path(page_index, width), data)
        # The manifest is written last, so a listed page always has its images.
        done = sorted({*state["done"], page_index})
        self._write(self._manifest, json.dumps({"total": state["total"], "done": done}).encode())

    def state(self) -> dict | None:
        try:
            data = json.loads(self._manifest.read_bytes())
            total = int(data["total"])
            done = sorted({int(page) for page in data["done"] if 0 <= int(page) < total})
        except (OSError, ValueError, TypeError, KeyError):
            return None
        return {"total": total, "done": done}

    def image_path(self, page_index: int, width: int) -> Path:
        return self.root / f"p{page_index}-w{width}.jpg"

    def image(self, page_index: int, requested_width: int) -> bytes | None:
        state = self.state()
        if not state or page_index not in state["done"]:
            return None
        try:
            return self.image_path(page_index, preview_width(requested_width)).read_bytes()
        except OSError:
            return None

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _write(target: Path, data: bytes) -> None:
        tmp = target.with_name(f".{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)


class PartialPagePublisher:
    """Receives pdf2zh's content patch for each finished page and publishes its image.

    pdf2zh keeps every patch in memory and applies them to its own document only
    after the last page. Applying them early to that document would change what
    its layout model sees on later pages (a form XObject shared between pages
    would already be translated), so the patches go to a separate copy that is
    only ever rendered here. Rendering problems stop early pages, never the
    translation itself.
    """

    def __init__(self, store: PartialPages):
        self.store = store
        self._doc: fitz.Document | None = None
        self._applied: dict[int, str] = {}
        # pdf2zh's new page streams and the page streams they replace are not
        # objects of the copy; only shared XObject patches are applied by number.
        self._page_objects: set[int] = set()

    def begin(self, pdf_bytes: bytes, total: int) -> None:
        self.close()
        self._applied.clear()
        self._page_objects.clear()
        try:
            self.store.reset(total)
            self._doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            logger.warning("Early translated pages are unavailable for this build", exc_info=True)
            self.close()

    def page_done(self, page_index: int, page_xref: int, content_ids: list[int], patches: dict[int, str]) -> None:
        if self._doc is None:
            return
        try:
            self.store.publish(page_index, self._render(page_index, page_xref, content_ids, patches))
        except Exception:
            logger.warning("Stopped publishing early translated pages", exc_info=True)
            self.close()

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    def _render(self, page_index, page_xref, content_ids, patches) -> dict[int, bytes]:
        doc = self._doc
        self._page_objects.add(page_xref)
        self._page_objects.update(content_ids)
        for xref, ops in list(patches.items()):
            if xref in self._page_objects or self._applied.get(xref) == ops:
                continue
            doc.update_stream(xref, ops.encode())
            self._applied[xref] = ops
        # Mirror pdf2zh: the page gets a fresh content stream holding the patch.
        contents = doc.get_new_xref()
        doc.update_object(contents, "<<>>")
        doc.update_stream(contents, patches[page_xref].encode())
        page = doc[page_index]
        page.set_contents(contents)
        images = {}
        for width in PREVIEW_WIDTHS:
            zoom = width / max(page.rect.width, 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, annots=True)
            images[width] = pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
        return images
