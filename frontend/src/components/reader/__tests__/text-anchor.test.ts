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
  it("retains a visible line-end hyphen whose PDFium text slice is empty", () => {
    const target = page(["connects from-", "scratch creation"]);
    target.characters[13].text = "";
    const rects = textAnchorRects(target, { text: "from-scratch" });
    expect(rects).toHaveLength(2);
    expect(rects[0].origin.x).toBe(124);
    expect(rects[1].size.width).toBe(7 * 6);
    // Never discard punctuation indiscriminately to make a quotation fit.
    expect(textAnchorRects(page(["connects from scratch"]), { text: "from-scratch" })).toEqual([]);
  });
  it("distinguishes repeated headings with surrounding paragraph context", () => {
    const target = page([
      "First trial. Observation and analysis.",
      "Scores decreased. Second trial. Observation and analysis.",
      "Scores improved.",
    ]);
    const rects = textAnchorRects(target, {
      text: "Observation and analysis.",
      prefix: "Second trial.",
      suffix: "Scores improved.",
    });
    expect(rects).toHaveLength(1);
    expect(rects[0].origin.y).toBe(94);
  });
  it("resolves undecoded PDF formatting glyphs in quotations and surrounding context", () => {
    const target = page(["Required behavior. ```bash`", "```python -m harness", "-- Next item."]);
    const rects = textAnchorRects(target, {
      text: "```bash\u0000```python -m harness",
      prefix: "Required behavior.",
      suffix: "\u0000- Next item.",
    });
    expect(rects).toHaveLength(2);
    expect(rects[0].origin.x).toBe(184);
    expect(rects[1].size.width).toBe(20 * 6);
    expect(textAnchorRects(target, {
      text: "Required behavior.", suffix: "```bash\u0000```python",
    })).toHaveLength(1);
    expect(textAnchorRects(page(["#### Tools (JSON output) --- next item."]), {
      text: "JSON output) \u0000\u0000- next item.", prefix: "\u0000\u0000## Tools (",
    })).toHaveLength(1);
  });
  it("never treats an unknown glyph as arbitrary content or chooses an ambiguous occurrence", () => {
    expect(textAnchorRects(page(["score 19"]), { text: "score 1\u0000" })).toEqual([]);
    expect(textAnchorRects(page(["not possible"]), { text: "\u0000ot possible" })).toEqual([]);
    expect(textAnchorRects(page(["a+b"]), { text: "a\u0000b" })).toEqual([]);
    expect(textAnchorRects(page(["-- next. `- next."]), { text: "\u0000- next." })).toEqual([]);
    expect(textAnchorRects(page(["`"]), { text: "\u0000" })).toEqual([]);
  });
});
