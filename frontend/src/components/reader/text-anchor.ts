import type { PdfPageGeometry, Rect } from "@embedpdf/models";
import { rectsWithinSlice } from "@embedpdf/plugin-selection";

export type TextAnchor = { text: string; prefix?: string; suffix?: string };
export type TextPage = { geometry: PdfPageGeometry; characters: { index: number; text: string }[] };
type CharRange = { from: number; to: number };
type PreparedTextPage = { text: string; indexes: number[]; glyphs: Map<number, PdfPageGeometry["runs"][number]["glyphs"][number]> };

// A page is shared by every hit test and highlight on that page. Keep the
// normalized character stream and glyph lookup alongside it so locating the
// next term does not rebuild the same data for every candidate span.
const preparedPages = new WeakMap<TextPage, PreparedTextPage>();
const anchorRanges = new WeakMap<TextPage, WeakMap<TextAnchor, CharRange | null>>();
const normalize = (text: string) =>
  text
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[‘’]/gu, "'")
    .replace(/[“”]/gu, '"')
    .replace(/[\s\u00ad\u200b]/gu, "");

function matchesAnchorText(actual: string, expected: string): boolean {
  if (actual.length !== expected.length) return false;
  for (let i = 0; i < expected.length; i++) {
    // MuPDF can expose an undecoded formatting glyph as NUL while PDFium
    // decodes that same glyph. Consume exactly one known formatting mark;
    // never accept an arbitrary letter, digit, operator, or missing text.
    if (expected[i] === "\u0000" ? !"`-#".includes(actual[i]) : actual[i] !== expected[i]) return false;
  }
  return true;
}

type LocatedAnchor = { indexes: number[]; start: number; needle: string };

function prepareTextPage(page: TextPage): PreparedTextPage {
  const cached = preparedPages.get(page);
  if (cached) return cached;
  let text = "";
  const indexes: number[] = [];
  const glyphs = new Map(
    page.geometry.runs.flatMap((run) => run.glyphs.map((glyph, i) => [run.charStart + i, glyph] as const)),
  );
  for (const [i, char] of page.characters.entries()) {
    let value = normalize(char.text);
    // PDFium returns an empty slice for some painted end-of-line hyphens.
    // Restore only that glyph, where a word continues on the following line.
    // An absent glyph or ordinary whitespace is never treated as punctuation.
    if (!char.text) {
      const glyph = glyphs.get(char.index);
      const next = glyphs.get(page.characters[i + 1]?.index);
      if (
        glyph &&
        next &&
        glyph.width > 0 &&
        next.y > glyph.y + glyph.height / 2 &&
        next.x < glyph.x &&
        /[a-z]$/iu.test(page.characters[i - 1]?.text || "") &&
        /^[a-z]/iu.test(page.characters[i + 1]?.text || "")
      ) {
        value = "-";
      }
    }
    text += value;
    for (let offset = 0; offset < value.length; offset++) indexes.push(char.index);
  }
  const prepared = { text, indexes, glyphs };
  preparedPages.set(page, prepared);
  return prepared;
}

function locateAnchor(page: TextPage, anchor: TextAnchor): LocatedAnchor | null {
  const { text, indexes } = prepareTextPage(page);
  const needle = normalize(anchor.text);
  if (!needle) return null;
  const literal = needle.split("\u0000").reduce((longest, part) => (part.length > longest.length ? part : longest), "");
  if (!literal || (needle.includes("\u0000") && !/[\p{L}\p{N}]/u.test(literal))) return null;
  const literalOffset = needle.indexOf(literal);
  const prefix = normalize(anchor.prefix || "");
  const suffix = normalize(anchor.suffix || "");
  const matches: number[] = [];
  for (let found = text.indexOf(literal); found !== -1; found = text.indexOf(literal, found + 1)) {
    const start = found - literalOffset;
    if (start < 0 || !matchesAnchorText(text.slice(start, start + needle.length), needle)) continue;
    if (prefix && !matchesAnchorText(text.slice(Math.max(0, start - prefix.length), start), prefix)) continue;
    const end = start + needle.length;
    if (suffix && !matchesAnchorText(text.slice(end, end + suffix.length), suffix)) continue;
    matches.push(start);
  }
  // Repeated phrases without matching context must not land on an arbitrary occurrence.
  if (matches.length !== 1) return null;
  return { indexes, start: matches[0], needle };
}

/** Inclusive PDF character indexes covered by one prepared span. */
export function textAnchorCharRange(page: TextPage, anchor: TextAnchor): { from: number; to: number } | null {
  let cache = anchorRanges.get(page);
  if (!cache) {
    cache = new WeakMap<TextAnchor, CharRange | null>();
    anchorRanges.set(page, cache);
  }
  if (cache.has(anchor)) return cache.get(anchor) || null;
  const located = locateAnchor(page, anchor);
  if (!located) {
    cache.set(anchor, null);
    return null;
  }
  const end = located.start + located.needle.length - 1;
  const range = { from: located.indexes[located.start], to: located.indexes[end] };
  cache.set(anchor, range);
  return range;
}

/** Locate meaning-bearing text in this renderer's character stream. No source coordinates. */
export function textAnchorRects(page: TextPage, anchor: TextAnchor): Rect[] {
  const range = textAnchorCharRange(page, anchor);
  if (!range) return [];
  return rectsWithinSlice(page.geometry, range.from, range.to);
}

export function textRectsBounds(rects: Rect[]): Rect {
  const x = Math.min(...rects.map((r) => r.origin.x));
  const y = Math.min(...rects.map((r) => r.origin.y));
  return {
    origin: { x, y },
    size: {
      width: Math.max(...rects.map((r) => r.origin.x + r.size.width)) - x,
      height: Math.max(...rects.map((r) => r.origin.y + r.size.height)) - y,
    },
  };
}
