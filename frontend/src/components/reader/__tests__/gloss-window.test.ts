import { describe, expect, it } from "vitest";
import { glossWindow } from "../useGlossSpans";

describe("gloss window", () => {
  it("fetches the visible page, one before it and three after it", () => {
    expect(glossWindow(1, 27)).toEqual([0, 1, 2, 3]);
    expect(glossWindow(2, 27)).toEqual([0, 1, 2, 3, 4]);
    expect(glossWindow(10, 27)).toEqual([8, 9, 10, 11, 12]);
  });

  it("never asks for pages outside the document", () => {
    expect(glossWindow(27, 27)).toEqual([25, 26]);
    expect(glossWindow(99, 3)).toEqual([1, 2]);
    expect(glossWindow(0, 2)).toEqual([0, 1]);
  });
});
