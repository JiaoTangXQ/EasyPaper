import { useEffect, useRef, useState } from "react";
import { DocumentManagerPlugin, ScrollPlugin, type PluginRegistry } from "@embedpdf/react-pdf-viewer";
import { glossCardPosition, glossClientRect, glyphIndexAt, spanAtChar, type GlossSpan } from "./gloss-hit";
import { textAnchorRects, type TextPage } from "./text-anchor";

type Box = { left: number; top: number; width: number; height: number };
type Point = { x: number; y: number };
type Place = { span: GlossSpan; pagePoint: Point; client: Point };

export default function GlossLayer({
  registry,
  container,
  spans,
}: {
  registry: PluginRegistry;
  container: HTMLElement | null;
  spans: GlossSpan[];
}) {
  const spansRef = useRef(spans);
  spansRef.current = spans;
  const pages = useRef(new Map<number, Promise<TextPage>>());
  const placeRef = useRef<Place | null>(null);
  const [place, setPlace] = useState<Place | null>(null);
  const [cardPoint, setCardPoint] = useState<Point | null>(null);
  const [marks, setMarks] = useState<Box[]>([]);
  const [cardBox, setCardBox] = useState({ width: 300, height: 120 });
  const cardRef = useRef<HTMLElement>(null);
  placeRef.current = place;

  useEffect(() => {
    setPlace(null);
    setCardPoint(null);
    setMarks([]);
  }, [spans]);

  useEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    const box = card.getBoundingClientRect();
    if (box.width && box.height) setCardBox({ width: box.width, height: box.height });
  }, [place]);

  useEffect(() => {
    const documents = registry.getPlugin<DocumentManagerPlugin>("document-manager")?.provides?.();
    if (!documents) return;
    const interaction = registry.getPlugin("interaction-manager")?.provides?.() as
      | {
          registerAlways(options: {
            scope: { type: "page"; documentId: string; pageIndex: number };
            handlers: {
              onPointerDown?: (point: { x: number; y: number }) => void;
              onPointerUp?: (point: { x: number; y: number }, event: { clientX: number; clientY: number }) => void;
            };
          }): () => void;
        }
      | undefined;
    if (!interaction) return;
    let remove: Array<() => void> = [];

    const bind = () => {
      remove.forEach((fn) => fn());
      remove = [];
      const documentId = documents.getActiveDocumentId();
      const pdf = documentId ? documents.getDocumentState(documentId)?.document : undefined;
      if (!documentId || !pdf) return;
      pdf.pages.forEach((_page, pageIndex) => {
        let down: { x: number; y: number } | null = null;
        remove.push(
          interaction.registerAlways({
            scope: { type: "page", documentId, pageIndex },
            handlers: {
              onPointerDown(point) {
                down = point;
              },
              onPointerUp(point, event) {
                if (!down || Math.hypot(point.x - down.x, point.y - down.y) > 4) {
                  down = null;
                  return;
                }
                down = null;
                void openAt(pdf, pageIndex, point, { x: event.clientX, y: event.clientY });
              },
            },
          }),
        );
      });
    };

    const openAt = async (
      pdf: { pages: unknown[] },
      pageIndex: number,
      point: { x: number; y: number },
      client: { x: number; y: number },
    ) => {
      const page = await textPage(pdf, pageIndex);
      const glyph = glyphIndexAt(page.geometry, point);
      const span =
        glyph < 0
          ? null
          : spanAtChar(
              page,
              spansRef.current.filter((item) => item.page === pageIndex),
              glyph,
            );
      if (!span) {
        setPlace(null);
        setCardPoint(null);
        setMarks([]);
        return;
      }
      const next = { span, pagePoint: point, client };
      placeRef.current = next;
      setPlace(next);
      setCardPoint(client);
      await paint(pdf, span);
    };

    const textPage = (pdf: { pages: unknown[] }, pageIndex: number) => {
      let cached = pages.current.get(pageIndex);
      if (!cached) {
        cached = loadTextPage(registry, pdf, pageIndex);
        pages.current.set(pageIndex, cached);
        cached.catch(() => pages.current.delete(pageIndex));
      }
      return cached;
    };

    const paint = async (pdf: { pages: unknown[] }, span: GlossSpan) => {
      const page = await textPage(pdf, span.page);
      const rects = textAnchorRects(page, span.anchor);
      const scroll = registry.getPlugin<ScrollPlugin>("scroll")?.provides?.();
      const metrics = scroll?.getMetrics();
      const visible = metrics?.pageVisibilityMetrics.find((item) => item.pageNumber === span.page + 1);
      const viewport = registry.getPlugin("viewport")?.provides?.() as
        | { getMetrics(): { clientWidth: number; clientHeight: number } }
        | undefined;
      const measured = viewport?.getMetrics();
      const port = scrollport(
        container,
        measured ? { width: measured.clientWidth, height: measured.clientHeight } : undefined,
      );
      if (!visible || !port || !rects.length) {
        setMarks([]);
        return;
      }
      const origin = port.getBoundingClientRect();
      const mapped = {
        viewportX: visible.viewportX,
        viewportY: visible.viewportY,
        pageX: visible.original.pageX,
        pageY: visible.original.pageY,
        scale: visible.original.scale,
      };
      const current = placeRef.current;
      if (current) {
        const spot = glossClientRect({ origin: current.pagePoint, size: { width: 0, height: 0 } }, mapped, origin);
        setCardPoint({ x: spot.left, y: spot.top });
      }
      setMarks(rects.map((rect) => glossClientRect(rect, mapped, origin)));
    };

    const refresh = () => {
      const current = placeRef.current;
      const documentId = documents.getActiveDocumentId();
      const pdf = documentId ? documents.getDocumentState(documentId)?.document : undefined;
      if (current && pdf) void paint(pdf, current.span);
    };

    const scroll = registry.getPlugin<ScrollPlugin>("scroll")?.provides?.();
    if (!scroll) return;
    bind();
    const stops = [scroll.onLayoutReady(() => bind()), scroll.onScroll(refresh)];
    try {
      const zoom = registry.getPlugin("zoom")?.provides?.() as
        | { onZoomChange?(listener: () => void): () => void }
        | undefined;
      const stopZoom = zoom?.onZoomChange?.(refresh);
      if (stopZoom) stops.push(stopZoom);
    } catch {
      /* Zoom events are optional; scrolling still repositions the highlight. */
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPlace(null);
        setCardPoint(null);
        setMarks([]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      stops.forEach((stop) => stop());
      remove.forEach((fn) => fn());
      window.removeEventListener("keydown", onKey);
    };
  }, [registry, container, spans]);

  const point = cardPoint ?? place?.client;
  const card = point
    ? glossCardPosition(point, cardBox, { width: window.innerWidth, height: window.innerHeight })
    : null;

  return (
    <>
      {marks.map((mark, index) => (
        <span key={index} className="gloss-mark" style={mark} />
      ))}
      {place && card ? (
        <aside
          ref={cardRef}
          className="gloss-card"
          role="dialog"
          aria-label={place.span.label}
          style={{ left: card.left, top: card.top }}
        >
          <p className="gloss-kicker">{place.span.label}</p>
          <p className="gloss-source">{place.span.text}</p>
          <p className="gloss-zh">{place.span.zh}</p>
          <p className="gloss-note">{place.span.category === "word" ? place.span.en : place.span.role}</p>
        </aside>
      ) : null}
    </>
  );
}

