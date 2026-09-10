import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import {
  PDFViewer as EmbedViewer,
  AnnotationPlugin,
  DocumentManagerPlugin,
  ExportPlugin,
  HistoryPlugin,
  ScrollPlugin,
  SelectionPlugin,
  ZoomMode,
  type AnnotationEvent,
  type PDFViewerConfig,
  type PdfAnnotationObject,
  type PluginRegistry,
  type Rect,
} from "@embedpdf/react-pdf-viewer";
import { Task, type PdfPageGeometry, type PdfErrorReason } from "@embedpdf/models";
import { LockModeType } from "@embedpdf/plugin-annotation";
import wasmUrl from "@embedpdf/pdfium/pdfium.wasm?url";
import chineseFont from "../../../node_modules/@embedpdf/fonts-sc/fonts/NotoSansHans-Regular.otf?url";
import { projectedAnnotations, type SharedAnnotation } from "./reader-store";
import { readerSelectionGeometry } from "./selection-geometry";
import { textAnchorRects, textRectsBounds, type TextAnchor, type TextPage } from "./text-anchor";

export type ReaderSelection = { text: string; data: PdfAnnotationObject };
export type PdfViewerHandle = {
  goToPage: (page: number, point?: { x: number; y: number }) => void;
  exportPdf: () => Promise<void>;
  getSelection: () => Promise<ReaderSelection | null>;
};
type Props = {
  src: string;
  versionId: string;
  initialPage?: number;
  annotations: SharedAnnotation[];
  onPageChange: (page: number) => void;
  onChange: (id: string, data: PdfAnnotationObject, deleted: boolean, geometryChanged: boolean) => void;
  onSelection?: (text: string) => void;
};
const geometryKeys = ["rect", "segmentRects", "inkList", "vertices", "linePoints", "rotation", "pageIndex"];
const appearanceKeys = [
  ...geometryKeys,
  "type",
  "contents",
  "strokeColor",
  "fillColor",
  "color",
  "opacity",
  "strokeWidth",
  "fontSize",
  "fontColor",
  "fontFamily",
  "textAlign",
  "verticalAlign",
];
const fingerprint = (data: PdfAnnotationObject) =>
  JSON.stringify(appearanceKeys.map((key) => (data as unknown as Record<string, unknown>)[key]));

