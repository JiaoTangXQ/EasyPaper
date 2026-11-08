import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { cacheGet, cacheSet } from "./reader-store";
import type { GlossSpan } from "./gloss-hit";

const PAGE_WINDOW = 2;
const PREFETCH_BATCH = 10;

function pagesAround(center1Based: number, pageCount: number): number[] {
  const center = Math.max(1, Math.min(pageCount, center1Based)) - 1;
  const pages: number[] = [];
  for (let delta = -PAGE_WINDOW; delta <= PAGE_WINDOW; delta += 1) {
    const index = center + delta;
    if (index >= 0 && index < pageCount) pages.push(index);
  }
  return pages;
}

export function useGlossSpans(
  documentId: string | undefined,
  glossReady: boolean,
  viewerPage: number,
  pageCount: number,
) {
  const [glossSpans, setGlossSpans] = useState<GlossSpan[] | null>(null);
  const [glossBooting, setGlossBooting] = useState(false);
  const digestRef = useRef("");
  const allPagesRef = useRef<number[]>([]);
  const loadedPages = useRef(new Set<number>());
  const inflight = useRef(new Set<string>());
  const prefetching = useRef(false);
  const viewerPageRef = useRef(viewerPage);
  viewerPageRef.current = viewerPage;

  const mergeSpans = useCallback((incoming: GlossSpan[]) => {
    if (!incoming.length) return;
    setGlossSpans((current) => {
      const byId = new Map((current || []).map((span) => [span.id, span]));
      incoming.forEach((span) => byId.set(span.id, span));
      return Array.from(byId.values());
    });
  }, []);

  const updateGlossSpan = useCallback((patch: GlossSpan) => {
    setGlossSpans(
      (current) => current?.map((span) => (span.id === patch.id ? { ...span, ...patch } : span)) || current,
    );
  }, []);

  const fetchPages = useCallback(
    async (pages: number[]) => {
      if (!documentId || !digestRef.current || !pages.length) return;
      const missing = pages.filter((page) => !loadedPages.current.has(page));
      if (!missing.length) return;
      const signature = missing.slice().sort((a, b) => a - b).join(",");
      if (inflight.current.has(signature)) return;
      inflight.current.add(signature);
      try {
        const { data } = await api.get<{ digest: string; spans: GlossSpan[] }>(
          `/api/reader/documents/${documentId}/gloss`,
          { params: { scope: "pages", pages: missing.join(",") } },
        );
        if (data.digest !== digestRef.current) return;
        missing.forEach((page) => loadedPages.current.add(page));
        mergeSpans(data.spans || []);
      } finally {
        inflight.current.delete(signature);
      }
    },
    [documentId, mergeSpans],
  );

  const prefetchRemaining = useCallback(
    async (document: string, digest: string) => {
      if (prefetching.current) return;
      prefetching.current = true;
      try {
        const remaining = allPagesRef.current.filter((page) => !loadedPages.current.has(page));
        for (let index = 0; index < remaining.length; index += PREFETCH_BATCH) {
          await fetchPages(remaining.slice(index, index + PREFETCH_BATCH));
          await new Promise((resolve) => window.setTimeout(resolve, 0));
        }
        setGlossSpans((current) => {
          if (current?.length && digestRef.current === digest) {
            void cacheSet(`gloss:${document}:${digest}`, current).catch(() => undefined);
          }
          return current;
        });
      } finally {
        prefetching.current = false;
      }
    },
    [fetchPages],
  );

  useEffect(() => {
    if (!documentId || !glossReady || pageCount < 1) {
      setGlossSpans(null);
      digestRef.current = "";
      allPagesRef.current = [];
      loadedPages.current = new Set();
      inflight.current = new Set();
      prefetching.current = false;
      return;
    }
    let cancelled = false;
    setGlossBooting(true);
    void (async () => {
      try {
        const { data: meta } = await api.get<{
          digest: string;
          pages: number[];
          span_count: number;
        }>(`/api/reader/documents/${documentId}/gloss`, { params: { scope: "meta" } });
        if (cancelled) return;
        digestRef.current = meta.digest || "";
        allPagesRef.current = meta.pages || [];
        loadedPages.current = new Set();
        inflight.current = new Set();
        prefetching.current = false;

        const cacheKey = `gloss:${documentId}:${meta.digest}`;
        const cached = await cacheGet<GlossSpan[]>(cacheKey).catch(() => undefined);
        if (cached?.length) {
          meta.pages.forEach((page) => loadedPages.current.add(page));
          setGlossSpans(cached);
          return;
        }

        setGlossSpans([]);
        await fetchPages(pagesAround(viewerPageRef.current, pageCount));
        if (!cancelled) void prefetchRemaining(documentId, meta.digest);
      } finally {
        if (!cancelled) setGlossBooting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId, glossReady, pageCount, fetchPages, prefetchRemaining]);

  useEffect(() => {
    if (!documentId || !glossReady || pageCount < 1 || !digestRef.current) return;
    void fetchPages(pagesAround(viewerPage, pageCount));
  }, [viewerPage, documentId, glossReady, pageCount, fetchPages]);

  return { glossSpans, glossBooting, updateGlossSpan };
}
