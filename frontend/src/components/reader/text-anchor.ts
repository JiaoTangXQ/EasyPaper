import type { PdfPageGeometry, Rect } from "@embedpdf/models";
import { rectsWithinSlice } from "@embedpdf/plugin-selection";

export type TextAnchor = { text: string; prefix?: string; suffix?: string };
export type TextPage = { geometry: PdfPageGeometry; characters: { index: number; text: string }[] };
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

/** Locate meaning-bearing text in this renderer's character stream. No source coordinates. */
export function textAnchorRects(page: TextPage, anchor: TextAnchor): Rect[] {
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
    for (let i = 0; i < value.length; i++) indexes.push(char.index);
  }
  const needle = normalize(anchor.text);
  if (!needle) return [];
  const literal = needle.split("\u0000").reduce((longest, part) => (part.length > longest.length ? part : longest), "");
  if (!literal || (needle.includes("\u0000") && !/[\p{L}\p{N}]/u.test(literal))) return [];
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
  if (matches.length !== 1) return [];
  const start = matches[0];
  return rectsWithinSlice(page.geometry, indexes[start], indexes[start + needle.length - 1]);
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
