"""Lightweight metadata for document lists; never parse the full paper or call a model."""

from functools import lru_cache
from pathlib import Path

import fitz


@lru_cache(maxsize=512)
def _cached_title(path: str, modified_ns: int, size: int) -> str | None:
    # The file signature invalidates cached metadata when the source changes.
    try:
        with fitz.open(path) as pdf:
            title = " ".join(((pdf.metadata or {}).get("title") or "").split())
            return title if title and title.lower() not in {"untitled", "untitled document"} else None
    except (OSError, RuntimeError, ValueError):
        # Optional metadata must not prevent reading the rest of the library.
        return None


def pdf_title(path: str | None) -> str | None:
    if not path:
        return None
    try:
        source = Path(path).resolve()
        stat = source.stat()
        return _cached_title(str(source), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None
