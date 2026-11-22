import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import {
  AlertCircle,
  BookOpen,
  BookmarkPlus,
  Check,
  ChevronLeft,
  CloudOff,
  Download,
  FileDown,
  FileText,
  Highlighter,
  Lightbulb,
  Link2,
  Loader2,
  Maximize,
  Minimize,
  MoreHorizontal,
  NotebookPen,
  PanelRight,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { isCancel } from "axios";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { downloadFile, parseServerDate } from "@/lib/format";
import { announceReviewChanged } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { PdfViewerHandle } from "@/components/reader/PdfViewer";
import PaperChat from "@/components/reader/PaperChat";
import PagePreview, { TranslationPreview } from "@/components/reader/PagePreview";
import { warmPdfViewer } from "@/components/reader/pdf-assets";
import type { GlossSpan } from "@/components/reader/gloss-hit";
import {
  cacheGet,
  cacheSet,
  versionNames,
  type ReaderMode,
  type ReaderVersion,
  type SharedAnnotation,
} from "@/components/reader/reader-store";
import { useSyncedReader } from "@/components/reader/useSyncedReader";
import { useGlossSpans } from "@/components/reader/useGlossSpans";
import { useFullscreenChrome } from "@/components/reader/useFullscreenChrome";
import { useUserPreferences } from "@/lib/preferences";
import { cn } from "@/lib/utils";
import "@/components/reader/reader.css";

const PdfViewer = lazy(() => import("@/components/reader/PdfViewer"));
type Aid = {
  chinese: string;
  simple_english: string;
  explanation?: string;
  terms?: { term: string; meaning: string; definition?: string }[];
  evidence_refs?: unknown[];
};
type Workspace = {
  document: {
    title: string;
    page_count: number;
    blocks: { id: string; page: number; source_text?: string }[];
  };
  aids?: Record<string, Aid>;
  state: { mode: ReaderMode; block_id: string };
  has_result: boolean;
  task_mode?: string;
  pdf_message: string;
  paper_id: string;
};
const modes: ReaderMode[] = ["original", "chinese", "simple", "bilingual", "gloss"];
const shortNames: Record<ReaderMode, string> = {
  original: "原文",
  chinese: "中文",
  simple: "简化",
  bilingual: "双语",
  gloss: "点读",
};
type ReaderPanel = "overview" | "aid" | "notes";
const panelNames: Record<ReaderPanel, string> = { overview: "论文概览", aid: "本页解读", notes: "共享批注" };
const panelClose: Record<ReaderPanel, string> = { overview: "关闭概览", aid: "关闭解读", notes: "关闭批注" };
const STORY_LABELS: Record<string, string> = { problem: "问题", method: "方法", results: "结果", impact: "意义" };

export default function Reader() {
  const { taskId = "" } = useParams<{ taskId: string }>();
  return <ReaderWorkspace key={taskId} taskId={taskId} />;
}

function ReaderWorkspace({ taskId }: { taskId: string }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const reader = useSyncedReader(taskId);
  const { bundle } = reader;
  const { preferences } = useUserPreferences();
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
  // Set while a revision downloads for the first time; page previews cover the wait.
  const [preview, setPreview] = useState<{ versionId: string; page: number; loaded: number; total: number } | null>(
    null,
  );
  const [pdfError, setPdfError] = useState("");
  const [page, setPage] = useState(1);
  const [activeBlockId, setActiveBlockId] = useState("");
  const [selection, setSelection] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [aidLoading, setAidLoading] = useState<"block" | "page" | null>(null);
  const [rememberedTerms, setRememberedTerms] = useState<Set<string>>(new Set());
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
  const glossBuild = bundle?.builds.find((item) => item.kind === "gloss");
  const glossStatus = glossBuild?.status || "missing";
  const glossAvailable = ["awaiting_worker", "claimed", "running", "completed", "error"].includes(glossStatus);
  const viewKind = mode === "gloss" ? (glossAvailable ? "original" : null) : mode;
  const currentVersions = viewKind ? bundle?.versions.filter((v) => v.kind === viewKind) || [] : [];
  const version = currentVersions.find((v) => v.id === revision) || currentVersions[0];
  const versionId = version?.id,
    versionUrl = version?.url,
    pageCount = version?.page_count;
  const { glossSpans, glossBooting, updateGlossSpan } = useGlossSpans(
    bundle?.document_id,
    glossAvailable,
    page,
    pageCount || 0,
    glossStatus,
  );
  const userId = bundle?.user_id;
  const versionRef = useRef(version);
  versionRef.current = version;
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const awaitingResult = workspace !== null && !workspace.has_result && workspace.task_mode !== "gloss";
  const reopen = reader.reopen;
  const build = bundle?.builds.find((b) => b.kind === mode);
  const isBuilding = generating || build?.status === "running";
  // Pages of a running translation that can be read before the whole version exists.
  const translatedPages = !version && build?.status === "running" && build.pages?.total ? build.pages : undefined;
  const originalPages = bundle?.versions.find((v) => v.kind === "original")?.pages;
  const currentBlock =
    workspace?.document.blocks.find((block) => block.id === activeBlockId) ||
    workspace?.document.blocks.find((block) => block.page === page);
  const currentAid = currentBlock ? workspace?.aids?.[currentBlock.id] : undefined;
  const pageAids = currentBlock
    ? (workspace?.document.blocks || [])
        .filter((block) => block.page === currentBlock.page && workspace?.aids?.[block.id])
        .map((block) => ({ block, aid: workspace!.aids![block.id] }))
    : [];

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
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (workspaceElement.current?.requestFullscreen) await workspaceElement.current.requestFullscreen();
      else toast.error("当前浏览器不支持全屏阅读");
    } catch {
      toast.error("未能切换全屏，请重试");
    }
  };

  const blockParam = searchParams.get("block");
  useEffect(() => {
    let cancelled = false;
    void api
      .get<Workspace>(`/api/reading/${taskId}`)
      .then(({ data }) => {
        if (cancelled) return;
        setWorkspace(data);
        setMode(data.state.mode || "original");
        const block =
          data.document.blocks.find((b) => b.id === blockParam) ||
          data.document.blocks.find((b) => b.id === data.state.block_id);
        if (block) {
          setPage(block.page);
          setActiveBlockId(block.id);
        }
      })
      .catch(() => {
        /* Archived reader remains usable if the legacy task data cannot be read. */
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, blockParam]);

  const generateAid = async (scope: "block" | "page") => {
    if (!currentBlock) return;
    setAidLoading(scope);
    try {
      if (scope === "block") {
        const { data } = await api.post<Aid>(`/api/reading/${taskId}/blocks/${currentBlock.id}/aid`);
        setWorkspace((old) => (old ? { ...old, aids: { ...(old.aids || {}), [currentBlock.id]: data } } : old));
      } else {
        const { data } = await api.post<{ aids: Workspace["aids"] }>(
          `/api/reading/${taskId}/pages/${currentBlock.page}/aid`,
        );
        setWorkspace((old) => (old ? { ...old, aids: { ...(old.aids || {}), ...(data.aids || {}) } } : old));
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err, scope === "block" ? "本段解读生成失败，请重试。" : "本页解读生成失败，请重试。"));
    } finally {
      setAidLoading(null);
    }
  };

  const saveTerm = async (payload: Record<string, unknown>, label: string) => {
    try {
      await api.post("/api/terms", payload);
      setRememberedTerms((old) => new Set(old).add(label.toLocaleLowerCase()));
      announceReviewChanged();
      toast.success(`已记住术语：${label}`, {
        action: { label: "术语本", onClick: () => navigate("/knowledge/terms") },
      });
    } catch (err) {
      toast.error(getApiErrorMessage(err, "保存术语失败。"));
      throw err;
    }
  };

  const rememberTerm = (term: { term: string; meaning: string; definition?: string }, blockId: string, quote = "") => {
    if (!workspace?.paper_id) return;
    void saveTerm(
      {
        term: term.term,
        meaning: term.meaning,
        definition: term.definition || "",
        paper_id: workspace.paper_id,
        task_id: taskId,
        block_id: blockId,
        source_quote: quote,
      },
      term.term,
    ).catch(() => undefined);
  };

  const rememberGlossTerm = async (span: GlossSpan) => {
    if (!workspace?.paper_id) {
      toast.error("论文信息仍在加载，请稍后再试。");
      throw new Error("paper not ready");
    }
    const block = workspace.document.blocks.find((item) => item.page === span.page + 1) || currentBlock;
    const term = span.text.trim().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
    if (!term) throw new Error("empty term");
    await saveTerm(
      {
        term,
        meaning: span.zh,
        definition: span.simple_en || span.en || span.role || "",
        paper_id: workspace.paper_id,
        task_id: taskId,
        block_id: block?.id,
        source_quote: span.text,
      },
      term,
    );
  };

  useEffect(() => {
    if (!awaitingResult) return;
    const timer = window.setInterval(() => {
      void api
        .get(`/api/status/${taskId}`)
        .then(({ data }) => {
          setWorkspace((old) => (old ? { ...old, has_result: Boolean(data.has_result), pdf_message: data.message } : old));
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
    warmPdfViewer();
  }, []);

  useEffect(() => {
    if (!versionId || !versionUrl || !pageCount || userId === undefined) {
      setPdf(null);
      setPreview(null);
      return;
    }
    let cancelled = false,
      url = "";
    const controller = new AbortController();
    setPdf(null);
    setPreview(null);
    setPdfError("");
    setSelection("");
    const cacheKey = `pdf:${userId}:${versionId}`;
    // A page read while this version was still being translated.
    const carried = positions.current.get(`partial:${versionRef.current?.kind}`);
    const startPage = async () => {
      const stored = await cacheGet<number>(`position:${userId}:${versionId}`).catch(() => undefined);
      return Math.max(
        1,
        Math.min(
          pageCount,
          requestedJump.current?.versionId === versionId
            ? requestedJump.current.page
            : positions.current.get(versionId) || stored || carried || 1,
        ),
      );
    };
    const openBlob = async (blob: Blob) => {
      const next = await startPage();
      if (cancelled) return;
      if (url) URL.revokeObjectURL(url);
      url = URL.createObjectURL(blob);
      setPage(next);
      setPdf({ versionId, url, page: next });
    };
    void (async () => {
      // Revision ids are content addresses (document:kind:sha256), so a cached
      // copy can never be stale. Opening it must not download the file again.
      const cached = await cacheGet<Blob>(cacheKey).catch(() => undefined);
      if (cancelled) return;
      if (cached) {
        await openBlob(cached);
        return;
      }
      const first = await startPage();
      if (cancelled) return;
      setPage(first);
      setPreview({ versionId, page: first, loaded: 0, total: 0 });
      let reported = 0;
      const { data } = await api.get<Blob>(versionUrl, {
        responseType: "blob",
        signal: controller.signal,
        onDownloadProgress: (event) => {
          const now = performance.now();
          if (now - reported < 250 && event.loaded !== event.total) return;
          reported = now;
          setPreview((current) =>
            current?.versionId === versionId
              ? { ...current, loaded: event.loaded, total: event.total || current.total }
              : current,
          );
        },
      });
      void cacheSet(cacheKey, data).catch(() => undefined);
      if (!cancelled) await openBlob(data);
    })().catch((err) => {
      if (cancelled || isCancel(err)) return;
      setPreview(null);
      setPdfError(getApiErrorMessage(err, "PDF 加载失败，请重新打开此版本"));
    });
    return () => {
      cancelled = true;
      // Leaving a paper (or switching version) must free the connection for the next one.
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [versionId, versionUrl, pageCount, userId]);

  useEffect(() => () => window.clearTimeout(positionTimer.current), []);

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
      if (block) {
        setActiveBlockId(block.id);
        positionTimer.current = window.setTimeout(() => {
          void api
            .patch(`/api/reading/${taskId}/state`, { block_id: block.id, mode: modeRef.current })
            .catch(() => undefined);
        }, 700);
      }
    },
    [userId, taskId],
  );

  const onPartialPageChange = useCallback((next: number) => {
    setPage(next);
    positions.current.set(`partial:${modeRef.current}`, next);
    const block = workspaceRef.current?.document.blocks.find((b) => b.page === next);
    if (block) setActiveBlockId(block.id);
  }, []);

  const switchMode = (next: ReaderMode) => {
    if (next === mode) return;
    const sourcePage = version?.origin_pages?.[page - 1];
    const nextReady =
      next !== "gloss" || bundle?.builds.some((item) => item.kind === "gloss" && item.status === "completed");
    const target = nextReady ? bundle?.versions.find((v) => v.kind === (next === "gloss" ? "original" : next)) : undefined;
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
      toast.success(`已开始生成${versionNames[mode]}`, { description: "生成期间可以先读原文，完成后会自动出现。" });
    } catch (err) {
      toast.error(getApiErrorMessage(err, "生成失败，请重试"));
    } finally {
      setGenerating(false);
    }
  };

  const enrichGlossSpan = useCallback(
    async (span: GlossSpan) => {
      if (!bundle?.document_id || span.simple_en) return span;
      try {
        const { data } = await api.post<GlossSpan>(`/api/reader/documents/${bundle.document_id}/gloss/${span.id}/enrich`);
        updateGlossSpan(data);
        return data;
      } catch {
        return null;
      }
    },
    [bundle?.document_id, updateGlossSpan],
  );
  const download = async (path: string, name: string) => {
    try {
      await downloadFile(path, name);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "下载失败"));
    }
  };
  const linkHere = async (annotation: SharedAnnotation) => {
    if (!bundle || !version) return;
    try {
      const selected = await viewerRef.current?.getSelection();
      if (!selected?.text) {
        toast.error("请先在当前版本选中对应文字，再点“关联此处”");
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
  const extractKnowledge = async () => {
    try {
      const { data } = await api.post<{ paper_id: string }>(`/api/knowledge/extract/${taskId}`);
      toast.success("已开始整理知识笔记", {
        description: "整理完成后可在知识笔记里查看发现、概念和复习卡。",
        action: { label: "查看", onClick: () => navigate(`/knowledge/paper/${data.paper_id}`) },
      });
    } catch (err) {
      toast.error(getApiErrorMessage(err, "知识整理启动失败。"));
    }
  };

  if (reader.error)
    return (
      <main className="reader-empty">
        <span className="reader-empty-icon">
          <FileText size={28} />
        </span>
        <h1>无法打开阅读器</h1>
        <p>{reader.error}</p>
        <div className="reader-empty-actions">
          <Button variant="secondary" onClick={() => navigate("/dashboard")}>
            返回我的论文
          </Button>
          <Button onClick={() => window.location.reload()}>重试</Button>
        </div>
      </main>
    );
  if (!bundle)
    return (
      <main className="reader-empty" aria-busy="true">
        <Loader2 className="spin" size={26} />
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
  const statusTone = reader.saveError ? "is-danger" : reader.pending.length || matching || retrying ? "is-warn" : partial ? "is-danger" : "is-ok";
  const statusShort = reader.saveError
    ? reader.pending.length
      ? "未同步"
      : "保存出错"
    : reader.pending.length
      ? "本地已保存"
      : matching
        ? `匹配中 ${matching}`
        : partial
          ? `${partial} 条待确认`
          : "已保存";
  const title = workspace?.document.title || bundle.title;
  const versionReady = (item: ReaderMode) =>
    (item === "gloss" && glossAvailable) || bundle.versions.some((v) => v.kind === item);
  const versionBuilding = (item: ReaderMode) => bundle.builds.some((b) => b.kind === item && b.status === "running");

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
        <header className="reader-topbar">
          <div className="reader-titlebar">
            <Button variant="ghost" size="icon-sm" aria-label="返回文档库" title="返回我的论文" onClick={() => navigate("/dashboard")}>
              <ChevronLeft />
            </Button>
            <div className="reader-title">
              <h1 title={title}>{title}</h1>
              <div className="reader-subline">
                <span className="reader-version-detail">
                  {version ? `${versionNames[mode]} · 第 ${page} / ${version.page_count} 页` : versionNames[mode]}
                </span>
                {currentVersions.length > 1 ? (
                  <Select
                    className="reader-revision"
                    aria-label="文件修订"
                    value={version?.id}
                    onChange={(e) => setRevision(e.target.value)}
                  >
                    {currentVersions.map((v, i) => (
                      <option key={v.id} value={v.id}>
                        {i === 0 ? "最新修订" : "历史修订"} · {parseServerDate(v.created_at)?.toLocaleString("zh-CN")}
                      </option>
                    ))}
                  </Select>
                ) : null}
              </div>
            </div>
          </div>
          <SegmentedControl
            ariaLabel="阅读版本"
            className="reader-version-switch"
            value={mode}
            onChange={switchMode}
            options={modes.map((item) => ({
              value: item,
              ariaLabel: versionReady(item) ? versionNames[item] : `${versionNames[item]}（${versionBuilding(item) ? "生成中" : "待生成"}）`,
              title: versionReady(item) ? undefined : versionBuilding(item) ? "正在生成" : "尚未生成，点击后可生成",
              label: (
                <>
                  <span className="version-long">{versionNames[item]}</span>
                  <span className="version-short">{shortNames[item]}</span>
                  {!versionReady(item) ? (
                    <span className={cn("version-dot", versionBuilding(item) && "is-building")} aria-hidden="true" />
                  ) : null}
                </>
              ),
            }))}
          />
          <div className="reader-actions">
            <span role="status" className="reader-sync">
              <button
                type="button"
                className={cn("reader-sync-chip", statusTone)}
                title={`${saveStatus} · ${matchStatus}`}
                onClick={() => {
                  setFilter(matching || retrying || partial ? "unmatched" : "all");
                  changePanel("notes");
                }}
              >
                {reader.pending.length || matching ? (
                  <Loader2 className="spin" aria-hidden="true" />
                ) : reader.saveError ? (
                  <CloudOff aria-hidden="true" />
                ) : partial ? (
                  <AlertCircle aria-hidden="true" />
                ) : (
                  <Check aria-hidden="true" />
                )}
                <span className="reader-sync-text" aria-hidden="true">
                  {statusShort}
                </span>
                <span className="sr-only">
                  {saveStatus} · {matchStatus}
                </span>
              </button>
            </span>
            <Button
              size="sm"
              variant="ghost"
              aria-label="论文概览"
              title="概览与本页解读"
              aria-expanded={panel === "overview" || panel === "aid"}
              className={cn((panel === "overview" || panel === "aid") && "is-active")}
              onClick={() => changePanel(panel === "overview" || panel === "aid" ? null : "overview")}
            >
              <PanelRight />
              <span className="desktop-label">助手</span>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className={cn(panel === "notes" && "is-active")}
              onClick={() => changePanel(panel === "notes" ? null : "notes")}
              aria-expanded={panel === "notes"}
            >
              <Highlighter />
              <span className="reader-label">批注</span> {active.length}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="带批注 PDF"
              title="下载带批注 PDF"
              disabled={!pdf}
              onClick={() =>
                void viewerRef.current?.exportPdf().catch((err) => toast.error(getApiErrorMessage(err, "导出失败")))
              }
            >
              <Download />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="更多阅读操作">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" container={isFullscreen ? workspaceElement.current : undefined}>
                {workspace?.paper_id ? (
                  <DropdownMenuItem onSelect={() => navigate(`/knowledge/paper/${workspace.paper_id}`)}>
                    <NotebookPen />
                    打开知识笔记
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem onSelect={() => void extractKnowledge()}>
                  <Sparkles />
                  整理知识笔记
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                {version ? (
                  <DropdownMenuItem onSelect={() => void download(version.url, `${title}-${versionNames[version.kind]}.pdf`)}>
                    <FileDown />
                    下载{versionNames[version.kind]} PDF
                  </DropdownMenuItem>
                ) : null}
                {version && mode !== "original" ? (
                  <DropdownMenuItem disabled={isBuilding} onSelect={() => void generate()}>
                    <RefreshCw />
                    {isBuilding ? "正在生成新修订…" : "重新生成此版本"}
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem onSelect={() => void toggleFullscreen()}>
                  {isFullscreen ? <Minimize /> : <Maximize />}
                  {isFullscreen ? "退出全屏" : "全屏阅读"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="ghost"
              size="icon-sm"
              className="reader-fullscreen-button"
              aria-label={isFullscreen ? "退出全屏" : "全屏阅读"}
              aria-pressed={isFullscreen}
              title={isFullscreen ? "退出全屏（Esc）" : "全屏阅读"}
              onClick={() => void toggleFullscreen()}
            >
              {isFullscreen ? <Minimize /> : <Maximize />}
            </Button>
          </div>
        </header>
        {conflicts.length ? (
          <div className="reader-conflicts" role="alert">
            {conflicts.map((id) => (
              <div key={id}>
                <AlertCircle size={16} aria-hidden="true" />
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
            {!version && translatedPages ? (
              <TranslationPreview
                key={`${bundle.document_id}:${mode}`}
                documentId={bundle.document_id}
                kind={mode}
                pages={originalPages}
                total={translatedPages.total}
                done={translatedPages.done}
                initialPage={positions.current.get(`partial:${mode}`) || page}
                onPageChange={onPartialPageChange}
              />
            ) : !version ? (
              <div className="pdf-empty">
                <div className="pdf-empty-card">
                  <span className="pdf-empty-icon" aria-hidden="true">
                    {isBuilding ? <Loader2 className="spin" /> : <BookOpen />}
                  </span>
                  <h2>{isBuilding ? `正在生成${versionNames[mode]}` : `${versionNames[mode]}尚未生成`}</h2>
                  <p>
                    {build?.error ||
                      (mode === "gloss"
                        ? isBuilding
                          ? "正在按页准备单词、术语、搭配和句式；已完成的页可以立即点读。"
                          : "生成后仍是原文。点中哪个词，就显示这块事先准备好的解释。"
                        : isBuilding
                          ? mode === "chinese"
                            ? "第 1 页译好后会直接显示在这里，之后每译完一页就多一页。也可以先读原文。"
                            : "生成完成后会自动打开，并匹配已保存的批注。可以先读原文。"
                          : "生成此版本后，可与其他版本共享批注和阅读位置。")}
                  </p>
                  {isBuilding ? <div className="pdf-empty-progress" aria-hidden="true" /> : null}
                  <div className="pdf-empty-actions">
                    {!isBuilding && mode !== "original" ? (
                      <Button onClick={() => void generate()}>
                        <RefreshCw />
                        生成{versionNames[mode]}
                      </Button>
                    ) : null}
                    {mode !== "original" ? (
                      <Button variant="secondary" onClick={() => switchMode("original")}>
                        先读原文
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : pdfError ? (
              <div className="pdf-empty" role="alert">
                <div className="pdf-empty-card">
                  <span className="pdf-empty-icon is-error" aria-hidden="true">
                    <AlertCircle />
                  </span>
                  <h2>这一版暂时打不开</h2>
                  <p>{pdfError}</p>
                  <Button onClick={() => window.location.reload()}>重新加载</Button>
                </div>
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
                    setPreview(null);
                    positions.current.delete(`partial:${version.kind}`);
                    const destination = requestedJump.current;
                    if (destination?.versionId === version.id) {
                      viewerRef.current?.goToPage(destination.page, destination.point);
                      requestedJump.current = undefined;
                    } else {
                      // The reader may have kept scrolling the preview after the file arrived.
                      const latest = positions.current.get(version.id);
                      if (latest && latest !== pdf.page) viewerRef.current?.goToPage(latest);
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
                  glossSpans={mode === "gloss" && glossSpans ? glossSpans : undefined}
                  onGlossEnrich={enrichGlossSpan}
                  onRememberTerm={rememberGlossTerm}
                  autoSpeak={preferences.reading.gloss.auto_speak}
                />
              </Suspense>
            ) : preview?.versionId !== version.id ? (
              <div className="pdf-loading">
                <Loader2 className="spin" size={22} />
                {mode === "gloss" && glossBooting ? "正在准备点读数据（优先加载当前页）…" : "正在打开完整页面…"}
              </div>
            ) : null}
            {version && preview?.versionId === version.id && !pdfError ? (
              <PagePreview
                key={version.id}
                documentId={bundle.document_id}
                version={version}
                initialPage={preview.page}
                loaded={preview.loaded}
                total={preview.total}
                onPageChange={(next) => {
                  if (requestedJump.current?.versionId === version.id) requestedJump.current = undefined;
                  onPageChange(next);
                }}
              />
            ) : null}
          </div>
        </main>
        {panel ? (
          <aside ref={panelRef} className="reader-sidepanel" aria-label={panelNames[panel]}>
            <div className="reader-panel-head">
              <div className="reader-panel-tabs" role="group" aria-label="阅读辅助类型">
                {(Object.keys(panelNames) as ReaderPanel[]).map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-label={`查看${value === "overview" ? "概览" : value === "aid" ? "本页解读" : "批注"}`}
                    aria-pressed={panel === value}
                    onClick={() => changePanel(value)}
                  >
                    {value === "overview" ? "概览" : value === "aid" ? "本页解读" : "批注"}
                    {value === "notes" && active.length ? <span className="tab-count">{active.length}</span> : null}
                  </button>
                ))}
              </div>
              <Button variant="ghost" size="icon-sm" onClick={() => changePanel(null)} aria-label={panelClose[panel]}>
                <X />
              </Button>
            </div>
            {panel === "notes" ? (
              <>
                <div className="annotation-sync" aria-hidden="true">
                  <span className={cn("status-dot", statusTone)} />
                  <span>{saveStatus}</span>
                  <span>·</span>
                  <span>{matchStatus}</span>
                </div>
                <div className="annotation-filters">
                  <div className="search-field">
                    <Search aria-hidden="true" />
                    <input
                      className="ui-input"
                      aria-label="搜索批注"
                      placeholder="搜索摘录或笔记"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </div>
                  <Select aria-label="批注类型" value={filter} onChange={(e) => setFilter(e.target.value)}>
                    <option value="all">全部批注</option>
                    <option value="unmatched">跨版本待匹配</option>
                    <option value="highlight">文字标记</option>
                    <option value="note">笔记</option>
                    <option value="ink">手写与圈画</option>
                    <option value="deleted">已删除 · 可恢复</option>
                  </Select>
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
                      <span className="annotation-empty-icon" aria-hidden="true">
                        <Highlighter size={22} />
                      </span>
                      <p>
                        {filter === "deleted"
                          ? "没有已删除的批注"
                          : filter === "unmatched"
                            ? "没有待匹配的批注"
                            : query
                              ? "没有匹配的批注，试试其他关键词。"
                              : "选中文字添加高亮，或用工具栏在页面上圈画。"}
                      </p>
                      <p>批注会自动保存，并同步到其他版本。无法定位时可选中文字后手动关联。</p>
                    </div>
                  )}
                </div>
                <footer className="annotation-footer">
                  <button
                    type="button"
                    onClick={() =>
                      void download(`/api/reader/documents/${bundle.document_id}/archive`, "paper-with-annotations.zip")
                    }
                  >
                    <Download size={14} />
                    备份论文与批注
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void download(`/api/reader/documents/${bundle.document_id}/annotations/export`, "paper-annotations.json")
                    }
                  >
                    导出批注数据
                  </button>
                  <button type="button" disabled={restoring} onClick={() => restoreInput.current?.click()}>
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
                </footer>
              </>
            ) : panel === "aid" ? (
              <div className="assistant-body">
                <section className="aid-head">
                  <div>
                    <h3>{currentBlock ? `第 ${currentBlock.page} 页` : "翻到一页后开始"}</h3>
                    <p>逐段给出忠实的中文、逻辑梳理和关键术语。结果会缓存，下次打开直接显示。</p>
                  </div>
                  <div className="aid-actions">
                    <Button size="sm" disabled={!currentBlock || aidLoading !== null} onClick={() => void generateAid("page")}>
                      {aidLoading === "page" ? <Loader2 className="spin" /> : <Sparkles />}
                      解读本页
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!currentBlock || aidLoading !== null}
                      onClick={() => void generateAid("block")}
                    >
                      {aidLoading === "block" ? <Loader2 className="spin" /> : <Lightbulb />}
                      {currentAid ? "重新解读首段" : "只解读首段"}
                    </Button>
                  </div>
                </section>
                {aidLoading ? (
                  <div className="aid-skeleton" role="status" aria-label="正在生成解读">
                    <span className="skeleton" style={{ width: "40%", height: 12 }} />
                    <span className="skeleton" style={{ width: "100%", height: 12 }} />
                    <span className="skeleton" style={{ width: "92%", height: 12 }} />
                    <span className="skeleton" style={{ width: "70%", height: 12 }} />
                  </div>
                ) : null}
                {pageAids.length ? (
                  pageAids.map(({ block, aid }, index) => (
                    <article key={block.id} className="aid-card">
                      <span className="aid-index">段落 {index + 1}</span>
                      <p className="aid-zh">{aid.chinese}</p>
                      {aid.explanation ? (
                        <div className="aid-logic">
                          <strong>逻辑</strong>
                          <p>{aid.explanation}</p>
                        </div>
                      ) : null}
                      {aid.terms?.length ? (
                        <div className="aid-terms">
                          {aid.terms.map((term) => {
                            const saved = rememberedTerms.has(term.term.toLocaleLowerCase());
                            return (
                              <button
                                key={term.term}
                                type="button"
                                className={cn("aid-term", saved && "is-saved")}
                                disabled={saved}
                                title={term.definition || term.meaning}
                                aria-label={saved ? `已记住 ${term.term}` : `记住 ${term.term}`}
                                onClick={() => rememberTerm(term, block.id, block.source_text || "")}
                              >
                                <span lang="en">{term.term}</span>
                                <small>{term.meaning}</small>
                                {saved ? <Check size={13} aria-hidden="true" /> : <BookmarkPlus size={13} aria-hidden="true" />}
                              </button>
                            );
                          })}
                        </div>
                      ) : null}
                    </article>
                  ))
                ) : !aidLoading ? (
                  <div className="annotation-empty">
                    <span className="annotation-empty-icon" aria-hidden="true">
                      <Lightbulb size={22} />
                    </span>
                    <p>这一页还没有解读。</p>
                    <p>点“解读本页”，AI 会把每一段翻译成中文并解释它在论证中的作用。</p>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="assistant-body">
                {summaryError && (
                  <div role="alert" className="notice is-danger">
                    <AlertCircle aria-hidden="true" />
                    <div style={{ display: "grid", gap: 10 }}>
                      <span>{summaryError}</span>
                      <Button size="sm" variant="secondary" onClick={() => void loadSummary()}>
                        重新生成概览
                      </Button>
                    </div>
                  </div>
                )}
                {summaryLoading ? (
                  <div className="aid-skeleton" role="status" aria-label="正在生成论文摘要">
                    <span className="skeleton" style={{ width: "85%", height: 20 }} />
                    <span className="skeleton" style={{ width: "60%", height: 20 }} />
                    <span className="skeleton" style={{ width: "100%", height: 12, marginTop: 12 }} />
                    <span className="skeleton" style={{ width: "94%", height: 12 }} />
                    <span className="skeleton" style={{ width: "80%", height: 12 }} />
                    <span className="sr-only">正在生成论文摘要…</span>
                  </div>
                ) : null}
                {summary ? (
                  <div className="summary-view">
                    <h3>{String(summary.one_liner || "论文摘要")}</h3>
                    <ol className="summary-story">
                      {Object.entries((summary.story as Record<string, { text?: string }>) || {}).map(([key, value]) => (
                        <li key={key}>
                          <strong>{STORY_LABELS[key] || key}</strong>
                          <p>{value?.text}</p>
                        </li>
                      ))}
                    </ol>
                    {["contributions", "limitations"].map((key) =>
                      Array.isArray(summary[key]) && (summary[key] as unknown[]).length ? (
                        <section key={key} className="summary-list">
                          <strong>{key === "contributions" ? "主要贡献" : "局限"}</strong>
                          <ul>
                            {(summary[key] as unknown[]).map((item, i) => (
                              <li key={i}>{typeof item === "string" ? item : (item as { text?: string }).text}</li>
                            ))}
                          </ul>
                        </section>
                      ) : null,
                    )}
                    <button type="button" className="summary-next" onClick={() => changePanel("aid")}>
                      <Lightbulb size={15} aria-hidden="true" />
                      读不懂这一页？看本页解读
                    </button>
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
        title={title}
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

const NOTE_SAVE_DELAY = 600;

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
  const timer = useRef<number>();
  const pendingText = useRef<string | null>(null);
  const latest = useRef({ a, onChange });
  useLayoutEffect(() => {
    latest.current = { a, onChange };
  });
  const color =
    (a.data as { strokeColor?: string; color?: string }).strokeColor || (a.data as { color?: string }).color || "#f4ce46";

  // Typing used to write one sync operation per keystroke. Commit after a short pause
  // (or on blur/unmount) instead, and guard the tab while a note is still unsaved.
  const guard = useCallback((event: BeforeUnloadEvent) => {
    event.preventDefault();
    event.returnValue = "";
  }, []);
  const commit = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
    window.removeEventListener("beforeunload", guard);
    const text = pendingText.current;
    pendingText.current = null;
    if (text === null) return;
    const { a: current, onChange: save } = latest.current;
    if ((current.data.contents || "") !== text) save({ ...current.data, contents: text }, false);
  }, [guard]);
  useEffect(() => commit, [commit]);

  const alignmentTone =
    a.alignment_status === "matched" ? "is-ok" : a.alignment_status === "pending" ? "is-warn" : "is-danger";
  return (
    <article className={`annotation-row ${a.deleted ? "is-deleted" : ""}`} style={{ "--mark": color } as CSSProperties}>
      <div className="annotation-row-head">
        <button type="button" className="annotation-location" onClick={() => onJump()}>
          {source ? versionNames[source.kind] : "历史版本"} · 第 {a.data.pageIndex + 1} 页
        </button>
        <label className="annotation-color" title="批注颜色">
          <span className="sr-only">批注颜色</span>
          <input
            type="color"
            disabled={a.deleted}
            value={/^#[0-9a-f]{6}$/i.test(color) ? color : "#f4ce46"}
            onChange={(e) =>
              onChange({ ...a.data, strokeColor: e.target.value, color: e.target.value } as SharedAnnotation["data"], false)
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
        rows={2}
        value={draft ?? a.data.contents ?? ""}
        onFocus={() => setDraft(a.data.contents || "")}
        onChange={(e) => {
          const text = e.target.value;
          setDraft(text);
          if (pendingText.current === null) window.addEventListener("beforeunload", guard);
          pendingText.current = text;
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(commit, NOTE_SAVE_DELAY);
        }}
        onBlur={() => {
          commit();
          setDraft(null);
        }}
      />
      {a.alignment_message ? (
        <p className="annotation-alignment">
          <span className={cn("status-dot", alignmentTone)} aria-hidden="true" />
          {a.alignment_message}
        </p>
      ) : null}
      <div className="annotation-row-actions">
        {a.deleted ? (
          <button type="button" onClick={() => onChange(a.data, false)}>
            <Undo2 size={13} />
            恢复
          </button>
        ) : (
          <>
            <button type="button" onClick={() => onJump(true)}>
              查看原标记
            </button>
            <button type="button" onClick={onLink}>
              <Link2 size={13} />
              关联此处
            </button>
            <span className="annotation-row-spacer" />
            <button type="button" className="icon" onClick={onRetry} aria-label="重试匹配" title="重新匹配自动标注，保留手动关联">
              <RefreshCw size={14} />
            </button>
            <button type="button" className="icon is-danger" onClick={() => onChange(a.data, true)} aria-label="删除批注" title="删除批注">
              <Trash2 size={14} />
            </button>
          </>
        )}
      </div>
    </article>
  );
}
