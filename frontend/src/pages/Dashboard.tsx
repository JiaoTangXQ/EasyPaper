import { useWorkspaceValue, useWorkspaceScroll } from "@/components/workspace/useWorkspaceMemory";
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { isCancel } from "axios";
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  FileSearch,
  Loader2,
  MessageCircleQuestion,
  MoreHorizontal,
  NotebookPen,
  PanelRight,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { PageHeader, EmptyState, ListSkeleton } from "@/components/workspace/PageHeader";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { confirmAction } from "@/lib/confirm";
import ImportDialog, { type ImportResult } from "@/components/library/ImportDialog";
import ReadingDemo from "@/components/workspace/ReadingDemo";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { useFeatures } from "@/lib/features";
import { friendlyDate } from "@/lib/format";
import { TASKS_CHANGED } from "@/lib/session";

const ACTIVE_TASK_STATUSES = new Set(["pending", "processing", "parsing", "rewriting", "rendering", "highlighting"]);

type TaskMode = "translate" | "simplify" | "gloss";
interface Task {
  task_id: string;
  filename: string;
  title?: string | null;
  title_zh?: string | null;
  status:
    | "pending"
    | "processing"
    | "parsing"
    | "rewriting"
    | "rendering"
    | "highlighting"
    | "completed"
    | "failed"
    | "error"
    | "cancelled";
  created_at: string;
  percent?: number;
  message?: string;
  mode?: TaskMode;
  highlight?: boolean;
  can_read?: boolean;
  reading?: { block_id: string; page?: number; understood_count: number; updated_at: string };
}
type KnowledgeRef = { id: string; status: string };

const MODE_META: Record<TaskMode, { label: string; glyph: string }> = {
  translate: { label: "中文译文", glyph: "译" },
  simplify: { label: "简化英文", glyph: "简" },
  gloss: { label: "原文点读", glyph: "点" },
};
const STATUS_LABELS: Record<string, string> = {
  pending: "排队中",
  processing: "处理中",
  parsing: "解析中",
  rewriting: "正在生成阅读版本",
  rendering: "正在排版",
  highlighting: "高亮中",
  completed: "完成",
  failed: "失败",
  error: "失败",
  cancelled: "已取消",
};

const taskTitle = (task: Task) => task.title?.trim() || task.filename;
const isReady = (task: Task) => task.status === "completed" || Boolean(task.can_read);
const isFailed = (task: Task) => task.status === "failed" || task.status === "error";
const taskErrorLabel = (task: Task) => {
  const message = task.message?.trim();
  if (!message) return "处理未完成，可以重新尝试。";
  // Old tasks can contain a provider-specific message. Keep implementation
  // details out of the library view; retrying always uses the current server provider.
  if (/cursor|codex|cli|模型配置|网络|AI/i.test(message)) return "AI 处理未完成，服务暂时不可用。点击重试。";
  return message;
};
type TitleState = { source: string; status: "pending" | "error" };

function PaperTitleSubtitle({ task, state, retry }: { task: Task; state?: TitleState; retry: () => void }) {
  if (task.title_zh)
    return (
      <p className="paper-title-zh" lang="zh-CN">
        {task.title_zh}
      </p>
    );
  if (!state || state.source !== task.title) return null;
  return (
    <p className="paper-title-zh">
      {state.status === "pending" ? (
        "正在翻译标题…"
      ) : (
        <button type="button" className="title-translation-retry" onClick={retry}>
          重试标题翻译
        </button>
      )}
    </p>
  );
}

function StatusPill({ task }: { task: Task }) {
  const mode = MODE_META[task.mode || "translate"];
  if (task.status === "completed")
    return (
      <span className="pill is-ok">
        <CheckCircle2 aria-hidden="true" />
        {task.mode === "gloss" ? "原文点读可用" : `${mode.label}可读`}
      </span>
    );
  if (isFailed(task))
    return (
      <span className="pill is-danger">
        <AlertCircle aria-hidden="true" />
        失败
      </span>
    );
  if (ACTIVE_TASK_STATUSES.has(task.status))
    return (
      <span className="pill is-warn">
        <Clock aria-hidden="true" />
        {STATUS_LABELS[task.status]}
      </span>
    );
  return <span className="pill">{STATUS_LABELS[task.status] || task.status}</span>;
}

