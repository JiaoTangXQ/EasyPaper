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

/** Locate meaning-bearing text in this renderer's character stream. No source coordinates. */
export function textAnchorRects(page: TextPage, anchor: TextAnchor): Rect[] {
  let text = "";
  const indexes: number[] = [];
  for (const char of page.characters) {
    const value = normalize(char.text);
    text += value;
    for (let i = 0; i < value.length; i++) indexes.push(char.index);
  }
  const needle = normalize(anchor.text);
  if (!needle) return [];
  const prefix = normalize(anchor.prefix || "");
  const suffix = normalize(anchor.suffix || "");
  const matches: number[] = [];
  for (let start = text.indexOf(needle); start !== -1; start = text.indexOf(needle, start + 1)) {
    if (prefix && !text.slice(0, start).endsWith(prefix)) continue;
    if (suffix && !text.slice(start + needle.length).startsWith(suffix)) continue;
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