const PdfViewer = forwardRef<PdfViewerHandle, Props>((props, ref) => {
  const callbacks = useRef(props);
  callbacks.current = props;
  const registryRef = useRef<PluginRegistry>();
  const loaded = useRef(false);
  const suppress = useRef(false);
  const ids = useRef(new Map<string, string>());
  const awaitingSave = useRef(new Set<string>());
  const previousNative = useRef(new Map<string, PdfAnnotationObject>());
  const removers = useRef<(() => void)[]>([]);
  const [error, setError] = useState("");
  const textPages = useRef(new Map<number, Promise<TextPage>>());
  const reconcileEpoch = useRef(0);
  const reconcilePending = useRef<Promise<void>>(Promise.resolve());
  const unresolvedText = useRef(false);
  const config = useMemo<PDFViewerConfig>(
    () => ({
      wasmUrl: new URL(wasmUrl, window.location.href).href,
      tabBar: "never",
      i18n: { defaultLocale: "zh-CN" },
      fonts: { ui: null, signature: null },
      fontFallback: {
        fonts: { 134: new URL(chineseFont, window.location.href).href },
        // Keep PDFium's metrically compatible Base-14 fonts. Replacing Times
        // with Noto Sans changes glyph widths, causing clipping and overlaps.
      },
      theme: { preference: "light" },
      zoom: { defaultZoomLevel: ZoomMode.FitWidth },
      documentManager: { maxDocuments: 1 },
      selection: { toleranceFactor: 1, minSelectionDragDistance: 2 },
      disabledCategories: [
        "document-open",
        "document-close",
        "document-protect",
        "security",
        "redaction",
        "signature",
        "stamp",
        "mode-insert",
        "insert-image",
        "insert-rubber-stamp",
        "insert-attachment",
        "insert-signature",
        "form",
        "page-settings",
        "annotation-link",
      ],
      annotations: { annotationAuthor: "EasyPaper", autoCommit: true },
    }),
    [],
  );

  const reconcile = useCallback(() => {
    const epoch = ++reconcileEpoch.current;
    reconcilePending.current = (async () => {
      const registry = registryRef.current;
      if (!registry || !loaded.current) return;
      const api = registry.getPlugin<AnnotationPlugin>("annotation")?.provides();
      if (!api) return;
      // Include tombstones so edits/deletions of annotations embedded in the input PDF survive reloads.
      for (const a of callbacks.current.annotations) {
        if (a.source_version_id === callbacks.current.versionId) {
          ids.current.set(a.data.id, a.id);
          awaitingSave.current.delete(a.data.id);
        }
      }
      const documents = registry.getPlugin<DocumentManagerPlugin>("document-manager")!.provides();
      const documentId = documents.getActiveDocumentId();
      const document = documentId && documents.getDocumentState(documentId)?.document;
      if (!document) return;
      let unresolved = 0;
      const objects = await Promise.all(
        projectedAnnotations(callbacks.current.annotations, callbacks.current.versionId).map(async (data) => {
          const anchors = data.custom?.easyPaperTextAnchors as TextAnchor[] | undefined;
          if (!anchors?.length) return data;
          let cached = textPages.current.get(data.pageIndex);
          if (!cached) {
            cached = (async () => {
              const engine = registry.getEngine();
              const geometry = await engine.getPageGeometry(document, document.pages[data.pageIndex]).toPromise();
              const indexes = geometry.runs.flatMap((run) =>
                run.glyphs.flatMap((glyph, i) => (glyph.flags & 3 ? [] : [run.charStart + i])),
              );
              // A single batched request retains exact PDF character indexes even
              // for ligatures and generated line breaks.
              const strings = await engine
                .getTextSlices(
                  document,
                  indexes.map((charIndex) => ({ pageIndex: data.pageIndex, charIndex, charCount: 1 })),
                )
                .toPromise();
              return { geometry, characters: indexes.map((index, i) => ({ index, text: strings[i] })) };
            })();
            textPages.current.set(data.pageIndex, cached);
            cached.catch(() => textPages.current.delete(data.pageIndex));
          }
          const page = await cached;
          const fragments = anchors.map((anchor) => textAnchorRects(page, anchor));
          if (fragments.some((rects) => !rects.length)) {
            unresolved++;
            return null;
          }
          const segmentRects = fragments.flat();
          return { ...data, rect: textRectsBounds(segmentRects), segmentRects } as PdfAnnotationObject;
        }),
      );
      if (epoch !== reconcileEpoch.current || registryRef.current !== registry) return;
      unresolvedText.current = unresolved > 0;
      setError(unresolved ? `${unresolved} 条批注尚未定位到对应文字，原始记录已保留` : "");
      const desired = new Map(objects.filter((a): a is PdfAnnotationObject => a !== null).map((a) => [a.id, a]));
      const present = new Map(
        api
          .getAnnotations()
          .filter((a) => a.commitState !== "deleted")
          .map((a) => [a.object.id, a.object]),
      );
      for (const [id, data] of present) previousNative.current.set(id, data);
      suppress.current = true;
      try {
        for (const [nativeId, data] of present) {
          if (!ids.current.has(nativeId) && !data.custom?.easyPaperId) continue;
          if (!desired.has(nativeId) && !awaitingSave.current.has(nativeId)) {
            api.deleteAnnotation(data.pageIndex, nativeId);
            registry
              .getPlugin<HistoryPlugin>("history")
              ?.provides()
              .purgeByMetadata<{ annotationIds?: string[] }>((m) => Boolean(m?.annotationIds?.includes(nativeId)));
          }
        }
        for (const [nativeId, data] of desired) {
          ids.current.set(nativeId, data.custom.easyPaperId);
          const previous = present.get(nativeId);
          if (!previous) api.importAnnotations([{ annotation: data }]);
          else if (fingerprint(previous) !== fingerprint(data)) {
            if (previous.type !== data.type) {
              api.deleteAnnotation(previous.pageIndex, nativeId);
              api.importAnnotations([{ annotation: data }]);
            } else api.updateAnnotation(data.pageIndex, nativeId, data);
            registry
              .getPlugin<HistoryPlugin>("history")
              ?.provides()
              .purgeByMetadata<{ annotationIds?: string[] }>((m) => Boolean(m?.annotationIds?.includes(nativeId)));
          }
          previousNative.current.set(nativeId, data);
        }
      } finally {
        suppress.current = false;
      }
    })().catch(() => {
      if (epoch === reconcileEpoch.current && registryRef.current) {
        unresolvedText.current = true;
        setError("批注文字定位未完成，请重新打开当前版本；原始记录已保留");
      }
    });
    return reconcilePending.current;
  }, []);
  useEffect(() => {
    void reconcile();
  }, [props.annotations, props.versionId, reconcile]);

  const onReady = useCallback(
    (registry: PluginRegistry) => {
      registryRef.current = registry;
      const engine = registry.getEngine();
      const getGeometry = engine.getPageGeometry.bind(engine);
      engine.getPageGeometry = (...args) => {
        const task = new Task<PdfPageGeometry, PdfErrorReason>();
        const original = getGeometry(...args);
        original.wait(
          (geometry) => task.resolve(readerSelectionGeometry(geometry)),
          (error) => task.fail(error),
        );
        return task;
      };
      const annotation = registry.getPlugin<AnnotationPlugin>("annotation")!.provides();
      // Both highlighting affordances select text. Freehand drawing remains a separate tool.
      removers.current.push(
        annotation.onActiveToolChange(({ documentId, tool }) => {
          const scope = annotation.forDocument(documentId);
          if (tool?.id === "inkHighlighter") {
            scope.setActiveTool("highlight");
            return;
          }
          // Existing marks must let pointer events reach text selection while a
          // text tool is active. Cursor mode restores selection/moving of marks.
          scope.setLocked({
            type:
              tool && ["highlight", "underline", "strikeout", "squiggly"].includes(tool.id)
                ? LockModeType.All
                : LockModeType.None,
          });
        }),
      );
      const documents = registry.getPlugin<DocumentManagerPlugin>("document-manager")!.provides();
      const scroll = registry.getPlugin<ScrollPlugin>("scroll")!.provides();
      removers.current.push(
        annotation.onAnnotationEvent((event: AnnotationEvent) => {
          if (event.type === "loaded") {
            loaded.current = true;
            reconcile();
            return;
          }
          if (suppress.current || event.committed) return;
          // SDK update events carry the pre-edit object and a separate patch (including undo).
          const data =
            event.type === "update"
              ? ({ ...event.annotation, ...event.patch } as PdfAnnotationObject)
              : event.annotation;
          const before = previousNative.current.get(data.id) || event.annotation;
          let id = data.custom?.easyPaperId || ids.current.get(data.id);
          if (!id) {
            id = crypto.randomUUID();
            ids.current.set(data.id, id);
          }
          const shared = callbacks.current.annotations.find((a) => a.id === id);
          const linkedNote =
            shared &&
            shared.source_version_id !== callbacks.current.versionId &&
            data.type === 1 &&
            shared.data.type !== 1;
          // Moving the linked marker must never replace the original ink or shape with a sticky note.
          const changed =
            !linkedNote &&
            (event.type === "create" ||
              (event.type === "update" &&
                geometryKeys.some(
                  (key) =>
                    JSON.stringify((before as unknown as Record<string, unknown>)[key]) !==
                    JSON.stringify((data as unknown as Record<string, unknown>)[key]),
                )));
          previousNative.current.set(data.id, data);
          if (event.type === "create") awaitingSave.current.add(data.id);
          callbacks.current.onChange(id, data, event.type === "delete", changed);
        }),
      );
      removers.current.push(
        scroll.onLayoutReady((event) => {
          loaded.current = true;
          reconcile();
          if (event.isInitial && (callbacks.current.initialPage || 1) > 1) {
            scroll.scrollToPage({
              pageNumber: Math.min(callbacks.current.initialPage!, event.totalPages),
              behavior: "instant",
            });
          }
        }),
      );
      removers.current.push(scroll.onPageChange((event) => callbacks.current.onPageChange(event.pageNumber)));
      removers.current.push(documents.onDocumentError((event) => setError(event.message || "PDF 打开失败")));
      removers.current.push(
        registry
          .getPlugin<SelectionPlugin>("selection")!
          .provides()
          .onTextRetrieved((event) => callbacks.current.onSelection?.(event.text.join("\n"))),
      );
      const activeId = documents.getActiveDocumentId();
      if (activeId && documents.getDocumentState(activeId)?.document) {
        loaded.current = true;
        reconcile();
      }
      // Install geometry correction before selection can populate its page cache.
      if (!activeId) documents.openDocumentUrl({ url: callbacks.current.src });
    },
    [reconcile],
  );
  useEffect(
    () => () => {
      removers.current.forEach((remove) => remove());
      removers.current = [];
      registryRef.current = undefined;
      reconcileEpoch.current++;
      textPages.current.clear();
    },
    [],
  );

  useImperativeHandle(
    ref,
    () => ({
      goToPage: (page, point) =>
        registryRef.current
          ?.getPlugin<ScrollPlugin>("scroll")
          ?.provides()
          .scrollToPage({ pageNumber: page, pageCoordinates: point, behavior: "instant" }),
      exportPdf: async () => {
        await reconcilePending.current;
        if (unresolvedText.current) throw new Error("部分批注尚未定位到对应文字，请完成定位后再导出");
        const registry = registryRef.current;
        if (!registry) throw new Error("PDF 尚未加载");
        const annotation = registry.getPlugin<AnnotationPlugin>("annotation")!.provides();
        const documents = registry.getPlugin<DocumentManagerPlugin>("document-manager")!.provides();
        const documentId = documents.getActiveDocumentId();
        const pdfDocument = documentId && documents.getDocumentState(documentId)?.document;
        if (!pdfDocument) throw new Error("PDF 尚未加载");
        const scope = annotation.forDocument(pdfDocument.id);
        const deadline = Date.now() + 15000;
        // In EmbedPDF 2.15, commit() resolves immediately when another batch
        // holds its lock. Await the state becoming clean, not just that task.
        while (scope.getState().hasPendingChanges) {
          if (Date.now() > deadline) throw new Error("PDF 批注仍在写入，请稍后重试");
          await scope.commit().toPromise();
          if (scope.getState().hasPendingChanges) await new Promise((resolve) => window.setTimeout(resolve, 25));
        }
        // The SDK settles failed engine writes too; don't silently export a
        // document missing a tracked annotation even if its batch reports success.
        const expected = new Map<number, string[]>();
        for (const item of scope.getAnnotations()) {
          if (item.commitState === "deleted") continue;
          const page = item.object.pageIndex;
          expected.set(page, [...(expected.get(page) || []), item.object.id]);
        }
        await Promise.all(
          [...expected].map(async ([page, ids]) => {
            const actual = await registry
              .getEngine()
              .getPageAnnotations(pdfDocument, pdfDocument.pages[page])
              .toPromise();
            const present = new Set(actual.map((a) => a.id));
            if (ids.some((id) => !present.has(id))) throw new Error("部分批注尚未写入 PDF，请稍后重试导出");
          }),
        );
        const bytes = await registry.getPlugin<ExportPlugin>("export")!.provides().saveAsCopy().toPromise();
        const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = "paper-annotated.pdf";
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
      getSelection: async () => {
        const registry = registryRef.current;
        if (!registry) return null;
        const docId = registry.getPlugin<DocumentManagerPlugin>("document-manager")!.provides().getActiveDocumentId();
        if (!docId) return null;
        const api = registry.getPlugin<SelectionPlugin>("selection")!.provides().forDocument(docId);
        const rects = api.getHighlightRects();
        const pages = Object.keys(rects);
        if (pages.length !== 1 || !rects[Number(pages[0])]?.length) return null;
        const pageIndex = Number(pages[0]);
        const segmentRects = rects[pageIndex];
        const rect = api.getBoundingRectForPage(pageIndex) as Rect;
        const text = (await api.getSelectedText().toPromise()).join("\n");
        return {
          text,
          data: {
            id: crypto.randomUUID(),
            type: 9,
            pageIndex,
            rect,
            segmentRects,
            opacity: 0.45,
            strokeColor: "#f4ce46",
          },
        };
      },
    }),
    [],
  );
  return (
    <div className="pdf-viewer-container embed-reader">
      {error ? (
        <div className="reader-inline-error" role="alert">
          {error}
        </div>
      ) : null}
      <EmbedViewer config={config} onReady={onReady} style={{ width: "100%", height: "100%" }} />
    </div>
  );
});
PdfViewer.displayName = "PdfViewer";
export default PdfViewer;
