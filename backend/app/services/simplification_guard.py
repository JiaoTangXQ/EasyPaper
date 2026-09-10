"""Reject malformed paragraph rewrites before they can overflow the PDF layout."""

from __future__ import annotations

import re
from collections import Counter


def keep_source_label(source: str) -> bool:
    text = re.sub(r"\{+v\d+\}+", "", source).strip()
    return not text or (len(text.split()) <= 14 and len(text) < 160 and not re.search(r"[.!?]\s|[.!?]$", text))


def guarded_simplification(source: str, rewritten: str) -> str:
    if keep_source_label(source):
        return source
    if not rewritten.strip() or len(rewritten) > max(len(source) * 1.65, len(source) + 100):
        return source

    def placeholders(text):
        return Counter(re.findall(r"\{+v\d+\}+", text))

    def numbers(text):
        return Counter(re.findall(r"\d+(?:[.,]\d+)*", text))

    if placeholders(source) != placeholders(rewritten) or numbers(source) != numbers(rewritten):
        return source
    if re.match(r"(?i)(?:I'm ready|I am ready|Please provide|Sure[,!]|Here is|Here's)", rewritten.strip()):
        return source
    return rewritten