function scrollport(root: HTMLElement | null, size?: { width: number; height: number }): HTMLElement | null {
  if (!root) return null;
  const nodes = [root, ...root.querySelectorAll<HTMLElement>("div")];
  if (size) {
    const match = nodes.find(
      (node) => Math.abs(node.clientWidth - size.width) < 2 && Math.abs(node.clientHeight - size.height) < 2,
    );
    if (match) return match;
  }
  return nodes.reduce<HTMLElement | null>((best, node) => {
    if (node.scrollHeight <= node.clientHeight + 8) return best;
    return !best || node.scrollHeight > best.scrollHeight ? node : best;
  }, null);
}

async function loadTextPage(registry: PluginRegistry, pdf: { pages: unknown[] }, pageIndex: number): Promise<TextPage> {
  const engine = registry.getEngine();
  const document = pdf as Parameters<typeof engine.getPageGeometry>[0];
  const page = document.pages[pageIndex];
  const geometry = await engine.getPageGeometry(document, page).toPromise();
  const indexes = geometry.runs.flatMap((run) =>
    run.glyphs.flatMap((glyph, index) => (glyph.flags & 3 ? [] : [run.charStart + index])),
  );
  const strings = await engine
    .getTextSlices(
      document,
      indexes.map((charIndex) => ({ pageIndex, charIndex, charCount: 1 })),
    )
    .toPromise();
  return { geometry, characters: indexes.map((index, position) => ({ index, text: strings[position] })) };
}
