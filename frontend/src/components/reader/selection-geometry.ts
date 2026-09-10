import type { PdfPageGeometry } from "@embedpdf/models";

export function readerSelectionGeometry(geometry: PdfPageGeometry): PdfPageGeometry {
  const bands = geometry.runs.map((run) => {
    const size = run.fontSize || 0;
    const ink = run.glyphs.filter((g) => !(g.flags & 3) && (g.tightHeight || 0) >= size * 0.6);
    if (!size || !ink.length) return null;
    const top = Math.min(...ink.map((g) => g.tightY!));
    const bottom = Math.max(...ink.map((g) => g.tightY! + g.tightHeight!));
    // Leave vertical text and multiline runs to the engine's native geometry.
    if (bottom - top > size * 1.5 || run.rect.width < size) return null;
    return {
      center: (top + bottom) / 2,
      height: Math.max(bottom - top + 1, size * 1.1),
      size,
      left: run.rect.x,
      right: run.rect.x + run.rect.width,
    };
  });
  return {
    ...geometry,
    runs: geometry.runs.map((run, i) => {
      const size = run.fontSize || 0;
      const center = bands[i]?.center ?? run.rect.y + run.rect.height / 2;
      if (run.glyphs.some((g) => !(g.flags & 3) && g.tightY !== undefined && Math.abs(g.tightY - center) > size * 1.5))
        return run;
      const peers = bands.filter(
        (b) => b && Math.abs(b.center - center) < size * 0.35 && Math.abs(b.size - size) < size * 0.3,
      );
      if (!peers.length) return run;
      const centers = peers.map((b) => b!.center).sort((a, b) => a - b);
      const height = Math.max(...peers.map((b) => b!.height));
      const lineCenter = centers[Math.floor(centers.length / 2)];
      const y = lineCenter - height / 2;
      const neighbors = bands.filter((b) => b && b.right >= run.rect.x && b.left <= run.rect.x + run.rect.width);
      const above = neighbors
        .filter((b) => b!.center < lineCenter - size * 0.4)
        .map((b) => (lineCenter - b!.center) / 2);
      const below = neighbors
        .filter((b) => b!.center > lineCenter + size * 0.4)
        .map((b) => (b!.center - lineCenter) / 2);
      const hitY = lineCenter - Math.min(size * 0.8, ...above);
      const hitBottom = lineCenter + Math.min(size * 0.8, ...below);
      const hitHeight = hitBottom - hitY;
      return {
        ...run,
        rect: { ...run.rect, y: hitY, height: hitHeight },
        glyphs: run.glyphs.map((g) => ({
          ...g,
          y,
          height,
          // A line has one hit band; punctuation and short Latin letters don't
          // pull a near-line drag toward an adjacent baseline.
          tightX: g.x,
          tightWidth: g.width,
          // Hit bands reach the midpoint between lines. This keeps the exact
          // same endpoint character when the mouse moves vertically into the gap.
          tightY: hitY,
          tightHeight: hitHeight,
        })),
      };
    }),
  };
}
