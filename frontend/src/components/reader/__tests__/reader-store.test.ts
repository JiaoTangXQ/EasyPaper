import "fake-indexeddb/auto";
import { describe, expect, it } from "vitest";
import {
  cacheGet,
  cacheSet,
  mergePending,
  mergeServer,
  pendingOperations,
  projectedAnnotations,
  storeOperation,
  type PendingOperation,
  type ReaderBundle,
  type SharedAnnotation,
} from "../reader-store";

const rect = { origin: { x: 20, y: 40 }, size: { width: 80, height: 14 } };
const mark: SharedAnnotation = {
  id: "shared",
  document_id: "doc",
  source_version_id: "chinese",
  revision: 1,
  deleted: false,
  quote: "内存减少30%",
  anchors: ["unit"],
  alignment_status: "matched",
  alignment_message: "已匹配",
  updated_at: new Date().toISOString(),
  data: { id: "native", type: 9, pageIndex: 0, rect, segmentRects: [rect], opacity: 0.5, strokeColor: "#ffff00" },
  projections: {
    bilingual: [
      { page: 0, unit_id: "en", quote: "30% less memory", rects: [rect], method: "exact" },
      { page: 1, unit_id: "zh", quote: "内存减少30%", rects: [rect], method: "exact" },
    ],
  },
};
const bundle: ReaderBundle = {
  document_id: "doc",
  user_id: 7,
  title: "paper",
  versions: [],
  annotations: [mark],
  builds: [],
};

describe("shared annotation projections", () => {
  it("keeps one logical annotation and stable native identity in the source", () => {
    expect(projectedAnnotations([mark], "chinese")[0].id).toBe("native");
    const dual = projectedAnnotations([mark], "bilingual");
    expect(dual.map((a) => a.pageIndex)).toEqual([0, 1]);
    expect(dual.every((a) => a.custom.easyPaperId === "shared")).toBe(true);
    expect(new Set(dual.map((a) => a.id)).size).toBe(2);
  });
  it("shows the other language when the mark was created inside the bilingual PDF", () => {
    const dualSource = { ...mark, source_version_id: "bilingual", data: { ...mark.data, pageIndex: 1 } };
    const projected = projectedAnnotations([dualSource], "bilingual");
    expect(projected.map((a) => a.pageIndex).sort()).toEqual([0, 1]);
    expect(projected.find((a) => a.pageIndex === 1)?.id).toBe("native");
  });
  it("propagates color and deletion to every projection", () => {
    const changed = { ...mark, data: { ...mark.data, strokeColor: "#118855" } };
    expect(
      projectedAnnotations([changed], "bilingual").every(
        (a) => (a as { strokeColor: string }).strokeColor === "#118855",
      ),
    ).toBe(true);
    expect(projectedAnnotations([{ ...mark, deleted: true }], "bilingual")).toEqual([]);
  });
  it("preserves ink in the source and represents reflowed ink with a linked note", () => {
    const ink = {
      ...mark,
      data: {
        ...mark.data,
        type: 15 as const,
        opacity: 1,
        inkList: [
          {
            points: [
              { x: 21, y: 42 },
              { x: 70, y: 45 },
            ],
          },
        ],
        strokeWidth: 2,
      },
    };
    expect(projectedAnnotations([ink], "chinese")[0].type).toBe(15);
    expect(projectedAnnotations([ink], "bilingual").every((a) => a.type === 1)).toBe(true);
    expect(ink.data.inkList[0].points).toHaveLength(2);
  });
});

describe("durable offline operations", () => {
  it("does not let late polls or retried acknowledgements roll back saved changes", () => {
    const newer = { ...mark, revision: 3, deleted: true, updated_at: "2026-09-09T10:00:00" };
    const current = { ...bundle, annotations: [newer] };
    expect(mergeServer(current, bundle).annotations[0]).toEqual(newer);
    expect(mergeServer(current, { ...bundle, annotations: [] }).annotations[0]).toEqual(newer);
    const aligned = { ...newer, updated_at: "2026-09-09T11:00:00", alignment_message: "Updated projection" };
    expect(mergeServer(current, { ...bundle, annotations: [aligned] }).annotations[0]).toEqual(aligned);
  });
  it("keeps unsent operations through a cache reload and isolates users", async () => {
    const operation: PendingOperation = {
      operation_id: "offline-create",
      annotation_id: "offline-mark",
      document_id: "doc",
      user_id: 7,
      base_revision: 0,
      version_id: "chinese",
      data: mark.data,
      deleted: false,
      geometry_changed: true,
      created: Date.now(),
    };
    await cacheSet("offline-paper", bundle);
    await storeOperation(operation);
    const restored = await cacheGet<ReaderBundle>("offline-paper");
    const pending = await pendingOperations(7, "doc");
    expect(mergePending(restored!, pending).annotations.find((a) => a.id === "offline-mark")?.revision).toBe(1);
    expect(await pendingOperations(8, "doc")).toEqual([]);
    await storeOperation(operation, true);
    expect(await pendingOperations(7, "doc")).toEqual([]);
  });
  it("keeps a pending edit and deletion visible over a stale server snapshot", () => {
    const op: PendingOperation = {
      operation_id: "edit",
      annotation_id: mark.id,
      document_id: "doc",
      user_id: 7,
      base_revision: 1,
      version_id: "chinese",
      data: { ...mark.data, contents: "local note" },
      deleted: true,
      geometry_changed: false,
      created: Date.now(),
      conflict: true,
    };
    const restored = mergePending(bundle, [op]).annotations[0];
    expect(restored.deleted).toBe(true);
    expect(restored.data.contents).toBe("local note");
    expect(restored.projections).toEqual(mark.projections);
    expect(restored.alignment_message).toContain("保留");
  });
});
