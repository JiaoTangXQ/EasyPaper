import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { cacheGet, cacheSet } from "./reader-store";
import type { GlossSpan } from "./gloss-hit";

// Fetch only what the reader is about to see: one page back, three ahead.
// Scrolling moves the window; nothing else is downloaded in the background,
// so the paper itself keeps the (small) server's bandwidth.
const LOOK_BEHIND = 1;
const LOOK_AHEAD = 3;
const META_POLL_MS = 2500;
const PERSIST_DELAY_MS = 800;
const TERMINAL_STATUSES = new Set(["completed", "error"]);

type GlossMeta = {
  status: string;
  error: string;
  digest: string;
  pages: number[];
  span_count: number;
};
/** Pages already fetched for one immutable gloss revision (digest). */
type CachedGloss = { pages: number[]; spans: GlossSpan[] };

export function glossWindow(center1Based: number, pageCount: number): number[] {
  const center = Math.max(1, Math.min(pageCount, center1Based)) - 1;
  const pages: number[] = [];
  for (let index = center - LOOK_BEHIND; index <= center + LOOK_AHEAD; index += 1) {
    if (index >= 0 && index < pageCount) pages.push(index);
  }
  return pages;
}

const cacheKey = (documentId: string, digest: string) => `gloss-pages:${documentId}:${digest}`;

