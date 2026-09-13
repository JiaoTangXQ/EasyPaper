import { lazy, Suspense, useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import {
  AlertCircle,
  ArrowLeft,
  BookOpen,
  Check,
  Download,
  FileText,
  Highlighter,
  Link2,
  Loader2,
  Maximize,
  Minimize,
  RefreshCw,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import type { PdfViewerHandle } from "@/components/reader/PdfViewer";
import PaperChat from "@/components/reader/PaperChat";
import {
  cacheGet,
  cacheSet,
  versionNames,
  type ReaderMode,
  type ReaderVersion,
  type SharedAnnotation,
} from "@/components/reader/reader-store";
import { useSyncedReader } from "@/components/reader/useSyncedReader";
import { useFullscreenChrome } from "@/components/reader/useFullscreenChrome";
import "@/components/reader/reader.css";

const PdfViewer = lazy(() => import("@/components/reader/PdfViewer"));
type Workspace = {
  document: { title: string; page_count: number; blocks: { id: string; page: number }[] };
  state: { mode: ReaderMode; block_id: string };
  has_result: boolean;
  pdf_message: string;
  paper_id: string;
};
const modes: ReaderMode[] = ["original", "chinese", "simple", "bilingual"];
type ReaderPanel = "notes" | "overview";

export default function Reader() {
  const { taskId = "" } = useParams<{ taskId: string }>();
  return <ReaderWorkspace key={taskId} taskId={taskId} />;
}

function ReaderWorkspace({ taskId }: { taskId: string }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const reader = useSyncedReader(taskId);
  const { bundle } = reader;
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [mode, setMode] = useState<ReaderMode>("original");
  const [revision, setRevision] = useState("");
  const [panel, setPanel] = useState<ReaderPanel | null>(searchParams.get("panel") === "summary" ? "overview" : null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const workspaceElement = useRef<HTMLDivElement>(null);
  const chrome = useFullscreenChrome(workspaceElement, isFullscreen);
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 1000px)").matches);
  const panelTrigger = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const summaryRequested = useRef(false);
  const [summaryError, setSummaryError] = useState("");
  const [pdf, setPdf] = useState<{ versionId: string; url: string; page: number } | null>(null);
  const [pdfError, setPdfError] = useState("");
  const [page, setPage] = useState(1);
  const [selection, setSelection] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [generating, setGenerating] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const restoreInput = useRef<HTMLInputElement>(null);
  const viewerRef = useRef<PdfViewerHandle>(null);
  const workspaceRef = useRef(workspace);
  workspaceRef.current = workspace;
  const requestedJump = useRef<{ versionId: string; page: number; point?: { x: number; y: number } }>();
  const positions = useRef(new Map<string, number>());
  const positionTimer = useRef<number>();
  const currentVersions = bundle?.versions.filter((v) => v.kind === mode) || [];
  const version = currentVersions.find((v) => v.id === revision) || currentVersions[0];
  const versionId = version?.id,
    versionUrl = version?.url,
    pageCount = version?.page_count;
  const userId = bundle?.user_id;
  const versionRef = useRef(version);
  versionRef.current = version;
  const awaitingResult = workspace !== null && !workspace.has_result;
  const reopen = reader.reopen;
  const build = bundle?.builds.find((b) => b.kind === mode);
  const isBuilding = generating || build?.status === "running";

  useEffect(() => {
    const update = () =>
      setIsFullscreen(
        Boolean(document.fullscreenElement && workspaceElement.current?.contains(document.fullscreenElement)),
      );
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, []);

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else if (workspaceElement.current?.requestFullscreen) {
        await workspaceElement.current.requestFullscreen();
      } else {
        toast.error("当前浏览器不支持全屏阅读");
      }
    } catch {
      toast.error("未能切换全屏，请重试");
    }
  };

  useEffect(() => {
    let cancelled = false;
    void api
      .get<Workspace>(`/api/reading/${taskId}`)
      .then(({ data }) => {
        if (cancelled) return;
        setWorkspace(data);
        setMode(data.state.mode || "original");
        const block = data.document.blocks.find((b) => b.id === data.state.block_id);
        if (block) setPage(block.page);
      })
      .catch(() => {
        /* Archived reader remains usable if the legacy task data cannot be read. */
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  useEffect(() => {
    if (!awaitingResult) return;
    const timer = window.setInterval(() => {
      void api
        .get(`/api/status/${taskId}`)
        .then(({ data }) => {
          setWorkspace((old) =>
            old ? { ...old, has_result: Boolean(data.has_result), pdf_message: data.message } : old,
          );
          if (data.has_result) void reopen();
        })
        .catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [taskId, awaitingResult, reopen]);

  const loadSummary = useCallback(async () => {
    if (summaryRequested.current) return;
    summaryRequested.current = true;
    setSummaryLoading(true);
    setSummaryError("");
    try {
      const { data } = await api.post(`/api/reading/${taskId}/summary`);
      setSummary(data);
    } catch (err) {
      summaryRequested.current = false;
      setSummaryError(getApiErrorMessage(err, "概览生成失败，请重试。"));
    } finally {
      setSummaryLoading(false);
    }
  }, [taskId]);
  useEffect(() => {
    if (panel === "overview") void loadSummary();
  }, [panel, loadSummary]);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1000px)");
    const update = () => setCompact(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const changePanel = (next: ReaderPanel | null) => {
    if (next) setChatOpen(false);
    if (next && !panel)
      panelTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setPanel(next);
    if (!next) queueMicrotask(() => panelTrigger.current?.focus());
  };
  const panelOpen = panel !== null;
  useEffect(() => {
    if (compact && panelOpen) panelRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [compact, panelOpen]);

  useEffect(() => {
    if (!versionId || !versionUrl || !pageCount || userId === undefined) {
      setPdf(null);
      return;
    }
    let cancelled = false,
      url = "";
    setPdf(null);
    setPdfError("");
    setSelection("");
    const cacheKey = `pdf:${userId}:${versionId}`;
    void (async () => {
      let blob: Blob;
      try {
        blob = (await api.get<Blob>(versionUrl, { responseType: "blob" })).data;
        // Offline PDF caching is optional; annotation operations have their own durable store.
        void cacheSet(cacheKey, blob).catch(() => undefined);
      } catch (error) {
        const cached = await cacheGet<Blob>(cacheKey).catch(() => undefined);
        if (!cached) throw error;
        blob = cached;
      }
      const remembered = await cacheGet<number>(`position:${userId}:${versionId}`).catch(() => undefined);
      if (cancelled) return;
      const next = Math.max(
        1,
        Math.min(
          pageCount,
          requestedJump.current?.versionId === versionId
            ? requestedJump.current.page
            : positions.current.get(versionId) || remembered || 1,
        ),
      );
      url = URL.createObjectURL(blob);
      setPage(next);
      setPdf({ versionId, url, page: next });
    })().catch((err) => {
      if (!cancelled) setPdfError(getApiErrorMessage(err, "PDF 加载失败，请重新打开此版本"));
    });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [versionId, versionUrl, pageCount, userId]);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPanel(null);
    };
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("keydown", close);
      window.clearTimeout(positionTimer.current);
    };
  }, []);

  const onPageChange = useCallback(
    (next: number) => {
      const version = versionRef.current;
      if (!version || userId === undefined) return;
      setPage(next);
      positions.current.set(version.id, next);
      void cacheSet(`position:${userId}:${version.id}`, next).catch(() => undefined);
      window.clearTimeout(positionTimer.current);
      const sourcePage = (version.origin_pages?.[next - 1] ?? next - 1) + 1;
      const block = workspaceRef.current?.document.blocks.find((b) => b.page === sourcePage);
      if (block)
        positionTimer.current = window.setTimeout(() => {
          void api
            .patch(`/api/reading/${taskId}/state`, { block_id: block.id, mode: version.kind })
            .catch(() => undefined);
        }, 700);
    },
    [userId, taskId],
  );

  const switchMode = (next: ReaderMode) => {
    const sourcePage = version?.origin_pages?.[page - 1];
    const target = bundle?.versions.find((v) => v.kind === next);
    const targetPage = sourcePage == null ? -1 : (target?.origin_pages?.indexOf(sourcePage) ?? -1);
    if (target && targetPage >= 0) {
      positions.current.set(target.id, targetPage + 1);
      requestedJump.current = { versionId: target.id, page: targetPage + 1 };
    }
    setRevision("");
    setMode(next);
    void api.patch(`/api/reading/${taskId}/state`, { mode: next }).catch(() => undefined);
  };
  const jump = (annotation: SharedAnnotation, source = false) => {
    if (!bundle) return;
    const projection = !source && version ? annotation.projections[version.id]?.[0] : undefined;
    const target = projection ? version! : bundle.versions.find((v) => v.id === annotation.source_version_id);
    if (!target) {
      toast.error("原始版本不可用，批注内容仍保留");
      return;
    }
    const nextPage = (projection?.page ?? annotation.data.pageIndex) + 1;
    const point = projection?.rects[0]?.origin || annotation.data.rect.origin;
    requestedJump.current = { versionId: target.id, page: nextPage, point };
    positions.current.set(target.id, nextPage);
    setMode(target.kind);
    setRevision(target.id);
    if (version?.id === target.id) viewerRef.current?.goToPage(nextPage, point);
    if (compact) changePanel(null);
  };
  const generate = async () => {
    if (!bundle || mode === "original") return;
    setGenerating(true);
    try {
      await api.post(`/api/reader/documents/${bundle.document_id}/versions/${mode}`);
      await reader.refresh();
    } catch (err) {
      toast.error(getApiErrorMessage(err, "生成失败，请重试"));
    } finally {
      setGenerating(false);
    }
  };
  const download = async (path: string, name: string) => {
    try {
      const { data } = await api.get(path, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "下载失败"));
    }
  };
  const linkHere = async (annotation: SharedAnnotation) => {
    if (!bundle || !version) return;
    try {
      const selected = await viewerRef.current?.getSelection();
      if (!selected?.text) {
        toast.error("请先在当前版本选中对应文字，再点关联此处");
        return;
      }
      await api.put(`/api/reader/documents/${bundle.document_id}/annotations/${annotation.id}/link`, {
        base_revision: annotation.revision,
        version_id: version.id,
        data: selected.data,
      });
      await reader.refresh();
      toast.success("对应关系已保存");
    } catch (err) {
      toast.error(getApiErrorMessage(err, "关联失败，请先同步批注后重试"));
    }
  };
  const restoreBackup = async (file: File) => {
    if (!bundle) return;
    setRestoring(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post(`/api/reader/documents/${bundle.document_id}/restore`, form);
      await reader.refresh();
      toast.success(`已恢复 ${data.restored} 条批注；${data.skipped} 条已有批注保留当前修改`);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "备份导入失败"));
    } finally {
      setRestoring(false);
      if (restoreInput.current) restoreInput.current.value = "";
    }
  };

  if (reader.error)
    return (
      <main className="reader-empty">
        <FileText size={36} />
        <h1>无法打开阅读器</h1>
        <p>{reader.error}</p>
        <Button onClick={() => window.location.reload()}>重试</Button>
      </main>
    );
  if (!bundle)
    return (
      <main className="reader-empty">
        <Loader2 className="spin" size={28} />
        <p>正在载入论文与批注…</p>
      </main>
    );
  const active = bundle.annotations.filter((a) => !a.deleted);
  const filtered = bundle.annotations
    .filter((a) => {
      if (filter === "deleted" ? !a.deleted : a.deleted) return false;
      if (filter === "unmatched" && a.alignment_status === "matched") return false;
      if (filter === "highlight" && ![9, 10, 11, 12].includes(a.data.type)) return false;
      if (filter === "ink" && ![4, 5, 6, 7, 8, 15].includes(a.data.type)) return false;
      if (filter === "note" && ![1, 3].includes(a.data.type)) return false;
      return `${a.quote} ${a.data.contents || ""}`.toLowerCase().includes(query.toLowerCase());
    })
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const conflicts = [...new Set(reader.pending.filter((p) => p.conflict).map((p) => p.annotation_id))];
  const matching = active.filter((a) => a.alignment_status === "pending").length;
  const retrying = active.filter((a) => a.alignment_status === "partial" && !a.retry_exhausted).length;
  const partial = active.filter((a) => a.alignment_status === "partial" && a.retry_exhausted).length;
  const saveStatus =
    reader.saveError || (reader.pending.length ? `本地已保存 · ${reader.pending.length} 项待上传` : "已保存到服务器");
  const matchStatus = matching
    ? `正在匹配 ${matching} 条批注${retrying ? ` · ${retrying} 条将自动重试` : ""}`
    : retrying
      ? `${retrying} 条批注将自动重试`
      : partial
        ? `${partial} 条批注的部分内容无法确认对应`
        : "跨版本匹配完成";

  return (
    <div
      ref={workspaceElement}
      className="reader-workspace synced-workspace"
      data-fullscreen={isFullscreen || undefined}
      data-chrome-hidden={(isFullscreen && !chrome.visible) || undefined}
      style={
        {
          "--reader-chrome-height": `${chrome.headerHeight}px`,
          "--reader-native-chrome-height": `${chrome.toolbarHeight}px`,
        } as CSSProperties
      }
      onKeyDown={(event) => {
        if (event.key === "Escape" && panel) {
          event.preventDefault();
          changePanel(null);
        }
      }}
    >
      {isFullscreen ? (
        <button
          className="reader-chrome-reveal"
          aria-label="显示阅读工具栏"
          aria-expanded={chrome.visible}
          onPointerEnter={chrome.reveal}
          onFocus={chrome.reveal}
          onClick={chrome.reveal}
        />
      ) : null}
      <div className="reader-chrome" ref={chrome.chromeRef}>
        <header className="reader-topbar synced-topbar">
          <div className="reader-brand">
            <Button variant="ghost" size="icon" aria-label="返回文档库" onClick={() => navigate("/dashboard")}>
              <ArrowLeft size={18} />
            </Button>
            <h1 title={workspace?.document.title || bundle.title}>{workspace?.document.title || bundle.title}</h1>
          </div>
          <nav className="reader-version-switch" aria-label="阅读版本">
            {modes.map((item) => (
              <button key={item} aria-pressed={mode === item} onClick={() => switchMode(item)}>
                {versionNames[item]}
                {!bundle.versions.some((v) => v.kind === item) ? (
                  <span className="version-unready">
                    {bundle.builds.some((b) => b.kind === item && b.status === "running") ? "生成中" : "待生成"}
                  </span>
                ) : null}
              </button>
            ))}
          </nav>
          <div className="reader-actions">
            <Button
              size="sm"
              variant={panel === "overview" ? "secondary" : "ghost"}
              aria-label="论文概览"
              aria-expanded={panel === "overview"}
              onClick={() => changePanel(panel === "overview" ? null : "overview")}
            >
              <FileText size={16} />
              <span className="desktop-label">概览</span>
            </Button>
            <Button
              variant={panel === "notes" ? "secondary" : "outline"}
              size="sm"
              onClick={() => changePanel(panel === "notes" ? null : "notes")}
              aria-expanded={panel === "notes"}
            >
              <Highlighter size={16} />
              批注 {active.length}
            </Button>
            <Button
              variant="outline"
              size="sm"
              aria-label="带批注 PDF"
              disabled={!pdf}
              onClick={() =>
                void viewerRef.current?.exportPdf().catch((err) => toast.error(getApiErrorMessage(err, "导出失败")))
              }
            >
              <Download size={16} />
              <span className="desktop-label">带批注 PDF</span>
            </Button>
            <Button
              variant={isFullscreen ? "secondary" : "outline"}
              size="sm"
              aria-label={isFullscreen ? "退出全屏" : "全屏阅读"}
              aria-pressed={isFullscreen}
              title={isFullscreen ? "退出全屏（Esc）" : "全屏阅读"}
              onClick={() => void toggleFullscreen()}
            >
              {isFullscreen ? <Minimize size={16} /> : <Maximize size={16} />}
              <span className="desktop-label">{isFullscreen ? "退出全屏" : "全屏"}</span>
            </Button>
          </div>
        </header>
        <div className="reader-savebar">
          <div className="reader-persistence" role="status">
            <span className={reader.saveError || reader.pending.length ? "save-pending" : "save-complete"}>
              {reader.pending.length ? (
                <Loader2 className="spin" size={13} />
              ) : reader.saveError ? (
                <AlertCircle size={13} />
              ) : (
                <Check size={13} />
              )}
              {saveStatus}
            </span>
            <button
              className={matching || retrying || partial ? "save-pending" : "save-muted"}
              onClick={() => {
                setFilter(matching || retrying || partial ? "unmatched" : "all");
                changePanel("notes");
              }}
            >
              {matching ? <Loader2 className="spin" size={13} /> : partial ? <AlertCircle size={13} /> : null}
              {matchStatus}
            </button>
          </div>
          <span className="reader-version-detail">
            {version ? `${versionNames[version.kind]} · 第 ${page} / ${version.page_count} 页` : versionNames[mode]}
          </span>
          {currentVersions.length > 1 ? (
            <select aria-label="文件修订" value={version?.id} onChange={(e) => setRevision(e.target.value)}>
              {currentVersions.map((v, i) => (
                <option key={v.id} value={v.id}>
                  {i === 0 ? "最新修订" : "历史修订"} · {new Date(v.created_at + "Z").toLocaleString()}
                </option>
              ))}
            </select>
          ) : null}
        </div>
        {conflicts.length ? (
          <div className="reader-conflicts" role="alert">
            {conflicts.map((id) => (
              <div key={id}>
                <span>其他窗口修改了同一条批注，本地修改仍保留。</span>
                <button onClick={() => void reader.resolveConflict(id, true)}>将本地修改另存一份</button>
                <button onClick={() => void reader.resolveConflict(id, false)}>采用服务器版本</button>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <div className={`reader-layout ${panel ? "ask-open" : ""}`}>
        <main
          className="pdf-reading"
          aria-label="论文阅读区"
          ref={(node) => {
            node?.toggleAttribute("inert", compact && panelOpen);
          }}
          aria-hidden={(compact && panelOpen) || undefined}
        >
          <div className="pdf-frame-wrap">
            {!version ? (
              <div className="pdf-empty">
                <BookOpen size={34} />
                <h2>{versionNames[mode]}尚未生成</h2>
                <p>
                  {build?.error ||
                    (isBuilding ? "生成完成后，会自动匹配已保存的批注。" : "生成此版本后，可与其他版本共享批注。")}
                </p>
                <Button disabled={isBuilding || mode === "original"} onClick={() => void generate()}>
                  {isBuilding ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                  {isBuilding ? "正在生成…" : `生成${versionNames[mode]}`}
                </Button>
                {mode !== "original" ? (
                  <button className="reader-text-button" onClick={() => switchMode("original")}>
                    先读原文
                  </button>
                ) : null}
              </div>
            ) : pdfError ? (
              <div className="pdf-empty" role="alert">
                <p>{pdfError}</p>
                <Button onClick={() => window.location.reload()}>重新加载</Button>
              </div>
            ) : pdf?.versionId === version.id ? (
              <Suspense
                fallback={
                  <div className="pdf-loading">
                    <Loader2 className="spin" size={22} />
                    正在加载阅读工具…
                  </div>
                }
              >
                <PdfViewer
                  key={version.id}
                  ref={viewerRef}
                  src={pdf.url}
                  versionId={version.id}
                  initialPage={pdf.page}
                  onReady={() => {
                    const destination = requestedJump.current;
                    if (destination?.versionId === version.id) {
                      viewerRef.current?.goToPage(destination.page, destination.point);
                      requestedJump.current = undefined;
                    }
                  }}
                  annotations={bundle.annotations}
                  embeddedAnnotations={version.embedded_annotations}
                  fullscreen={isFullscreen}
                  chromeVisible={chrome.visible}
                  onToolbarHeight={chrome.setToolbarHeight}
                  onToolbarInteraction={chrome.holdForMenu}
                  onPageChange={onPageChange}
                  onSelection={setSelection}
                  onChange={(id, data, deleted, geometry) => reader.change(id, version.id, data, deleted, geometry)}
                />
              </Suspense>
            ) : (
              <div className="pdf-loading">
                <Loader2 className="spin" size={22} />
                正在打开完整页面…
              </div>
            )}
          </div>
        </main>
        {panel ? (
          <aside
            ref={panelRef}
            className="assistant-panel reader-sidepanel"
            aria-label={panel === "notes" ? "共享批注" : "论文概览"}
          >
            <div className="assistant-head">
              <h2>{panel === "notes" ? "共享批注" : "论文概览"}</h2>
              <button onClick={() => changePanel(null)} aria-label={panel === "notes" ? "关闭批注" : "关闭概览"}>
                <X size={18} />
              </button>
            </div>
            <nav className="reader-panel-tabs" aria-label="阅读辅助类型">
              {(
                [
                  ["overview", "概览"],
                  ["notes", "批注"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  aria-label={`查看${label}`}
                  aria-pressed={panel === value}
                  onClick={() => changePanel(value)}
                >
                  {label}
                </button>
              ))}
            </nav>
            {panel === "notes" ? (
              <>
                <div className="annotation-filters">
                  <input
                    aria-label="搜索批注"
                    placeholder="搜索摘录或笔记"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  <select aria-label="批注类型" value={filter} onChange={(e) => setFilter(e.target.value)}>
                    <option value="all">全部批注</option>
                    <option value="unmatched">跨版本待匹配</option>
                    <option value="highlight">文字标记</option>
                    <option value="note">笔记</option>
                    <option value="ink">手写与圈画</option>
                    <option value="deleted">已删除 · 可恢复</option>
                  </select>
                </div>
                <div className="annotation-list">
                  {filtered.length ? (
                    filtered.map((annotation) => (
                      <AnnotationRow
                        key={annotation.id}
                        annotation={annotation}
                        source={bundle.versions.find((v) => v.id === annotation.source_version_id)}
                        onJump={(source) => jump(annotation, source)}
                        onLink={() => void linkHere(annotation)}
                        onRetry={() =>
                          void api
                            .post(`/api/reader/documents/${bundle.document_id}/annotations/${annotation.id}/align`)
                            .then(reader.refresh)
                            .catch(() => toast.error("重试失败"))
                        }
                        onChange={(data, deleted) =>
                          reader.change(annotation.id, annotation.source_version_id, data, deleted, false)
                        }
                      />
                    ))
                  ) : (
                    <div className="annotation-empty">
                      <Highlighter size={26} />
                      <p>
                        {filter === "deleted"
                          ? "没有已删除的批注"
                          : filter === "unmatched"
                            ? "没有待匹配的批注"
                            : query
                              ? "没有匹配的批注，试试其他关键词。"
                              : "选中文字添加高亮，或用工具栏在页面上圈画。"}
                      </p>
                      <p>批注会自动保存。无法定位的版本可选中文字后手动关联。</p>
                    </div>
                  )}
                </div>
                <footer className="annotation-footer">
                  <button
                    onClick={() =>
                      void download(`/api/reader/documents/${bundle.document_id}/archive`, "paper-with-annotations.zip")
                    }
                  >
                    <Download size={14} />
                    备份论文与批注
                  </button>
                  <button
                    onClick={() =>
                      void download(
                        `/api/reader/documents/${bundle.document_id}/annotations/export`,
                        "paper-annotations.json",
                      )
                    }
                  >
                    导出批注数据
                  </button>
                  <button disabled={restoring} onClick={() => restoreInput.current?.click()}>
                    {restoring ? "正在导入…" : "导入本篇备份"}
                  </button>
                  <input
                    hidden
                    ref={restoreInput}
                    type="file"
                    accept=".zip,application/zip"
                    aria-label="导入论文备份"
                    onChange={(e) => {
                      if (e.target.files?.[0]) void restoreBackup(e.target.files[0]);
                    }}
                  />
                  {workspace?.paper_id ? (
                    <button onClick={() => navigate(`/knowledge/paper/${workspace.paper_id}`)}>打开知识笔记</button>
                  ) : null}
                  {version && mode !== "original" ? (
                    <button disabled={isBuilding} onClick={() => void generate()}>
                      <RefreshCw size={13} />
                      {isBuilding ? "正在生成新修订" : "重新生成此版本"}
                    </button>
                  ) : null}
                </footer>
              </>
            ) : (
              <div className="assistant-body">
                {summaryError && (
                  <div role="alert" className="space-y-3">
                    <p>{summaryError}</p>
                    <Button variant="outline" onClick={() => void loadSummary()}>
                      重新生成概览
                    </Button>
                  </div>
                )}
                {summaryLoading ? (
                  <p>
                    <Loader2 className="spin" size={16} />
                    正在生成论文摘要…
                  </p>
                ) : null}
                {summary ? (
                  <div className="summary-view">
                    <h3>{String(summary.one_liner || "论文摘要")}</h3>
                    {Object.entries((summary.story as Record<string, { text?: string }>) || {}).map(([key, value]) => (
                      <section key={key}>
                        <strong>
                          {{ problem: "问题", method: "方法", results: "结果", impact: "意义" }[key] || key}
                        </strong>
                        <p>{value?.text}</p>
                      </section>
                    ))}
                    {["contributions", "limitations"].map((key) =>
                      Array.isArray(summary[key]) ? (
                        <section key={key}>
                          <strong>{key === "contributions" ? "主要贡献" : "局限"}</strong>
                          {(summary[key] as unknown[]).map((item, i) => (
                            <p key={i}>{typeof item === "string" ? item : (item as { text?: string }).text}</p>
                          ))}
                        </section>
                      ) : null,
                    )}
                  </div>
                ) : null}
              </div>
            )}
          </aside>
        ) : null}
      </div>
      <PaperChat
        taskId={taskId}
        portalContainer={isFullscreen ? workspaceElement.current : undefined}
        title={workspace?.document.title || bundle.title}
        selection={selection}
        clearSelection={() => setSelection("")}
        open={chatOpen}
        onOpenChange={(next) => {
          setChatOpen(next);
          if (next) setPanel(null);
        }}
        onSource={(sourcePage) => {
          const original = bundle.versions.find((item) => item.kind === "original");
          if (!original || !Number.isInteger(sourcePage) || sourcePage < 1 || sourcePage > original.page_count) {
            toast.error("该原文位置暂不可用。");
            return;
          }
          requestedJump.current = { versionId: original.id, page: sourcePage };
          positions.current.set(original.id, sourcePage);
          setMode("original");
          setRevision("");
          if (version?.id === original.id) viewerRef.current?.goToPage(sourcePage);
          if (compact) setChatOpen(false);
        }}
      />
    </div>
  );
}

function AnnotationRow({
  annotation: a,
  source,
  onJump,
  onLink,
  onRetry,
  onChange,
}: {
  annotation: SharedAnnotation;
  source?: ReaderVersion;
  onJump: (source?: boolean) => void;
  onLink: () => void;
  onRetry: () => void;
  onChange: (data: SharedAnnotation["data"], deleted: boolean) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const color =
    (a.data as { strokeColor?: string; color?: string }).strokeColor ||
    (a.data as { color?: string }).color ||
    "#f4ce46";
  return (
    <article className={`annotation-row ${a.deleted ? "is-deleted" : ""}`}>
      <div className="annotation-row-head">
        <button onClick={() => onJump()}>
          {source ? versionNames[source.kind] : "历史版本"} · 第 {a.data.pageIndex + 1} 页
        </button>
        <label title="批注颜色">
          <span className="sr-only">批注颜色</span>
          <input
            type="color"
            disabled={a.deleted}
            value={/^#[0-9a-f]{6}$/i.test(color) ? color : "#f4ce46"}
            onChange={(e) =>
              onChange(
                { ...a.data, strokeColor: e.target.value, color: e.target.value } as SharedAnnotation["data"],
                false,
              )
            }
          />
        </label>
      </div>
      {a.quote ? (
        <blockquote>{a.quote}</blockquote>
      ) : (
        <p className="annotation-kind">{a.data.type === 15 ? "手写批注" : "页面批注"}</p>
      )}
      <textarea
        aria-label="批注笔记"
        placeholder="添加笔记…"
        disabled={a.deleted}
        value={draft ?? a.data.contents ?? ""}
        onFocus={() => {
          setDraft(a.data.contents || "");
        }}
        onChange={(e) => {
          setDraft(e.target.value);
          onChange({ ...a.data, contents: e.target.value }, false);
        }}
        onBlur={() => {
          setDraft(null);
        }}
      />
      <p className="annotation-alignment">{a.alignment_message}</p>
      <div className="annotation-row-actions">
        {a.deleted ? (
          <button onClick={() => onChange(a.data, false)}>
            <Undo2 size={13} />
            恢复
          </button>
        ) : (
          <>
            <button onClick={() => onJump(true)}>查看原标记</button>
            <button onClick={onLink}>
              <Link2 size={13} />
              关联此处
            </button>
            <button onClick={onRetry} aria-label="重试匹配" title="重新匹配自动标注，保留手动关联">
              <RefreshCw size={13} />
            </button>
            <button onClick={() => onChange(a.data, true)} aria-label="删除批注">
              <Trash2 size={13} />
            </button>
          </>
        )}
      </div>
    </article>
  );
}