function todayLabel() {
  return new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
}

const Dashboard = () => {
  const features = useFeatures();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [knowledge, setKnowledge] = useState<Map<string, KnowledgeRef>>(new Map());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useWorkspaceValue("papers:status", "all");
  const [search, setSearch] = useWorkspaceValue("papers:search");
  const [extracting, setExtracting] = useState("");
  useWorkspaceScroll("papers", !loading);
  const abortRef = useRef<AbortController | null>(null);
  const errorShownRef = useRef(false);
  const hasActiveTasks = tasks.some((task) => ACTIVE_TASK_STATUSES.has(task.status));
  const [titleStates, setTitleStates] = useState<Record<string, TitleState>>({});
  const titleCalls = useRef(new Map<string, AbortController>());
  const requestedTitles = useRef(new Set<string>());

  const fetchTasks = useCallback(async () => {
    try {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      const response = await api.get("/api/tasks", { signal: abortRef.current.signal });
      setTasks((current) =>
        (response.data as Task[]).map((task) => {
          const existing = current.find((item) => item.task_id === task.task_id && item.title === task.title);
          return { ...task, title_zh: task.title_zh || existing?.title_zh };
        }),
      );
      setLoading(false);
      setLoadError("");
      errorShownRef.current = false;
    } catch (error: unknown) {
      if (isCancel(error)) return;
      setLoading(false);
      setLoadError("无法获取论文列表，请检查连接后重试。");
      // Surface the failure once per error streak instead of on every poll.
      if (!errorShownRef.current) {
        toast.error("无法加载论文列表，正在重试…");
        errorShownRef.current = true;
      }
    }
  }, []);

  // Knowledge notes are keyed by task so each row can link to its own notes.
  const fetchKnowledge = useCallback(async () => {
    try {
      const { data } = await api.get<{ id: string; task_id: string | null; extraction_status: string }[]>(
        "/api/knowledge/papers",
      );
      setKnowledge(
        new Map(
          (Array.isArray(data) ? data : [])
            .filter((paper) => paper.task_id)
            .map((paper) => [paper.task_id as string, { id: paper.id, status: paper.extraction_status }]),
        ),
      );
    } catch {
      /* The library stays usable without the knowledge index. */
    }
  }, []);

  const translateTitle = useCallback(
    async (task: Task) => {
      if (!features.ai_available) return;
      const source = task.title?.trim();
      if (!source || task.title_zh || /[\u3400-\u9fff]/.test(source)) return;
      const key = `${task.task_id}:${source}`;
      if (titleCalls.current.has(key)) return;
      requestedTitles.current.add(key);
      const controller = new AbortController();
      titleCalls.current.set(key, controller);
      setTitleStates((current) => ({ ...current, [task.task_id]: { source, status: "pending" } }));
      try {
        const { data } = await api.post<{ title: string; title_zh: string | null }>(
          `/api/tasks/${task.task_id}/title-translation`,
          {},
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          if (!data.title_zh) throw new Error("中文标题暂不可用");
          setTasks((current) =>
            current.map((item) =>
              item.task_id === task.task_id && item.title === data.title ? { ...item, title_zh: data.title_zh } : item,
            ),
          );
          setTitleStates((current) => {
            if (current[task.task_id]?.source !== source) return current;
            const next = { ...current };
            delete next[task.task_id];
            return next;
          });
        }
      } catch {
        if (!controller.signal.aborted)
          setTitleStates((current) => ({ ...current, [task.task_id]: { source, status: "error" } }));
      } finally {
        if (titleCalls.current.get(key) === controller) titleCalls.current.delete(key);
      }
    },
    [features.ai_available],
  );

  useEffect(
    () => () => {
      titleCalls.current.forEach((controller) => controller.abort());
      titleCalls.current.clear();
      requestedTitles.current.clear();
    },
    [],
  );

  useEffect(() => {
    const available = 2 - titleCalls.current.size;
    if (available <= 0) return;
    tasks
      .filter(
        (task) =>
          task.title &&
          !task.title_zh &&
          !/[\u3400-\u9fff]/.test(task.title) &&
          !requestedTitles.current.has(`${task.task_id}:${task.title}`),
      )
      .slice(0, available)
      .forEach((task) => void translateTitle(task));
  }, [tasks, titleStates, translateTitle]);

  // Poll every 2 s while something is processing, every 15 s otherwise.
  useEffect(() => {
    void fetchTasks();
    const id = window.setInterval(fetchTasks, hasActiveTasks ? 2000 : 15000);
    return () => {
      window.clearInterval(id);
      abortRef.current?.abort();
    };
  }, [fetchTasks, hasActiveTasks]);

  useEffect(() => {
    void fetchKnowledge();
    const refresh = () => {
      void fetchTasks();
      void fetchKnowledge();
    };
    window.addEventListener(TASKS_CHANGED, refresh);
    return () => window.removeEventListener(TASKS_CHANGED, refresh);
  }, [fetchKnowledge, fetchTasks]);

  // The command palette opens the import dialog with ?import=1.
  useEffect(() => {
    if (searchParams.get("import") !== "1") return;
    setImportOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("import");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const onImported = (result: ImportResult, name: string) => {
    void fetchTasks();
    if (result.duplicate_of) {
      toast("这篇论文之前导入过", {
        description: "已按新的阅读方式开始处理；旧的阅读记录和批注仍在原来那份里。",
        action: { label: "打开已有", onClick: () => navigate(`/reader/${result.duplicate_of}`) },
        duration: 9000,
      });
    } else {
      toast.success(`已开始处理「${name.split("/").pop()}」`, { description: "原文已可阅读，生成好的版本会自动出现。" });
    }
  };

  const handleDelete = async (task: Task) => {
    const ok = await confirmAction({
      title: `删除「${taskTitle(task)}」？`,
      description: "会移除这篇论文的阅读文件和任务记录。已整理的知识笔记会保留，但不再关联到这份阅读文件。",
      confirmLabel: "删除论文",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/tasks/${task.task_id}`);
      setTasks((prev) => prev.filter((t) => t.task_id !== task.task_id));
      toast.success("论文已删除。");
    } catch {
      toast.error("删除论文失败。");
    }
  };

  const retry = async (task: Task) => {
    try {
      await api.post(`/api/tasks/${task.task_id}/retry`);
      toast.success("已重新开始处理。");
      void fetchTasks();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "重试失败，原始文件可能已过期。"));
    }
  };

  const beginExtraction = async (task: Task) => {
    if (extracting) return;
    setExtracting(task.task_id);
    try {
      const { data } = await api.post<{ paper_id: string }>(`/api/knowledge/extract/${task.task_id}`);
      void fetchKnowledge();
      toast.success("已开始整理知识笔记", {
        description: "通常需要一两分钟，可以继续阅读。",
        action: data?.paper_id
          ? { label: "查看进度", onClick: () => navigate(`/knowledge/paper/${data.paper_id}`) }
          : undefined,
      });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "知识整理启动失败，请重试。"));
    } finally {
      setExtracting("");
    }
  };

  const query = search.trim().toLowerCase();
  const searched = query
    ? tasks.filter((t) => [taskTitle(t), t.title_zh || "", t.filename].some((value) => value.toLowerCase().includes(query)))
    : tasks;
  const visibleTasks = searched.filter(
    (task) =>
      statusFilter === "all" || (statusFilter === "active" ? ACTIVE_TASK_STATUSES.has(task.status) : isReady(task)),
  );
  const counts = useMemo(
    () => ({
      all: tasks.length,
      ready: tasks.filter(isReady).length,
      active: tasks.filter((task) => ACTIVE_TASK_STATUSES.has(task.status)).length,
    }),
    [tasks],
  );
  const hasFilters = Boolean(query || statusFilter !== "all");
  const lastRead = [...tasks]
    .filter((task) => task.reading?.block_id && isReady(task))
    .sort((a, b) => (b.reading?.updated_at || "").localeCompare(a.reading?.updated_at || ""))[0];

  const aiUnavailable = features.loaded && !features.ai_available;

  return (
    <div className="page">
      <PageHeader
        eyebrow={todayLabel()}
        title="我的论文"
        description="从上次停下的地方，继续读。"
        actions={
          <Button disabled={!features.ai_available} onClick={() => setImportOpen(true)}>
            <Plus />
            导入论文
          </Button>
        }
      />
      {aiUnavailable && (
        <p role="status" className="notice">
          <AlertCircle aria-hidden="true" />
          AI 服务尚未就绪，暂时不能导入或生成新版本。已保存的论文仍可阅读，请联系管理员。
        </p>
      )}
      <ImportDialog open={importOpen} onOpenChange={setImportOpen} features={features} onImported={onImported} />
      {loading ? (
        <ListSkeleton rows={3} label="正在加载论文…" />
      ) : loadError && tasks.length === 0 ? (
        <EmptyState title="论文加载失败" description={loadError} error>
          <Button onClick={() => void fetchTasks()}>重新加载</Button>
        </EmptyState>
      ) : tasks.length === 0 ? (
        <>
          <section className="library-welcome ep-enter">
            <div>
              <h2>
                从一篇论文，
                <br />
                开始读懂。
              </h2>
              <p>保留完整正文、图表和公式，按需要切换阅读版本。遇到生词点一下就有释义，有疑问就地提问。</p>
              <Button size="lg" disabled={!features.ai_available} onClick={() => setImportOpen(true)}>
                <Plus />
                导入第一篇论文
              </Button>
            </div>
            <ReadingDemo />
          </section>
          <div className="welcome-steps ep-stagger">
            {[
              { icon: <Upload />, title: "导入", text: "上传 PDF，或粘贴 arXiv、OpenReview 链接。原文马上就能读。" },
              {
                icon: <MessageCircleQuestion />,
                title: "阅读与提问",
                text: "原文、中文、简化英文、双语对照随时切换，划线和批注跟着内容走。",
              },
              { icon: <Sparkles />, title: "整理与复习", text: "把发现、概念和生词整理成笔记与卡片，定期复习。" },
            ].map((step) => (
              <div className="welcome-step" key={step.title}>
                <span className="welcome-step-icon" aria-hidden="true">
                  {step.icon}
                </span>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            ))}
          </div>
        </>
      ) : (
        <>
          {lastRead && !hasFilters && (
            <section className="continue-section ep-enter" aria-label="继续阅读">
              <div className="continue-paper">
                <div className="continue-paper-copy">
                  <span className="continue-kicker">
                    <BookOpen size={15} aria-hidden="true" />
                    继续阅读
                  </span>
                  <h3>{taskTitle(lastRead)}</h3>
                  <PaperTitleSubtitle
                    task={lastRead}
                    state={titleStates[lastRead.task_id]}
                    retry={() => void translateTitle(lastRead)}
                  />
                  <p className="continue-meta">
                    <span>{lastRead.reading?.page ? `上次读到第 ${lastRead.reading.page} 页` : "已有阅读记录"}</span>
                    <span>{friendlyDate(lastRead.reading?.updated_at)}</span>
                    <span>{MODE_META[lastRead.mode || "translate"].label}</span>
                  </p>
                </div>
                <div className="continue-actions">
                  <span className="paper-stack" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                  <Button size="lg" onClick={() => navigate(`/reader/${lastRead.task_id}`)}>
                    继续阅读
                    <ArrowRight />
                  </Button>
                </div>
              </div>
            </section>
          )}
          <section className="section ep-enter" style={{ "--ep-delay": "60ms" } as React.CSSProperties} aria-label="论文列表">
            <div className="section-heading">
              <h2>
                全部论文 <span className="section-count">{tasks.length}</span>
              </h2>
            </div>
            <div className="section-toolbar">
              <SegmentedControl
                ariaLabel="筛选论文状态"
                value={statusFilter}
                onChange={setStatusFilter}
                options={[
                  { value: "all", label: "全部", ariaLabel: "全部" },
                  { value: "ready", label: "可阅读", hint: counts.ready || undefined, ariaLabel: "可阅读" },
                  { value: "active", label: "处理中", hint: counts.active || undefined, ariaLabel: "处理中" },
                ]}
              />
              <div className="search-field">
                <Search aria-hidden="true" />
                <Input
                  aria-label="按标题搜索论文"
                  placeholder="搜索标题或文件名"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                {search && (
                  <button type="button" className="search-clear" aria-label="清除论文搜索" onClick={() => setSearch("")}>
                    <X size={14} />
                  </button>
                )}
              </div>
            </div>
            {visibleTasks.length ? (
              <div className="paper-list ep-stagger">
                {visibleTasks.map((task) => {
                  const ready = isReady(task);
                  const failed = isFailed(task);
                  const processing = ACTIVE_TASK_STATUSES.has(task.status);
                  const mode = task.mode || "translate";
                  const notes = knowledge.get(task.task_id);
                  const open = () => navigate(`/reader/${task.task_id}`);
                  return (
                    <article key={task.task_id} className="paper-row">
                      <span className={cn("paper-glyph", `is-${mode}`)} aria-hidden="true">
                        {MODE_META[mode].glyph}
                      </span>
                      <div className="paper-row-text">
                        <h3>
                          {ready ? (
                            <button type="button" className="paper-title" title={taskTitle(task)} onClick={open}>
                              {taskTitle(task)}
                            </button>
                          ) : (
                            <span className="paper-title" title={taskTitle(task)}>
                              {taskTitle(task)}
                            </span>
                          )}
                        </h3>
                        <PaperTitleSubtitle
                          task={task}
                          state={titleStates[task.task_id]}
                          retry={() => void translateTitle(task)}
                        />
                        <div className="paper-meta">
                          <StatusPill task={task} />
                          <span>{friendlyDate(task.created_at)}导入</span>
                          {task.reading?.page && <span>读到第 {task.reading.page} 页</span>}
                          {task.highlight && <span>AI 标注重点</span>}
                          {notes?.status === "completed" && <span>已整理笔记</span>}
                          {notes?.status === "extracting" && <span>正在整理笔记…</span>}
                        </div>
                        {processing && (
                          <div className="paper-progress">
                            <div className="paper-progress-label">
                              <span>{task.message || "正在准备论文"}</span>
                              {typeof task.percent === "number" && <span>{task.percent}%</span>}
                            </div>
                            <Progress value={typeof task.percent === "number" ? task.percent : undefined} />
                          </div>
                        )}
                        {failed && <p className="paper-error">{taskErrorLabel(task)}</p>}
                      </div>
                      <div className="paper-row-actions">
                        {ready && (
                          <Button size="sm" variant="outline" onClick={open}>
                            {task.status !== "completed" ? "先读原文" : task.reading?.block_id ? "继续阅读" : "开始阅读"}
                            <ArrowRight />
                          </Button>
                        )}
                        {failed && (
                          <Button size="sm" variant="secondary" onClick={() => void retry(task)}>
                            <RotateCcw />
                            重试
                          </Button>
                        )}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" aria-label={`${taskTitle(task)} 的更多操作`}>
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {ready && (
                              <DropdownMenuItem onSelect={() => navigate(`/reader/${task.task_id}?panel=summary`)}>
                                <PanelRight />
                                打开论文概览
                              </DropdownMenuItem>
                            )}
                            {notes && notes.status === "completed" ? (
                              <DropdownMenuItem onSelect={() => navigate(`/knowledge/paper/${notes.id}`)}>
                                <NotebookPen />
                                查看知识笔记
                              </DropdownMenuItem>
                            ) : task.status === "completed" ? (
                              <DropdownMenuItem
                                disabled={Boolean(extracting) || notes?.status === "extracting"}
                                onSelect={() => void beginExtraction(task)}
                              >
                                {extracting === task.task_id ? <Loader2 className="spin" /> : <NotebookPen />}
                                {notes?.status === "extracting"
                                  ? "知识笔记整理中"
                                  : extracting === task.task_id
                                    ? "正在启动整理…"
                                    : "整理知识笔记"}
                              </DropdownMenuItem>
                            ) : null}
                            {(ready || notes) && <DropdownMenuSeparator />}
                            <DropdownMenuItem danger onSelect={() => void handleDelete(task)}>
                              <Trash2 />
                              删除论文
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="card">
                <EmptyState title="没有符合条件的论文" description="试试其他标题，或清除筛选。" icon={<FileSearch />}>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setSearch("");
                      setStatusFilter("all");
                    }}
                  >
                    清除筛选
                  </Button>
                </EmptyState>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
};

export default Dashboard;
