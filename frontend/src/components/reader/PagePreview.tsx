import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ReaderVersion } from "./reader-store";

const GAP = 16;
const MAX_SCALE = 1.5;

type PageSize = { width: number; height: number; rotation: number };

function formatMB(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(bytes > 10 * 1024 * 1024 ? 0 : 1)} MB`;
}

function geometry(pages: PageSize[] | undefined, count: number): PageSize[] {
  return pages?.length === count
    ? pages
    : Array.from(
        { length: count },
        (_, index) => pages?.[index] || pages?.[0] || { width: 612, height: 792, rotation: 0 },
      );
}

/**
 * Scrollable page images. Only pages near the viewport are requested, so a page
 * appears in about a second even for a 30 MB paper. `ready` limits requests to
 * pages that exist on the server; when it grows, visible pages load at once.
 */
function PageImages({
  pages,
  imageUrl,
  sourceKey,
  ready,
  initialPage,
  placeholder,
  onPageChange,
  status,
  className,
}: {
  pages: PageSize[];
  imageUrl: (index: number) => string;
  /** Changes when the images belong to another document or version. */
  sourceKey: string;
  ready?: number[];
  initialPage: number;
  placeholder: (index: number) => ReactNode;
  onPageChange: (page: number) => void;
  status: ReactNode;
  className?: string;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [images, setImages] = useState<Record<number, string>>({});
  const imagesRef = useRef(images);
  imagesRef.current = images;
  const requested = useRef(new Set<number>());
  const urls = useRef<string[]>([]);
  const lastPage = useRef(initialPage);
  const imageUrlRef = useRef(imageUrl);
  imageUrlRef.current = imageUrl;
  const readyKey = ready ? ready.join(",") : "all";

  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const created = urls.current;
    return () => created.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const pageWidth = (index: number) => {
    const page = pages[index] || pages[0];
    const rotated = page.rotation % 180 !== 0;
    const natural = rotated ? page.height : page.width;
    return Math.max(120, Math.min(width - GAP * 2, natural * MAX_SCALE));
  };
  const pageHeight = (index: number) => {
    const page = pages[index] || pages[0];
    const rotated = page.rotation % 180 !== 0;
    const ratio = rotated ? page.width / page.height : page.height / page.width;
    return pageWidth(index) * ratio;
  };

  // Open on the remembered page, like the real viewer will.
  const positioned = useRef(false);
  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element || !width || positioned.current) return;
    positioned.current = true;
    const target = element.querySelector<HTMLElement>(`[data-preview-page="${initialPage - 1}"]`);
    if (target) element.scrollTop = target.offsetTop - GAP;
  }, [width, initialPage]);

  useEffect(() => {
    const element = scroller.current;
    if (!element || !width) return;
    const controller = new AbortController();
    const allowed = readyKey === "all" ? null : new Set(readyKey ? readyKey.split(",").map(Number) : []);
    const load = (index: number) => {
      if (requested.current.has(index) || (allowed && !allowed.has(index))) return;
      requested.current.add(index);
      const pixels = Math.round(pageWidth(index) * Math.min(2, window.devicePixelRatio || 1));
      void api
        .get<Blob>(imageUrlRef.current(index), {
          params: { width: pixels },
          responseType: "blob",
          signal: controller.signal,
        })
        .then(({ data }) => {
          const url = URL.createObjectURL(data);
          urls.current.push(url);
          setImages((current) => ({ ...current, [index]: url }));
        })
        .catch(() => requested.current.delete(index));
    };
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) load(Number((entry.target as HTMLElement).dataset.previewPage));
        });
      },
      { root: element, rootMargin: "600px 0px" },
    );
    element.querySelectorAll("[data-preview-page]").forEach((node) => observer.observe(node));
    return () => {
      observer.disconnect();
      controller.abort();
      // Aborted pages may be requested again when observed next time.
      requested.current = new Set(Object.keys(imagesRef.current).map(Number));
    };
    // pageWidth depends only on width and the page geometry of this source.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey, width, readyKey]);

  const onScroll = () => {
    const element = scroller.current;
    if (!element) return;
    const middle = element.scrollTop + element.clientHeight / 3;
    let current = 1;
    for (const node of element.querySelectorAll<HTMLElement>("[data-preview-page]")) {
      if (node.offsetTop <= middle) current = Number(node.dataset.previewPage) + 1;
      else break;
    }
    if (current !== lastPage.current) {
      lastPage.current = current;
      onPageChange(current);
    }
  };

  return (
    <div className={cn("page-preview", className)} aria-busy="true">
      <div className="page-preview-status" role="status">
        {status}
      </div>
      <div className="page-preview-scroll" ref={scroller} onScroll={onScroll}>
        {width
          ? pages.map((_, index) => (
              <div
                key={index}
                className="page-preview-page"
                data-preview-page={index}
                style={{ width: pageWidth(index), height: pageHeight(index) }}
              >
                {images[index] ? (
                  <img src={images[index]} alt={`第 ${index + 1} 页预览`} draggable={false} />
                ) : (
                  <span className="page-preview-placeholder" aria-hidden="true">
                    {placeholder(index)}
                  </span>
                )}
              </div>
            ))
          : null}
      </div>
    </div>
  );
}

function ProgressBar({ percent }: { percent: number }) {
  return (
    <span className="page-preview-bar" aria-hidden="true">
      <span style={{ transform: `scaleX(${percent / 100})` }} />
    </span>
  );
}

/** Page images shown while the complete PDF is still downloading. Interaction waits for the real viewer. */
export default function PagePreview({
  documentId,
  version,
  initialPage,
  loaded,
  total,
  onPageChange,
}: {
  documentId: string;
  version: ReaderVersion;
  initialPage: number;
  loaded: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  const percent = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : null;
  return (
    <PageImages
      pages={geometry(version.pages, version.page_count)}
      sourceKey={`${documentId}:${version.id}`}
      imageUrl={(index) =>
        `/api/reader/documents/${documentId}/versions/${encodeURIComponent(version.id)}/pages/${index}/preview`
      }
      initialPage={initialPage}
      placeholder={(index) => `第 ${index + 1} 页`}
      onPageChange={onPageChange}
      status={
        <>
          <Loader2 className="spin" size={14} aria-hidden="true" />
          <span>
            正在载入完整 PDF{percent !== null ? ` · ${percent}%` : ""}
            {total > 0 ? (
              <span className="page-preview-size">
                （{formatMB(loaded)} / {formatMB(total)}）
              </span>
            ) : null}
          </span>
          <span className="page-preview-hint">先显示页面预览，划线和点读稍后可用</span>
          {percent !== null ? <ProgressBar percent={percent} /> : null}
        </>
      }
    />
  );
}

/**
 * Pages of a translation that is still running. pdf2zh translates in page order,
 * so the first missing page is the one in progress.
 */
export function TranslationPreview({
  documentId,
  kind,
  pages,
  total,
  done,
  initialPage,
  onPageChange,
}: {
  documentId: string;
  kind: string;
  pages?: PageSize[];
  total: number;
  done: number[];
  initialPage: number;
  onPageChange: (page: number) => void;
}) {
  const finished = new Set(done);
  let current = 0;
  while (finished.has(current)) current++;
  const percent = total > 0 ? Math.min(100, Math.round((done.length / total) * 100)) : 0;
  return (
    <PageImages
      className="is-translating"
      pages={geometry(pages, total)}
      sourceKey={`${documentId}:build:${kind}`}
      ready={done}
      imageUrl={(index) => `/api/reader/documents/${documentId}/builds/${kind}/pages/${index}/preview`}
      initialPage={Math.min(Math.max(1, initialPage), total)}
      placeholder={(index) => (index === current ? `正在翻译第 ${index + 1} 页…` : `第 ${index + 1} 页 · 稍后译好`)}
      onPageChange={onPageChange}
      status={
        <>
          <Loader2 className="spin" size={14} aria-hidden="true" />
          <span>
            正在翻译 · 已完成{" "}
            <span className="page-preview-size">
              {done.length} / {total}
            </span>{" "}
            页
          </span>
          <span className="page-preview-hint">译好的页先显示，全部完成后可划线批注</span>
          <ProgressBar percent={percent} />
        </>
      }
    />
  );
}
