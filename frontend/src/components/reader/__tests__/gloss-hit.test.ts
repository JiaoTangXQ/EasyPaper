import { describe, expect, it } from "vitest";
import type { PdfPageGeometry } from "@embedpdf/models";
import { glossCardPosition, glyphIndexAt, spanAtChar, type GlossSpan } from "../gloss-hit";
import { textAnchorCharRange, type TextPage } from "../text-anchor";

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
  return { geometry: { runs } as PdfPageGeometry, characters };
}

const pattern: GlossSpan = {
  id: "pattern",
  page: 0,
  text: "by a large margin",
  category: "idiom",
  label: "俚语",
  zh: "以很大的幅度",
  role: "说明领先的程度",
  anchor: { text: "by a large margin", prefix: "outperforms the baseline ", suffix: "." },
};

describe("click gloss", () => {
  it("returns the prepared phrase when the click lands inside one of its words", () => {
    const target = page(["outperforms the baseline by a large margin."]);
    const range = textAnchorCharRange(target, pattern.anchor);
    expect(range).not.toBeNull();
    const large = target.characters.find((char) => char.text === "l" && char.index > (range?.from ?? 0));
    expect(spanAtChar(target, [pattern], large!.index)?.id).toBe("pattern");
  });

  it("uses neighboring words to choose the second copy of a repeated phrase", () => {
    const target = page(["The model is fixed. The budget is fixed."]);
    const first: GlossSpan = {
      ...pattern,
      id: "first",
      text: "is fixed",
      anchor: { text: "is fixed", prefix: "themodel", suffix: ".thebudgetisfixed." },
    };
    const second: GlossSpan = {
      ...pattern,
      id: "second",
      text: "is fixed",
      anchor: { text: "is fixed", prefix: "themodelisfixed.thebudget", suffix: "." },
    };
    const text = target.characters.map((char) => char.text).join("");
    const firstIs = text.indexOf("is fixed");
    const secondIs = text.indexOf("is fixed", firstIs + 1);
    expect(spanAtChar(target, [first, second], target.characters[firstIs].index)?.id).toBe("first");
    expect(spanAtChar(target, [first, second], target.characters[secondIs].index)?.id).toBe("second");
  });

  it("hits the glyph under the pointer and places the card above it", () => {
    const target = page(["margin"]);
    expect(glyphIndexAt(target.geometry, { x: 73, y: 84 })).toBe(0);
    expect(glyphIndexAt(target.geometry, { x: 10, y: 10 })).toBe(-1);
    expect(
      glossCardPosition({ x: 200, y: 40 }, { width: 280, height: 90 }, { width: 800, height: 600 }).top,
    ).toBeGreaterThan(40);
  });
});
