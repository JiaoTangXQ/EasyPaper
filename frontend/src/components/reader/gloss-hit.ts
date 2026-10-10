import type { PdfPageGeometry, Rect } from "@embedpdf/models";
import { textAnchorCharRange, type TextAnchor, type TextPage } from "./text-anchor";

export type GlossSpan = {
  id: string;
  page: number;
  text: string;
  category: string;
  label: string;
  zh: string;
  en?: string;
  role?: string;
  anchor: TextAnchor;
};

export function glyphIndexAt(
  geometry: PdfPageGeometry,
  point: { x: number; y: number },
  toleranceFactor = 1.5,
): number {
  for (const run of geometry.runs) {
    const inside =
      point.y >= run.rect.y &&
      point.y <= run.rect.y + run.rect.height &&
      point.x >= run.rect.x &&
      point.x <= run.rect.x + run.rect.width;
    if (!inside) continue;
    const local = run.glyphs.findIndex((glyph) => {
      const x = glyph.tightX ?? glyph.x;
      const y = glyph.tightY ?? glyph.y;
      const width = glyph.tightWidth ?? glyph.width;
      const height = glyph.tightHeight ?? glyph.height;
      return point.x >= x && point.x <= x + width && point.y >= y && point.y <= y + height;
    });
    if (local !== -1) return run.charStart + local;
  }
  if (toleranceFactor <= 0) return -1;
  const heights = geometry.runs.flatMap((run) =>
    run.glyphs.filter((glyph) => glyph.flags !== 2).map((glyph) => glyph.height),
  );
  const tolerance = heights.length
    ? (heights.reduce((sum, height) => sum + height, 0) / heights.length) * toleranceFactor
    : 0;
  const pad = tolerance / 2;
  let best = -1;
  let bestDistance = Infinity;
  for (const run of geometry.runs) {
    for (let index = 0; index < run.glyphs.length; index++) {
      const glyph = run.glyphs[index];
      if (glyph.flags === 2) continue;
      const x = glyph.tightX ?? glyph.x;
      const y = glyph.tightY ?? glyph.y;
      const width = glyph.tightWidth ?? glyph.width;
      const height = glyph.tightHeight ?? glyph.height;
      if (point.x < x - pad || point.x > x + width + pad || point.y < y - pad || point.y > y + height + pad) continue;
      const distance =
        Math.min(Math.abs(point.x - x), Math.abs(point.x - (x + width))) +
        Math.min(Math.abs(point.y - y), Math.abs(point.y - (y + height)));
      if (distance < bestDistance) {
        bestDistance = distance;
        best = run.charStart + index;
      }
    }
  }
  return best;
}

/** The prepared block that owns this character. A phrase wins over a shorter accidental match. */
export function spanAtChar<T extends { anchor: TextAnchor }>(page: TextPage, spans: T[], charIndex: number): T | null {
  const hits = spans.filter((span) => {
    const range = textAnchorCharRange(page, span.anchor);
    return Boolean(range && charIndex >= range.from && charIndex <= range.to);
  });
  hits.sort((a, b) => b.anchor.text.length - a.anchor.text.length);
  return hits[0] ?? null;
}

export function glossCardPosition(
  point: { x: number; y: number },
  card: { width: number; height: number },
  frame: { width: number; height: number },
): { left: number; top: number } {
  const left = Math.min(Math.max(8, point.x - card.width / 2), Math.max(8, frame.width - card.width - 8));
  const above = point.y - card.height - 12;
  const top = above >= 8 ? above : Math.min(point.y + 18, Math.max(8, frame.height - card.height - 8));
  return { left, top };
}

export function glossClientRect(
  rect: Rect,
  visible: { viewportX: number; viewportY: number; pageX: number; pageY: number; scale: number },
  origin: { left: number; top: number },
) {
  return {
    left: origin.left + visible.viewportX + (rect.origin.x - visible.pageX) * visible.scale,
    top: origin.top + visible.viewportY + (rect.origin.y - visible.pageY) * visible.scale,
    width: rect.size.width * visible.scale,
    height: rect.size.height * visible.scale,
  };
}
