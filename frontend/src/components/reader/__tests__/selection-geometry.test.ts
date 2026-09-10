import { describe, expect, it } from "vitest";
import type { PdfPageGeometry } from "@embedpdf/models";
import { glyphAt, rectsWithinSlice } from "@embedpdf/plugin-selection";
import { readerSelectionGeometry } from "../selection-geometry";

// PDFium metrics from a translated PDF: 10 pt glyphs have 28 pt font boxes,
// while neighboring baselines are only 14 pt apart.
const geometry: PdfPageGeometry = {
  runs: [0, 14].map((dy, row) => ({
    rect: { x: 87, y: 194 + dy, width: 30, height: 28 },
    charStart: 1438 + row * 3,
    fontSize: 9.9626,
    glyphs: [0, 10, 20].map((dx) => ({
      x: 87 + dx,
      y: 194 + dy,
      width: 10,
      height: 28,
      flags: 0,
      tightX: 88 + dx,
      tightY: 203 + dy,
      tightWidth: 9,
      tightHeight: 10,
    })),
  })),
};

describe("reader text selection geometry", () => {
  it("keeps highlight bands on their own line and preserves PDF character indexes", () => {
    const result = readerSelectionGeometry(geometry);
    const first = result.runs[0].glyphs[0];
    const second = result.runs[1].glyphs[0];
    expect(first.height).toBeLessThan(14);
    expect(first.y + first.height).toBeLessThan(second.y);
    expect(result.runs.map((r) => r.charStart)).toEqual([1438, 1441]);
    expect(geometry.runs[0].glyphs[0].height).toBe(28);
    const selected = rectsWithinSlice(result, 1438, 1440);
    expect(selected).toHaveLength(1);
    expect(selected[0].size.height).toBeLessThan(14);
  });
  it("uses the whole line band for hit testing, including above small punctuation", () => {
    const withPunctuation = structuredClone(geometry);
    Object.assign(withPunctuation.runs[0].glyphs[1], { tightY: 210, tightHeight: 3 });
    const result = readerSelectionGeometry(withPunctuation).runs[0];
    expect(result.glyphs[1].tightY).toBe(result.rect.y);
    expect(result.glyphs[1].tightHeight).toBe(result.rect.height);
    expect(result.glyphs[1].height).toBeLessThan(14);
  });
  it("keeps the same character hit for a pointer six points above or below the line", () => {
    const result = readerSelectionGeometry(geometry);
    expect([-6, 0, 6].map((dy) => glyphAt(result, { x: 100, y: 208 + dy }))).toEqual([1439, 1439, 1439]);
  });
});
