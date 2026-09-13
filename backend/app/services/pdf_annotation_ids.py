"""Adapt page-local PDF annotation names to the reader's document-wide IDs."""

from __future__ import annotations

import fitz


def unique_annotation_ids(data: bytes) -> bytes:
    """Rename collisions only, preserving geometry, appearances and other metadata.

    PyMuPDF emits fitz-A0, fitz-A1, ... independently on every page. EmbedPDF
    indexes annotations by /NM across the entire document, so repeated names
    cause later pages to replace earlier pages' text and positions in the viewer.
    """
    with fitz.open(stream=data, filetype="pdf") as doc:
        annotations = [(page.number, xref, name) for page in doc for xref, _kind, name in page.annot_xrefs() if name]
        reserved = {name for _, _, name in annotations}
        if len(reserved) == len(annotations):
            return data
        seen: set[str] = set()
        for page, xref, name in annotations:
            if name not in seen:
                seen.add(name)
                continue
            replacement = f"easypaper-p{page}-x{xref}"
            while replacement in reserved:
                replacement += "-1"
            reserved.add(replacement)
            doc.xref_set_key(xref, "NM", fitz.get_pdf_str(replacement))
        # Reopening the same legacy file must not create a new revision each time.
        return doc.tobytes(no_new_id=True)
