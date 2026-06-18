import { describe, it, expect } from "vitest";

import { clientToGraphPoint } from "../graph";

const CANVAS = { width: 1200, height: 800 };

describe("clientToGraphPoint", () => {
    it("maps a click to graph space when the canvas is stretched by CSS", () => {
        // Canvas rendered at half its internal resolution (600x400).
        const rect = { left: 0, top: 0, width: 600, height: 400 };
        // Click at the visual centre.
        const point = clientToGraphPoint({ x: 300, y: 200 }, rect, CANVAS, { x: 0, y: 0 }, 1);
        // Must land at the centre of the 1200x800 logical space, not (300,200).
        expect(point).toEqual({ x: 600, y: 400 });
    });

    it("accounts for the canvas offset within the viewport", () => {
        const rect = { left: 100, top: 50, width: 1200, height: 800 };
        const point = clientToGraphPoint({ x: 100, y: 50 }, rect, CANVAS, { x: 0, y: 0 }, 1);
        expect(point).toEqual({ x: 0, y: 0 });
    });

    it("inverts pan offset and zoom", () => {
        const rect = { left: 0, top: 0, width: 1200, height: 800 };
        const point = clientToGraphPoint({ x: 200, y: 200 }, rect, CANVAS, { x: 100, y: 100 }, 2);
        // (200 - 100) / 2 = 50
        expect(point).toEqual({ x: 50, y: 50 });
    });
});
