"""Bounded page views of immutable PDF indexes; never retain whole decoded papers."""

import json
from collections import OrderedDict


class ReaderIndexCache:
    def __init__(self, max_pages=32, max_chars=120_000, max_versions=128):
        self.metadata = OrderedDict()
        self.pages = OrderedDict()
        self.max_pages, self.max_chars, self.max_versions = max_pages, max_chars, max_versions
        self.char_count = 0

    def _remember_metadata(self, version, index):
        self.metadata[version.id] = {
            "id": version.id,
            "kind": version.kind,
            "fingerprint": version.fingerprint,
            "page_count": len(index["pages"]),
            "pages": index["pages"],
            "origin_pages": index.get("origin_pages", []),
            "embedded_annotations": {a["data"]["id"]: a["annotation_id"] for a in index.get("ai_highlights", [])},
            "created_at": version.created_at.isoformat(),
            "url": f"/api/reader/documents/{version.document_id}/versions/{version.id}/pdf",
        }
        self.metadata.move_to_end(version.id)
        while len(self.metadata) > self.max_versions:
            self.metadata.popitem(last=False)

    def version(self, version):
        if version.id not in self.metadata:
            self._remember_metadata(version, json.loads(version.index_json))
        self.metadata.move_to_end(version.id)
        return self.metadata[version.id]

    def index(self, version, *, pages=None, origin_page=None):
        decoded = None
        if version.id not in self.metadata:
            decoded = json.loads(version.index_json)
            self._remember_metadata(version, decoded)
        meta = self.metadata[version.id]
        if pages is None:
            pages = (
                {i for i, origin in enumerate(meta["origin_pages"]) if origin == origin_page}
                if origin_page is not None
                else set()
            )
            if not pages:
                pages = set(range(meta["page_count"]))
        pages = sorted(pages)
        views = []
        for page in pages:
            key = (version.id, page)
            if key not in self.pages:
                if decoded is None:
                    decoded = json.loads(version.index_json)
                units = [u for u in decoded["units"] if u["page"] == page]
                figures = [f for f in decoded.get("figures", []) if f["page"] == page]
                count = sum(len(u["chars"]) for u in units)
                self.pages[key] = (units, figures, count)
                self.char_count += count
            units, figures, _ = self.pages[key]
            views.append((units, figures))
            self.pages.move_to_end(key)
            while len(self.pages) > self.max_pages or self.char_count > self.max_chars:
                _, (_, _, count) = self.pages.popitem(last=False)
                self.char_count -= count
        return {
            "pages": meta["pages"],
            "origin_pages": meta["origin_pages"],
            "units": [u for units, _ in views for u in units],
            "figures": [f for _, figures in views for f in figures],
        }
