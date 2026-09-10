import type { PdfAnnotationObject, Rect } from "@embedpdf/react-pdf-viewer";
import type { TextAnchor } from "./text-anchor";

export type ReaderMode = "original" | "chinese" | "simple" | "bilingual";
export const versionNames: Record<ReaderMode, string> = {
  original: "原文",
  chinese: "中文译文",
  simple: "简化英语",
  bilingual: "双语对照",
};
export type ReaderVersion = {
  id: string;
  kind: ReaderMode;
  url: string;
  page_count: number;
  origin_pages?: (number | null)[];
  fingerprint: string;
  created_at: string;
  pages: { width: number; height: number; rotation: number }[];
};
export type Projection = {
  page: number;
  unit_id: string;
  quote: string;
  rects: Rect[];
  method: string;
  text_anchor?: TextAnchor;
  geometry?: Partial<PdfAnnotationObject>;
};
export type SharedAnnotation = {
  id: string;
  document_id: string;
  source_version_id: string;
  data: PdfAnnotationObject;
  quote: string;
  anchors: string[];
  projections: Record<string, Projection[]>;
  revision: number;
  deleted: boolean;
  alignment_status: string;
  alignment_message: string;
  updated_at: string;
};
export type ReaderBundle = {
  document_id: string;
  user_id: number;
  title: string;
  versions: ReaderVersion[];
  annotations: SharedAnnotation[];
  builds: { kind: ReaderMode; status: string; error: string }[];
};
export type PendingOperation = {
  operation_id: string;
  annotation_id: string;
  document_id: string;
  user_id: number;
  base_revision: number;
  version_id: string;
  data: PdfAnnotationObject;
  deleted: boolean;
  geometry_changed: boolean;
  created: number;
  conflict?: boolean;
};

let database: Promise<IDBDatabase> | undefined;
function db() {
  return (database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open("easypaper-reader", 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("cache");
      request.result.createObjectStore("outbox", { keyPath: "operation_id" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      database = undefined;
      reject(request.error);
    };
  }));
}

export async function cacheGet<T>(key: string): Promise<T | undefined> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const request = database.transaction("cache").objectStore("cache").get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function cacheSet(key: string, value: unknown) {
  const database = await db();
  return new Promise<void>((resolve, reject) => {
    const transaction = database.transaction("cache", "readwrite");
    transaction.objectStore("cache").put(value, key);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

export async function pendingOperations(userId: number, documentId: string): Promise<PendingOperation[]> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const request = database.transaction("outbox").objectStore("outbox").getAll();
    request.onsuccess = () =>
      resolve(
        (request.result as PendingOperation[])
          .filter((p) => p.user_id === userId && p.document_id === documentId)
          .sort((a, b) => a.created - b.created),
      );
    request.onerror = () => reject(request.error);
  });
}

export async function storeOperation(operation: PendingOperation, remove = false) {
  const database = await db();
  return new Promise<void>((resolve, reject) => {
    const transaction = database.transaction("outbox", "readwrite");
    const store = transaction.objectStore("outbox");
    if (remove) store.delete(operation.operation_id);
    else store.put(operation);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

// A response started before a save may arrive after it. Never regress an acknowledged revision.
export function mergeServer(current: ReaderBundle | null, incoming: ReaderBundle): ReaderBundle {
  if (!current || current.document_id !== incoming.document_id) return incoming;
  const annotations = new Map(current.annotations.map((a) => [a.id, a]));
  for (const a of incoming.annotations) {
    const old = annotations.get(a.id);
    if (!old || a.revision > old.revision || (a.revision === old.revision && a.updated_at >= old.updated_at))
      annotations.set(a.id, a);
  }
  const versions = new Map([...current.versions, ...incoming.versions].map((v) => [v.id, v]));
  return {
    ...incoming,
    annotations: [...annotations.values()],
    versions: [...versions.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)),
  };
}

export function mergePending(bundle: ReaderBundle, pending: PendingOperation[]): ReaderBundle {
  const annotations = new Map(bundle.annotations.map((a) => [a.id, a]));
  for (const op of pending) {
    const old = annotations.get(op.annotation_id);
    annotations.set(op.annotation_id, {
      id: op.annotation_id,
      document_id: op.document_id,
      source_version_id: op.geometry_changed ? op.version_id : old?.source_version_id || op.version_id,
      data: op.data,
      quote: old?.quote || "",
      anchors: op.geometry_changed ? [] : old?.anchors || [],
      projections: op.geometry_changed ? {} : old?.projections || {},
      revision: op.base_revision + 1,
      deleted: op.deleted,
      alignment_status: "pending",
      alignment_message: op.conflict ? "其他窗口有修改，本地操作已保留" : "本地已保存，等待同步",
      updated_at: new Date(op.created).toISOString(),
    });
  }
  return { ...bundle, annotations: [...annotations.values()] };
}

function bounds(rects: Rect[]): Rect {
  const x = Math.min(...rects.map((r) => r.origin.x)),
    y = Math.min(...rects.map((r) => r.origin.y));
  return {
    origin: { x, y },
    size: {
      width: Math.max(...rects.map((r) => r.origin.x + r.size.width)) - x,
      height: Math.max(...rects.map((r) => r.origin.y + r.size.height)) - y,
    },
  };
}

export function projectedAnnotations(annotations: SharedAnnotation[], versionId: string): PdfAnnotationObject[] {
  return annotations
    .filter((a) => !a.deleted)
    .flatMap((a) => {
      const hydrate = (data: PdfAnnotationObject, suffix: string) => ({
        ...data,
        id: suffix === "source" ? data.id : `ep_${a.id}_${suffix}`,
        custom: { easyPaperId: a.id },
        created: data.created ? new Date(data.created) : undefined,
        modified: new Date(a.updated_at),
        appearanceModes: 0,
      });
      const source = a.source_version_id === versionId ? [hydrate(a.data, "source")] : [];
      const byPage = new Map<number, Projection[]>();
      for (const p of a.projections[versionId] || []) {
        if (source.length && p.page === a.data.pageIndex) continue;
        byPage.set(p.page, [...(byPage.get(p.page) || []), p]);
      }
      return [
        ...source,
        ...[...byPage].map(([pageIndex, parts]) => {
          const segmentRects = parts.flatMap((p) => p.rects);
          const rect = bounds(segmentRects);
          if (parts[0].geometry)
            return hydrate({ ...a.data, ...parts[0].geometry, pageIndex } as PdfAnnotationObject, `${pageIndex}`);
          if ([9, 10, 11, 12].includes(a.data.type)) {
            return {
              ...hydrate({ ...a.data, pageIndex, rect, segmentRects } as PdfAnnotationObject, `${pageIndex}`),
              custom: { easyPaperId: a.id, easyPaperTextAnchors: parts.map((p) => p.text_anchor || { text: p.quote }) },
            };
          }
          // Reflowed handwriting is represented by a linked note; the source ink remains intact.
          return hydrate(
            {
              type: 1,
              pageIndex,
              rect: { origin: rect.origin, size: { width: 24, height: 24 } },
              contents: a.data.contents || (a.data.type === 15 ? "关联手写批注：在批注列表中查看原笔迹" : "关联批注"),
              color: "#e7b539",
              opacity: 1,
              id: a.id,
            } as PdfAnnotationObject,
            `${pageIndex}`,
          );
        }),
      ];
    });
}
