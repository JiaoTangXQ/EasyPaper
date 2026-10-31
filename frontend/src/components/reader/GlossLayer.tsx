import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { DocumentManagerPlugin, ScrollPlugin, type PluginRegistry } from "@embedpdf/react-pdf-viewer";
import type { Rect } from "@embedpdf/models";
import { Volume2, VolumeX, X } from "lucide-react";
import api from "@/lib/api";
import { glossCardPosition, glyphIndexAt, spanAtChar, type GlossSpan } from "./gloss-hit";
import { textAnchorRects, type TextPage } from "./text-anchor";

type Box = { left: number; top: number; width: number; height: number };
type Point = { x: number; y: number };
type Place = { span: GlossSpan; pagePoint: Point; client: Point };

export default function GlossLayer({
  registry,
  container,
  spans,
  onEnrich,
}: {
  registry: PluginRegistry;
  container: HTMLElement | null;
  spans: GlossSpan[];
  onEnrich?: (span: GlossSpan) => Promise<GlossSpan | null>;
}) {
  const spansByPageRef = useRef(new Map<number, GlossSpan[]>());
  const spanSignature = useRef("");
  const pages = useRef(new Map<number, Promise<TextPage>>());
  const placeRef = useRef<Place | null>(null);
  const [place, setPlace] = useState<Place | null>(null);
  const [cardPoint, setCardPoint] = useState<Point | null>(null);
  const [marks, setMarks] = useState<Box[]>([]);
  const [cardBox, setCardBox] = useState({ width: 300, height: 120 });
  const [enriching, setEnriching] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [speechLoading, setSpeechLoading] = useState(false);
  const [portalHost, setPortalHost] = useState<HTMLElement | null>(null);
  const dismissedPointer = useRef(false);
  const enrichRequest = useRef(0);
  const speechRequest = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrls = useRef(new Map<string, string>());
  const cardRef = useRef<HTMLElement>(null);

  const closePopup = useCallback(() => {
    window.speechSynthesis?.cancel();
    speechRequest.current += 1;
    audioRef.current?.pause();
    if (audioRef.current) audioRef.current.currentTime = 0;
    enrichRequest.current += 1;
    placeRef.current = null;
    setSpeaking(false);
    setSpeechLoading(false);
    setEnriching(false);
    setPlace(null);
    setCardPoint(null);
    setMarks([]);
  }, []);

  useEffect(() => {
    const updateHost = () => setPortalHost((document.fullscreenElement as HTMLElement | null) || document.body);
    updateHost();
    document.addEventListener("fullscreenchange", updateHost);
    return () => document.removeEventListener("fullscreenchange", updateHost);
  }, []);

  useEffect(() => {
    const byPage = new Map<number, GlossSpan[]>();
    spans.forEach((span) => {
      const page = byPage.get(span.page);
      if (page) page.push(span);
      else byPage.set(span.page, [span]);
    });
    spansByPageRef.current = byPage;
    const nextSignature = spans.map((span) => span.id).join(",");
    if (spanSignature.current && spanSignature.current !== nextSignature) {
      closePopup();
    }
    spanSignature.current = nextSignature;
  }, [spans, closePopup]);
  useEffect(() => {
    placeRef.current = place;
  }, [place]);

  useEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    const box = card.getBoundingClientRect();
    if (box.width && box.height) setCardBox({ width: box.width, height: box.height });
  }, [place, portalHost]);

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
                if (dismissedPointer.current) {
                  dismissedPointer.current = false;
                  down = null;
                  return;
                }
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
              spansByPageRef.current.get(pageIndex) ?? [],
              glyph,
            );
      if (!span) {
        closePopup();
        return;
      }
      const next = { span, pagePoint: point, client };
      placeRef.current = next;
      setPlace(next);
      setCardPoint(client);
      const requestId = ++enrichRequest.current;
      if (onEnrich && (!span.simple_en || !span.ipa)) {
        setEnriching(true);
        void onEnrich(span)
          .then((enriched) => {
            if (requestId === enrichRequest.current && enriched && placeRef.current?.span.id === enriched.id) {
              const updated = { ...placeRef.current, span: enriched };
              placeRef.current = updated;
              setPlace(updated);
            }
          })
          .finally(() => {
            if (requestId === enrichRequest.current) setEnriching(false);
          });
      }
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
      const viewport = registry.getPlugin("viewport")?.provides?.() as
        | { getMetrics(): { clientWidth: number; clientHeight: number }; getViewportGap?(): number }
        | undefined;
      const measured = viewport?.getMetrics();
      const port = scrollport(
        container,
        measured ? { width: measured.clientWidth, height: measured.clientHeight } : undefined,
      );
      if (!scroll || !metrics || !port || !rects.length) {
        setMarks([]);
        return;
      }
      const origin = port.getBoundingClientRect();
      const offset = metrics.scrollOffset || { x: 0, y: 0 };
      const gap = viewport?.getViewportGap?.() || 0;
      const toClientRect = (rect: Rect) => {
        try {
          const positioned = scroll.getRectPositionForPage(span.page, rect);
          if (!positioned) return null;
          return {
            left: origin.left + gap + positioned.origin.x - offset.x,
            top: origin.top + gap + positioned.origin.y - offset.y,
            width: positioned.size.width,
            height: positioned.size.height,
          };
        } catch {
          return null;
        }
      };
      const current = placeRef.current;
      if (current?.span.id === span.id) {
        const spot = toClientRect({ origin: current.pagePoint, size: { width: 0, height: 0 } });
        if (spot) setCardPoint({ x: spot.left, y: spot.top });
      }
      setMarks(rects.map(toClientRect).filter((rect): rect is Box => Boolean(rect)));
    };

    const refresh = () => {
      const current = placeRef.current;
      const documentId = documents.getActiveDocumentId();
      const pdf = documentId ? documents.getDocumentState(documentId)?.document : undefined;
      if (current && pdf) void paint(pdf, current.span);
    };
    const refreshAfterLayout = () => window.requestAnimationFrame(refresh);

    const onDocumentPointerDown = (event: PointerEvent) => {
      if (!placeRef.current) {
        // A toolbar click can happen between the page pointerdown/pointerup
        // pair. Clear the one-shot dismissal marker before the next gesture.
        dismissedPointer.current = false;
        return;
      }
      const target = event.target;
      if (target instanceof Node && cardRef.current?.contains(target)) return;
      dismissedPointer.current = true;
      closePopup();
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
      if (event.key === "Escape" && placeRef.current) {
        event.preventDefault();
        event.stopPropagation();
        closePopup();
      }
    };
    document.addEventListener("pointerdown", onDocumentPointerDown, true);
    window.addEventListener("resize", refreshAfterLayout);
    document.addEventListener("fullscreenchange", refreshAfterLayout);
    window.addEventListener("keydown", onKey, true);
    return () => {
      stops.forEach((stop) => stop());
      remove.forEach((fn) => fn());
      document.removeEventListener("pointerdown", onDocumentPointerDown, true);
      window.removeEventListener("resize", refreshAfterLayout);
      document.removeEventListener("fullscreenchange", refreshAfterLayout);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [registry, container, spans, onEnrich, closePopup]);

  useEffect(
    () => () => {
      speechRequest.current += 1;
      audioRef.current?.pause();
      audioUrls.current.forEach((url) => URL.revokeObjectURL(url));
      audioUrls.current.clear();
    },
    [],
  );

  const speakWithBrowser = useCallback((text: string) => {
    if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") return false;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 0.92;
    const voices = window.speechSynthesis.getVoices();
    // Prefer Edge's cloud/neural voice when the browser exposes it. Local
    // system voices are intentionally excluded because they caused the
    // distorted, recorder-like sound reported by readers.
    const voice = voices.find(
      (candidate) => /^en-US/i.test(candidate.lang) && /(online|natural|jenny|aria|guy|ava|andrew)/i.test(candidate.name),
    );
    if (!voice) return false;
    utterance.voice = voice;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.speak(utterance);
    return true;
  }, []);

  const speak = useCallback(async () => {
    if (!place || !place.span.text.trim()) return;
    if (speaking || speechLoading) {
      speechRequest.current += 1;
      audioRef.current?.pause();
      if (audioRef.current) audioRef.current.currentTime = 0;
      window.speechSynthesis?.cancel();
      setSpeaking(false);
      setSpeechLoading(false);
      return;
    }
    const text = place.span.text.trim();
    const requestId = ++speechRequest.current;
    const cached = audioUrls.current.get(text);
    if (cached) {
      const audio = new Audio(cached);
      audioRef.current = audio;
      audio.onended = () => setSpeaking(false);
      audio.onerror = () => setSpeaking(false);
      setSpeaking(true);
      try {
        await audio.play();
        if (requestId !== speechRequest.current) audio.pause();
      } catch {
        if (requestId !== speechRequest.current) return;
        setSpeaking(false);
      }
      return;
    }
    setSpeechLoading(true);
    let response: { data: Blob };
    try {
      response = await api.post<Blob>("/api/reader/tts", { text }, { responseType: "blob" });
    } catch {
      if (requestId === speechRequest.current) {
        setSpeaking(false);
        setSpeechLoading(false);
        speakWithBrowser(text);
      }
      return;
    }
    if (requestId !== speechRequest.current) return;
    const url = URL.createObjectURL(response.data);
    audioUrls.current.set(text, url);
    while (audioUrls.current.size > 64) {
      const oldest = audioUrls.current.keys().next().value as string | undefined;
      if (!oldest) break;
      URL.revokeObjectURL(audioUrls.current.get(oldest) || "");
      audioUrls.current.delete(oldest);
    }
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => setSpeaking(false);
    audio.onerror = () => setSpeaking(false);
    setSpeaking(true);
    try {
      await audio.play();
      if (requestId !== speechRequest.current) audio.pause();
    } catch {
      // A successful neural response must never be replaced by a local,
      // distorted voice when autoplay policy blocks playback.
      if (requestId === speechRequest.current) setSpeaking(false);
    } finally {
      if (requestId === speechRequest.current) setSpeechLoading(false);
    }
  }, [place, speakWithBrowser, speaking, speechLoading]);
  const canSpeak = typeof Audio !== "undefined" || "speechSynthesis" in window;

  const point = cardPoint ?? place?.client;
  const card = point
    ? glossCardPosition(point, cardBox, { width: window.innerWidth, height: window.innerHeight })
    : null;

  const content = (
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
          <div className="gloss-headline">
            <p className="gloss-kicker">{place.span.label}</p>
            <div className="gloss-actions">
              <button
                type="button"
                className="gloss-speak"
                aria-label={speaking || speechLoading ? "停止朗读" : "朗读英文"}
                title={speaking || speechLoading ? "停止朗读" : "朗读英文"}
                onClick={speak}
                disabled={!canSpeak || !place.span.text.trim()}
              >
                {speaking || speechLoading ? <VolumeX size={16} /> : <Volume2 size={16} />}
              </button>
              <button
                type="button"
                className="gloss-close"
                aria-label="关闭点读解释"
                title="关闭"
                onClick={closePopup}
              >
                <X size={16} />
              </button>
            </div>
          </div>
          <p className="gloss-source">{place.span.text}</p>
          {place.span.ipa ? <p className="gloss-ipa">/{place.span.ipa.replace(/^\/+|\/+$/g, "")}/</p> : null}
          <p className="gloss-zh">{place.span.zh}</p>
          {place.span.simple_en || place.span.en ? (
            <p className="gloss-simple-en">{place.span.simple_en || place.span.en}</p>
          ) : enriching ? (
            <p className="gloss-simple-en gloss-loading">正在准备简明英文解释…</p>
          ) : null}
          {place.span.role ? <p className="gloss-note">{place.span.role}</p> : null}
        </aside>
      ) : null}
    </>
  );
  return portalHost ? createPortal(content, portalHost) : null;
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
