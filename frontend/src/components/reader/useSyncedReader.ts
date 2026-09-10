import { useCallback, useEffect, useRef, useState } from "react";
import type { PdfAnnotationObject } from "@embedpdf/react-pdf-viewer";
import api from "@/lib/api";
import {
  cacheGet,
  cacheSet,
  mergePending,
  mergeServer,
  pendingOperations,
  storeOperation,
  type PendingOperation,
  type ReaderBundle,
  type SharedAnnotation,
} from "./reader-store";

export function useSyncedReader(taskId: string) {
  const [bundle, setBundle] = useState<ReaderBundle | null>(null);
  const [pending, setPending] = useState<PendingOperation[]>([]);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const server = useRef<ReaderBundle | null>(null);
  const busy = useRef(false);
  const writeChain = useRef(Promise.resolve());
  const unsaved = useRef(0);
  const cacheKey = `task:${localStorage.getItem("email") || "account"}:${taskId}`;
  const mounted = useRef(true);

  const display = useCallback(
    async (data: ReaderBundle) => {
      const operations = await pendingOperations(data.user_id, data.document_id);
      if (!mounted.current) return;
      data = mergeServer(server.current, data);
      server.current = data;
      setBundle(mergePending(data, operations));
      setPending(operations);
      await cacheSet(cacheKey, data);
    },
    [cacheKey],
  );

  const flush = useCallback(async () => {
    if (busy.current || !server.current) return;
    busy.current = true;
    try {
      const data = server.current;
      const ops = await pendingOperations(data.user_id, data.document_id);
      const blocked = new Set(ops.filter((p) => p.conflict).map((p) => p.annotation_id));
      for (const op of ops) {
        if (blocked.has(op.annotation_id)) continue;
        try {
          const { data: saved } = await api.put<SharedAnnotation>(
            `/api/reader/documents/${data.document_id}/annotations/${op.annotation_id}`,
            op,
          );
          // Save the acknowledgement before deleting the durable retry operation.
          const current: ReaderBundle = server.current!;
          const next = mergeServer(current, { ...current, annotations: [saved] });
          await cacheSet(cacheKey, next);
          server.current = mergeServer(server.current, next);
          await storeOperation(op, true);
          if (mounted.current) setSaveError("");
        } catch (e) {
          const status = (e as { response?: { status?: number } }).response?.status;
          if (status === 409) {
            await storeOperation({ ...op, conflict: true });
            blocked.add(op.annotation_id);
          } else {
            if (mounted.current)
              setSaveError(status === 422 ? "批注未被服务器接受，本地副本已保留" : "本地已保存，连接恢复后继续同步");
            break;
          }
        }
      }
      if (server.current) await display(server.current);
    } catch {
      if (mounted.current) setSaveError("浏览器存储不可用，请保持页面打开并导出带批注 PDF");
    } finally {
      busy.current = false;
    }
  }, [cacheKey, display]);

  const refresh = useCallback(async () => {
    const current = server.current;
    if (!current || busy.current) return;
    try {
      const { data } = await api.get<ReaderBundle>(`/api/reader/documents/${current.document_id}`);
      await writeChain.current;
      if (!busy.current) await display(data);
    } catch {
      /* Retain the local document and unsent operations. */
    }
  }, [display]);

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    void (async () => {
      try {
        const cached = await cacheGet<ReaderBundle>(cacheKey);
        if (cached && !cancelled) await display(cached);
      } catch {
        setSaveError("浏览器存储不可用；批注保存后请确认服务器状态");
      }
      try {
        const { data } = await api.get<ReaderBundle>(`/api/reader/tasks/${taskId}`);
        if (!cancelled) {
          await display(data);
          await flush();
        }
      } catch {
        if (!cancelled && !server.current) setError("阅读器加载失败，请重试");
      }
    })();
    const online = () => {
      void flush().then(refresh);
    };
    const guard = (event: BeforeUnloadEvent) => {
      if (unsaved.current > 0) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("online", online);
    window.addEventListener("beforeunload", guard);
    return () => {
      cancelled = true;
      mounted.current = false;
      window.removeEventListener("online", online);
      window.removeEventListener("beforeunload", guard);
    };
  }, [taskId, cacheKey, display, flush, refresh]);

  const syncing =
    pending.length > 0 || !!bundle?.annotations.some((a) => !a.deleted && a.alignment_status === "pending");
  useEffect(() => {
    let polling = false;
    const timer = window.setInterval(
      async () => {
        if (polling) return;
        polling = true;
        try {
          await flush();
          await refresh();
        } finally {
          polling = false;
        }
      },
      syncing ? 1000 : 5000,
    );
    return () => window.clearInterval(timer);
  }, [syncing, flush, refresh]);

  const change = useCallback(
    (id: string, versionId: string, data: PdfAnnotationObject, deleted = false, geometryChanged = true) => {
      unsaved.current++;
      writeChain.current = writeChain.current
        .then(async () => {
          const current = server.current;
          if (!current) throw new Error("Document not loaded");
          const ops = await pendingOperations(current.user_id, current.document_id);
          const view = mergePending(current, ops);
          const old = view.annotations.find((a) => a.id === id);
          const stored =
            old && !geometryChanged
              ? ({
                  ...old.data,
                  ...Object.fromEntries(
                    Object.entries(data).filter(
                      ([key]) =>
                        !["rect", "segmentRects", "inkList", "pageIndex", "id", "custom", "type"].includes(key),
                    ),
                  ),
                } as PdfAnnotationObject)
              : data;
          const op: PendingOperation = {
            operation_id: crypto.randomUUID(),
            annotation_id: id,
            document_id: current.document_id,
            user_id: current.user_id,
            base_revision: old?.revision || 0,
            version_id: !geometryChanged && old ? old.source_version_id : versionId,
            data: stored,
            deleted,
            geometry_changed: geometryChanged,
            created: Math.max(Date.now(), ...ops.map((p) => p.created + 1)),
          };
          await storeOperation(op);
          unsaved.current--;
          await display(current);
        })
        .catch(() => {
          setSaveError("批注尚未保存：浏览器存储失败。请保持页面打开并导出 PDF");
        });
      void writeChain.current.then(flush);
    },
    [display, flush],
  );

  const resolveConflict = useCallback(
    async (id: string, keepLocal: boolean) => {
      const current = server.current;
      if (!current) return;
      const ops = (await pendingOperations(current.user_id, current.document_id)).filter((p) => p.annotation_id === id);
      if (keepLocal && ops.length) {
        const last = ops[ops.length - 1];
        await storeOperation({
          ...last,
          operation_id: crypto.randomUUID(),
          annotation_id: crypto.randomUUID(),
          data: { ...last.data, id: crypto.randomUUID() },
          base_revision: 0,
          conflict: false,
          deleted: false,
          geometry_changed: true,
          created: Date.now(),
        });
      }
      for (const op of ops) await storeOperation(op, true);
      await refresh();
      await flush();
    },
    [flush, refresh],
  );

  const reopen = useCallback(async () => {
    const { data } = await api.get<ReaderBundle>(`/api/reader/tasks/${taskId}`);
    await display(data);
  }, [taskId, display]);

  return {
    bundle,
    pending,
    error,
    saveError,
    change,
    refresh,
    flush,
    resolveConflict,
    reopen,
  };
}
