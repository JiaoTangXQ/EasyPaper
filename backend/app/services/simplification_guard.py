"""Preserve incomplete PDF sentences and reject malformed paragraph rewrites."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable

_ABBREVIATIONS = frozenset(
    "al approx cf dr eg eq eqs et etc fig figs ie mr mrs ms no nos pp prof ref refs resp sec secs tab tabs viz vol vs".split()
)


def _sentence_ends(text: str) -> list[int]:
    """Conservative prose boundaries, excluding citations, decimals and initials."""
    ends = []
    for match in re.finditer(r"""[.!?:]["'”’]*(?=\s|$)""", text):
        offset = match.start()
        before = text[:offset]
        # A citation or parenthetical may itself contain punctuation. Never
        # separate it from the sentence that owns it.
        if before.count("(") > before.count(")") or before.count("[") > before.count("]"):
            continue
        if text[offset] == ".":
            token_match = re.search(r"[A-Za-z.]+$", before)
            token = token_match.group() if token_match else ""
            if token.lower() in _ABBREVIATIONS or "." in token or (len(token) == 1 and token.isalpha()):
                continue
        # Leave whitespace attached to the protected fragments when rebuilding.
        ends.append(match.end())
    return ends


def simplification_parts(source: str) -> tuple[str, str, str]:
    """Return untouched prefix, complete prose, untouched suffix.

    pdf2zh supplies page-local blocks, not logical paragraphs. A lowercase,
    formula-led or numeric-led opening is ambiguous without the preceding block;
    an unterminated ending may continue on the next page. Preserve those pieces
    verbatim instead of asking the model to invent their missing context.
    """
    ends = _sentence_ends(source)
    if not ends:
        return source, "", ""
    start = len(source) - len(source.lstrip())
    end = ends[-1]
    for boundary in ends:
        opening = source[start:].lstrip('"“‘')
        if opening and opening[0].isupper():
            break
        start = boundary
        while start < len(source) and source[start].isspace():
            start += 1
    if start >= end:
        return source, "", ""
    return source[:start], source[start:end], source[end:]


def simplify_preserving_fragments(source: str, rewrite: Callable[[str], str]) -> str:
    if keep_source_label(source):
        return source
    prefix, complete, suffix = simplification_parts(source)
    if not complete or keep_source_label(complete):
        return source
    rewritten = guarded_simplification(complete, rewrite(complete))
    return guarded_simplification(source, prefix + rewritten + suffix)


def keep_source_label(source: str) -> bool:
    text = re.sub(r"\{+v\d+\}+", "", source).strip()
    return not text or (len(text.split()) <= 14 and len(text) < 160 and not re.search(r"[.!?]\s|[.!?]$", text))


def guarded_simplification(source: str, rewritten: str) -> str:
    if keep_source_label(source):
        return source
    if not rewritten.strip() or len(rewritten) > max(len(source) * 1.65, len(source) + 100):
        return source

    prefix, complete, suffix = simplification_parts(source)
    if not complete or not rewritten.startswith(prefix) or not rewritten.endswith(suffix):
        return source
    rewritten_complete = rewritten[len(prefix) : len(rewritten) - len(suffix) if suffix else None]
    ends = _sentence_ends(rewritten_complete)
    if not ends or ends[-1] != len(rewritten_complete.rstrip()):
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