export function useGlossSpans(
  documentId: string | undefined,
  glossAvailable: boolean,
  viewerPage: number,
  pageCount: number,
  buildStatus = "missing",
) {
  const [glossSpans, setGlossSpans] = useState<GlossSpan[] | null>(null);
  const [glossBooting, setGlossBooting] = useState(false);
  const digestRef = useRef("");
  const statusRef = useRef(buildStatus);
  const spans = useRef(new Map<string, GlossSpan>());
  const loadedPages = useRef(new Set<number>());
  const inflight = useRef(new Set<string>());
  const persistTimer = useRef<number>();
  const viewerPageRef = useRef(viewerPage);
  viewerPageRef.current = viewerPage;

  useEffect(() => {
    statusRef.current = buildStatus;
  }, [buildStatus]);

  const publish = useCallback(() => setGlossSpans(Array.from(spans.current.values())), []);

  // Remember fetched pages per revision, so reopening the paper needs no request
  // for pages already read. Only finished builds are stable enough to keep.
  const persist = useCallback(() => {
    if (!documentId || !digestRef.current || statusRef.current !== "completed") return;
    window.clearTimeout(persistTimer.current);
    const digest = digestRef.current;
    persistTimer.current = window.setTimeout(() => {
      if (digestRef.current !== digest) return;
      const value: CachedGloss = { pages: [...loadedPages.current], spans: [...spans.current.values()] };
      void cacheSet(cacheKey(documentId, digest), value).catch(() => undefined);
    }, PERSIST_DELAY_MS);
  }, [documentId]);

  const updateGlossSpan = useCallback(
    (patch: GlossSpan) => {
      const current = spans.current.get(patch.id);
      if (!current) return;
      spans.current.set(patch.id, { ...current, ...patch });
      publish();
      persist();
    },
    [persist, publish],
  );

  const fetchPages = useCallback(
    async (pages: number[]) => {
      if (!documentId || !digestRef.current || !pages.length) return;
      const missing = pages.filter((page) => !loadedPages.current.has(page));
      if (!missing.length) return;
      const signature = missing.slice().sort((a, b) => a - b).join(",");
      if (inflight.current.has(signature)) return;
      inflight.current.add(signature);
      try {
        const { data } = await api.get<GlossMeta & { spans: GlossSpan[] }>(
          `/api/reader/documents/${documentId}/gloss`,
          { params: { scope: "pages", pages: missing.join(",") } },
        );
        statusRef.current = data.status || statusRef.current;
        if (data.digest && data.digest !== digestRef.current) {
          // A checkpoint landed while this request was in flight. Keep the
          // spans already shown, but refetch every page against the new digest.
          digestRef.current = data.digest;
          loadedPages.current = new Set();
        }
        const incoming = data.spans || [];
        const available = new Set(incoming.map((span) => span.page));
        const terminal = TERMINAL_STATUSES.has(data.status || statusRef.current);
        missing.forEach((page) => {
          // While the build is active, an empty page may simply not have been
          // generated yet. Leave it retryable until a checkpoint contains it.
          if (terminal || available.has(page)) loadedPages.current.add(page);
        });
        if (incoming.length) {
          incoming.forEach((span) => spans.current.set(span.id, span));
          publish();
        }
        persist();
      } finally {
        inflight.current.delete(signature);
      }
    },
    [documentId, persist, publish],
  );

  useEffect(() => {
    if (!documentId || !glossAvailable || pageCount < 1) {
      setGlossSpans(null);
      digestRef.current = "";
      statusRef.current = buildStatus;
      spans.current = new Map();
      loadedPages.current = new Set();
      inflight.current = new Set();
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    setGlossBooting(true);

    const applyMeta = (meta: GlossMeta) => {
      const changed = Boolean(digestRef.current && meta.digest !== digestRef.current);
      digestRef.current = meta.digest || digestRef.current;
      statusRef.current = meta.status || statusRef.current;
      if (changed) loadedPages.current = new Set();
      return changed;
    };

    const restore = async (meta: GlossMeta) => {
      const cached = await cacheGet<CachedGloss>(cacheKey(documentId, meta.digest)).catch(() => undefined);
      if (cached?.spans?.length) {
        cached.spans.forEach((span) => spans.current.set(span.id, span));
        cached.pages.forEach((page) => loadedPages.current.add(page));
        return true;
      }
      // Older clients cached the complete span list under a different key.
      const legacy = await cacheGet<GlossSpan[]>(`gloss:${documentId}:${meta.digest}`).catch(() => undefined);
      if (legacy?.length) {
        legacy.forEach((span) => spans.current.set(span.id, span));
        meta.pages.forEach((page) => loadedPages.current.add(page));
        return true;
      }
      return false;
    };

    // Poll only while the build is still producing pages.
    const schedulePoll = () => {
      window.clearInterval(timer);
      timer = undefined;
      if (cancelled || TERMINAL_STATUSES.has(statusRef.current)) return;
      timer = window.setInterval(() => void poll(), META_POLL_MS);
    };
    const poll = async () => {
      try {
        const { data } = await api.get<GlossMeta>(`/api/reader/documents/${documentId}/gloss`, {
          params: { scope: "meta" },
        });
        if (cancelled) return;
        applyMeta(data);
        // fetchPages skips pages already loaded; pages that were still empty are retried.
        await fetchPages(glossWindow(viewerPageRef.current, pageCount));
        if (TERMINAL_STATUSES.has(data.status)) schedulePoll();
      } catch {
        // The PDF remains readable while a transient worker/API request fails.
      }
    };

    void (async () => {
      try {
        const { data: meta } = await api.get<GlossMeta>(`/api/reader/documents/${documentId}/gloss`, {
          params: { scope: "meta" },
        });
        if (cancelled) return;
        applyMeta(meta);
        if (meta.status === "completed") await restore(meta);
        if (cancelled) return;
        publish();
        await fetchPages(glossWindow(viewerPageRef.current, pageCount));
      } catch {
        if (!cancelled) setGlossSpans((current) => current ?? []);
      } finally {
        if (!cancelled) {
          setGlossBooting(false);
          schedulePoll();
        }
      }
    })();

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.clearTimeout(persistTimer.current);
    };
  }, [documentId, glossAvailable, pageCount, buildStatus, fetchPages, publish]);

  useEffect(() => {
    if (!documentId || !glossAvailable || pageCount < 1 || !digestRef.current) return;
    void fetchPages(glossWindow(viewerPage, pageCount));
  }, [viewerPage, documentId, glossAvailable, pageCount, fetchPages]);

  return { glossSpans, glossBooting, updateGlossSpan };
}
