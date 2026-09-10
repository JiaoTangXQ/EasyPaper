import { describe, expect, it } from "vitest";
import { textAnchorRects, type TextPage } from "../text-anchor";

function page(lines: string[]): TextPage {
  let index = 0;
  const characters: TextPage["characters"] = [];
  const runs = lines.map((text, row) => {
    const charStart = index;
    const glyphs = Array.from(text).map((c, col) => {
      characters.push({ index: index++, text: c });
      return { x: 70 + col * 6, y: 80 + row * 14, width: 6, height: 10, flags: c === " " ? 1 : 0 };
    });
    return { charStart, glyphs, fontSize: 10, rect: { x: 70, y: 80 + row * 14, width: text.length * 6, height: 10 } };
  });
  return { geometry: { runs }, characters };
}

describe("content anchored projections", () => {
  it("redraws the selected phrase using the target's changed line breaks and widths", () => {
    const target = page(["two parts: a model that", "understands and plans"]);
    const rects = textAnchorRects(target, { text: "a model that understands and plans" });
    expect(rects).toHaveLength(2);
    expect(rects[0].origin.x).toBe(136); // exclude 'two parts: '
    expect(rects[1].origin).toEqual({ x: 70, y: 94 });
    expect(rects.every((r) => r.size.height === 10)).toBe(true);
  });
  it("uses sentence context to distinguish repeated words without position hints", () => {
    const target = page(["the model is fixed. the budget is fixed."]);
    expect(textAnchorRects(target, { text: "is fixed" })).toEqual([]);
    const rects = textAnchorRects(target, { text: "is fixed", prefix: "the model ", suffix: ". the budget" });
    expect(rects[0].origin.x).toBe(130);
  });
  it("matches ligatures and line breaks without changing PDF character indexes", () => {
    const target = page(["The ﬁxed", "model"]);
    expect(textAnchorRects(target, { text: "fixed model" })).toHaveLength(2);
    expect(textAnchorRects(target, { text: "a different model" })).toEqual([]);
  });
  it("accepts typographic quotation marks without shifting the selected characters", () => {
    const target = page(["The model’s prior is broad but fixed."]);
    const rects = textAnchorRects(target, { text: "The model's prior is broad but" });
    expect(rects).toHaveLength(1);
    expect(rects[0].origin.x).toBe(70);
    expect(rects[0].size.width).toBe(30 * 6);
  });
});
