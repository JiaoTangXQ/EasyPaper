import { useWorkspaceValue, useWorkspaceScroll } from "@/components/workspace/useWorkspaceMemory";
import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { isCancel } from "axios";
import { Button } from "@/components/ui/button";
import { PageHeader, EmptyState } from "@/components/workspace/PageHeader";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Upload,
  FileText,
  ArrowRight,
  Clock,
  CheckCircle,
  AlertCircle,
  Languages,
  BookOpen,
  Trash2,
  Search,
  X,
  Plus,
  Loader2,
  MoreHorizontal,
  NotebookPen,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";

const MAX_FILE_SIZE_MB = 50;
const ACTIVE_TASK_STATUSES = new Set(["pending", "processing", "parsing", "rewriting", "rendering", "highlighting"]);

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
  mode?: "translate" | "simplify";
  highlight?: boolean;
  can_read?: boolean;
  reading?: { block_id: string; page?: number; understood_count: number; updated_at: string };
}

const taskTitle = (task: Task) => task.title?.trim() || task.filename;
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

const Dashboard = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useWorkspaceValue("papers:status", "all");
  const [extracting, setExtracting] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<"translate" | "simplify">("translate");
  const [search, setSearch] = useWorkspaceValue("papers:search");
  const [highlight, setHighlight] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [inputMode, setInputMode] = useState<"file" | "url">("file");
  const [pdfUrl, setPdfUrl] = useState("");
  const [urlLoading, setUrlLoading] = useState(false);
  const navigate = useNavigate();
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
      // Surface the failure once per error streak instead of silently
      // retrying forever, but don't spam a toast on every poll.
      if (!errorShownRef.current) {
        toast.error("无法加载任务列表，正在重试…");
        errorShownRef.current = true;
      }
    }
  }, []);

  const translateTitle = useCallback(async (task: Task) => {
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
  }, []);

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
    const missing = tasks.filter(
      (task) =>
        task.title &&
        !task.title_zh &&
        !/[\u3400-\u9fff]/.test(task.title) &&
        !requestedTitles.current.has(`${task.task_id}:${task.title}`),
    );
    missing.slice(0, available).forEach((task) => void translateTitle(task));
  }, [tasks, titleStates, translateTitle]);

  // 活跃任务期间 2 秒刷新一次，空闲时降到 15 秒。
  useEffect(() => {
    fetchTasks();
    const intervalMs = hasActiveTasks ? 2000 : 15000;
    const id = window.setInterval(fetchTasks, intervalMs);

    return () => {
      window.clearInterval(id);
      abortRef.current?.abort();
    };
  }, [fetchTasks, hasActiveTasks]);

  const validateFile = (file: File): boolean => {
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      toast.error("仅支持 PDF 文件。");
      return false;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      toast.error(`文件大小超过 ${MAX_FILE_SIZE_MB}MB 限制。`);
      return false;
    }
    return true;
  };

  const uploadFile = async (file: File) => {
    if (uploadProgress !== null || !validateFile(file)) return;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("mode", mode);
    formData.append("highlight", String(highlight));

    setUploadProgress(0);
    try {
      await api.post("/api/upload", formData, {
        onUploadProgress: (e) => {
          if (e.total) {
            setUploadProgress(Math.round((e.loaded / e.total) * 100));
          }
        },
      });
      toast.success(`"${file.name}" 上传成功。`);
      setImportOpen(false);
      fetchTasks();
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "上传失败。"));
    } finally {
      setUploadProgress(null);
    }
  };

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    e.target.value = "";
    uploadFile(file);
  };

  // Drag & Drop handlers
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
  };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadFile(file);
  };

  const handleDelete = async (taskId: string) => {
    if (!window.confirm("删除后会移除这篇论文的阅读文件和任务记录，知识库导出内容也可能受影响。确定删除吗？")) return;
    try {
      await api.delete(`/api/tasks/${taskId}`);
      setTasks((prev) => prev.filter((t) => t.task_id !== taskId));
      toast.success("任务已删除。");
    } catch {
      toast.error("删除任务失败。");
    }
  };

  const submitUrl = async () => {
    const trimmed = pdfUrl.trim();
    if (!trimmed) {
      toast.error("请输入 PDF 链接。");
      return;
    }
    try {
      new URL(trimmed.startsWith("http") ? trimmed : `https://${trimmed}`);
    } catch {
      toast.error("请输入有效的链接。");
      return;
    }
    setUrlLoading(true);
    try {
      await api.post("/api/upload-url", {
        url: trimmed,
        mode,
        highlight,
      });
      toast.success("PDF 下载成功，已开始处理！");
      setPdfUrl("");
      setImportOpen(false);
      fetchTasks();
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "从链接下载 PDF 失败。"));
    } finally {
      setUrlLoading(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle className="h-4 w-4" />;
      case "processing":
      case "parsing":
      case "rewriting":
      case "rendering":
      case "highlighting":
        return <Clock className="h-3.5 w-3.5" />;
      case "failed":
      case "error":
        return <AlertCircle className="h-4 w-4" />;
      case "cancelled":
        return <X className="h-4 w-4" />;
      default:
        return <Clock className="h-4 w-4" />;
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case "pending":
        return "排队中";
      case "processing":
        return "处理中";
      case "parsing":
        return "解析中";
      case "rewriting":
        return "正在生成阅读版本";
      case "rendering":
        return "正在排版";
      case "highlighting":
        return "高亮中";
      case "completed":
        return "完成";
      case "failed":
      case "error":
        return "失败";
      case "cancelled":
        return "已取消";
      default:
        return status;
    }
  };

  const filteredTasks = search
    ? tasks.filter((t) =>
        [taskTitle(t), t.title_zh || "", t.filename].some((value) =>
          value.toLowerCase().includes(search.toLowerCase()),
        ),
      )
    : tasks;

  const lastRead = [...tasks]
    .filter((task) => task.reading?.block_id && (task.status === "completed" || task.can_read))
    .sort((a, b) => (b.reading?.updated_at || "").localeCompare(a.reading?.updated_at || ""))[0];
  const hasFilters = Boolean(search || statusFilter !== "all");
  const visibleTasks = filteredTasks.filter(
    (task) =>
      statusFilter === "all" ||
      (statusFilter === "active"
        ? ACTIVE_TASK_STATUSES.has(task.status)
        : task.status === "completed" || task.can_read),
  );
  const beginExtraction = async (task: Task) => {
    if (extracting) return;
    setExtracting(task.task_id);
    try {
      await api.post(`/api/knowledge/extract/${task.task_id}`);
      toast.success("已开始整理，可在知识笔记中查看进度。");
    } catch (error) {
      toast.error(getApiErrorMessage(error, "知识整理启动失败，请重试。"));
    } finally {
      setExtracting("");
    }
  };
  return (
    <div className="page-stack">
      <PageHeader
        title="我的论文"
        description="从上次停下的地方，继续读。"
        actions={
          <Button onClick={() => setImportOpen(true)}>
            <Plus />
            导入论文
          </Button>
        }
      />
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="import-dialog">
          <DialogHeader>
            <DialogTitle>导入论文</DialogTitle>
            <DialogDescription>原文会保留，生成译文时仍可先读原文。</DialogDescription>
          </DialogHeader>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium mb-2">同时生成</legend>
            <div className="import-options">
              <label className="import-option">
                <input
                  type="radio"
                  name="reading-result"
                  checked={mode === "translate"}
                  onChange={() => setMode("translate")}
                  disabled={uploadProgress !== null || urlLoading}
                />
                <Languages size={18} />
                中文译文
              </label>
              <label className="import-option">
                <input
                  type="radio"
                  name="reading-result"
                  checked={mode === "simplify"}
                  onChange={() => setMode("simplify")}
                  disabled={uploadProgress !== null || urlLoading}
                />
                <BookOpen size={18} />
                简化英文
              </label>
            </div>
          </fieldset>
          <Tabs value={inputMode} onValueChange={(value) => setInputMode(value as "file" | "url")}>
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="file">PDF 文件</TabsTrigger>
              <TabsTrigger value="url">论文链接</TabsTrigger>
            </TabsList>
            <TabsContent value="file">
              <div
                className={cn("import-dropzone", dragging && "is-dragging")}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <Upload size={27} className="text-primary" />
                <h3 className="font-medium">选择要阅读的 PDF</h3>
                <p>也可拖拽到这里 · 最大 {MAX_FILE_SIZE_MB} MB</p>
                <Button disabled={uploadProgress !== null} onClick={() => fileInputRef.current?.click()}>
                  {uploadProgress !== null ? <Loader2 className="animate-spin" /> : <FileText />}
                  {uploadProgress !== null ? "正在上传…" : "选择 PDF"}
                </Button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  hidden
                  onChange={handleUpload}
                  aria-label="上传 PDF"
                />
                {uploadProgress !== null && (
                  <div className="w-full space-y-2" role="status">
                    <p>上传文件 {uploadProgress}%</p>
                    <Progress value={uploadProgress} />
                  </div>
                )}
              </div>
            </TabsContent>
            <TabsContent value="url">
              <form
                className="space-y-3 py-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void submitUrl();
                }}
              >
                <label htmlFor="paper-url" className="text-sm font-medium">
                  PDF 链接
                </label>
                <Input
                  id="paper-url"
                  type="url"
                  placeholder="粘贴 arXiv、OpenReview 或 PDF 直链"
                  value={pdfUrl}
                  onChange={(e) => setPdfUrl(e.target.value)}
                  disabled={urlLoading}
                />
                <Button type="submit" disabled={urlLoading || !pdfUrl.trim()}>
                  {urlLoading ? <Loader2 className="animate-spin" /> : <ArrowRight />}
                  {urlLoading ? "正在获取论文…" : "导入链接"}
                </Button>
              </form>
            </TabsContent>
          </Tabs>
          <details className="import-optional">
            <summary>可选设置</summary>
            <label>
              <input
                type="checkbox"
                checked={highlight}
                onChange={(e) => setHighlight(e.target.checked)}
                disabled={uploadProgress !== null || urlLoading}
              />
              <span>
                生成时自动标注重点
                <br />
                <span className="text-xs">AI 标注供阅读参考，也可以自行划线。</span>
              </span>
            </label>
          </details>
          <p className="text-xs text-muted-foreground">其他阅读版本可在阅读器中生成。关闭面板不会取消已提交的任务。</p>
        </DialogContent>
      </Dialog>
      {loading ? (
        <div className="workspace-empty" role="status">
          <Loader2 className="animate-spin text-primary" />
          <p>正在加载论文…</p>
        </div>
      ) : loadError && tasks.length === 0 ? (
        <EmptyState title="论文加载失败" description={loadError} error>
          <Button onClick={() => void fetchTasks()}>重新加载</Button>
        </EmptyState>
      ) : tasks.length === 0 ? (
        <section className="library-welcome">
          <div>
            <h2>
              从一篇论文，
              <br />
              开始读懂。
            </h2>
            <p>保留完整正文、图表和公式，按需要切换阅读版本。遇到疑问就地提问，理解留在批注里。</p>
            <Button onClick={() => setImportOpen(true)}>
              <Plus />
              导入第一篇论文
            </Button>
          </div>
          <div className="language-example">
            <span>阅读方式示例</span>
            <p lang="en">
              Read the paper.
              <br />
              <mark>Keep your understanding alongside it.</mark>
            </p>
            <p>
              读完论文，
              <br />
              <mark>把理解留在原文旁边。</mark>
            </p>
          </div>
        </section>
      ) : (
        <>
          {lastRead && !hasFilters && (
            <section className="continue-section">
              <h2>继续阅读</h2>
              <div className="continue-paper">
                <div>
                  <h3>{taskTitle(lastRead)}</h3>
                  <PaperTitleSubtitle
                    task={lastRead}
                    state={titleStates[lastRead.task_id]}
                    retry={() => void translateTitle(lastRead)}
                  />
                  <p>
                    {lastRead.reading?.page ? `上次读到第 ${lastRead.reading.page} 页` : "已有阅读记录"} ·
                    阅读位置已保存
                  </p>
                </div>
                <Button onClick={() => navigate(`/reader/${lastRead.task_id}`)}>
                  继续阅读
                  <ArrowRight />
                </Button>
              </div>
            </section>
          )}
          <section aria-label="论文列表">
            <div className="section-heading">
              <h2>
                全部论文 <span className="text-sm font-normal text-muted-foreground">{tasks.length}</span>
              </h2>
              <div className="search-field">
                <Search size={16} />
                <Input
                  aria-label="按标题搜索论文"
                  placeholder="搜索论文标题"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-2 mb-4" aria-label="筛选论文状态">
              {(
                [
                  ["all", "全部"],
                  ["ready", "可阅读"],
                  ["active", "处理中"],
                ] as const
              ).map(([value, label]) => (
                <Button
                  key={value}
                  size="sm"
                  variant={statusFilter === value ? "secondary" : "ghost"}
                  aria-pressed={statusFilter === value}
                  onClick={() => setStatusFilter(value)}
                >
                  {label}
                </Button>
              ))}
            </div>
            {visibleTasks.length ? (
              <div className="paper-list">
                {visibleTasks.map((task) => {
                  const ready = task.status === "completed" || task.can_read;
                  const failed = task.status === "failed" || task.status === "error";
                  const processing = ACTIVE_TASK_STATUSES.has(task.status);
                  return (
                    <article key={task.task_id} className="paper-row">
                      <div className="paper-row-main">
                        <FileText size={20} />
                        <div className="paper-row-text">
                          <h3 className="paper-title" title={taskTitle(task)}>
                            {taskTitle(task)}
                          </h3>
                          <PaperTitleSubtitle
                            task={task}
                            state={titleStates[task.task_id]}
                            retry={() => void translateTitle(task)}
                          />
                          <div className="paper-meta">
                            <span
                              className={cn(
                                "task-status",
                                task.status === "completed"
                                  ? "is-ready"
                                  : failed
                                    ? "is-error"
                                    : processing
                                      ? "is-pending"
                                      : "",
                              )}
                            >
                              {getStatusIcon(task.status)}
                              {task.status === "completed"
                                ? `${task.mode === "simplify" ? "简化英文" : "中文译文"}可读`
                                : getStatusLabel(task.status)}
                            </span>
                            <span>{new Date(task.created_at).toLocaleDateString()}</span>
                            {task.reading?.page && <span>上次第 {task.reading.page} 页</span>}
                            {task.highlight && <span>已启用 AI 标注</span>}
                          </div>
                          {processing && (
                            <div className="paper-progress">
                              <div className="flex justify-between gap-3 text-xs text-muted-foreground">
                                <span>{task.message || "正在准备论文"}</span>
                                {typeof task.percent === "number" && <span>{task.percent}%</span>}
                              </div>
                              {typeof task.percent === "number" && <Progress value={task.percent} className="h-1" />}
                            </div>
                          )}
                          {failed && (
                            <p className="text-sm text-destructive mt-3">
                              {task.message || "生成失败，可以重新处理。"}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="paper-row-actions">
                        {ready && (
                          <Button size="sm" variant="outline" onClick={() => navigate(`/reader/${task.task_id}`)}>
                            {task.status !== "completed"
                              ? "先读原文"
                              : task.reading?.block_id
                                ? "继续阅读"
                                : "开始阅读"}
                            <ArrowRight />
                          </Button>
                        )}
                        {task.status === "completed" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => navigate(`/reader/${task.task_id}?panel=summary`)}
                          >
                            概览
                          </Button>
                        )}
                        {failed && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={async () => {
                              try {
                                await api.post(`/api/tasks/${task.task_id}/retry`);
                                void fetchTasks();
                              } catch {
                                toast.error("重试失败，原始文件可能已过期。");
                              }
                            }}
                          >
                            重试
                          </Button>
                        )}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" aria-label={`${taskTitle(task)} 的更多操作`}>
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {task.status === "completed" && (
                              <>
                                <DropdownMenuItem
                                  disabled={Boolean(extracting)}
                                  onSelect={() => void beginExtraction(task)}
                                >
                                  <NotebookPen className="mr-2 h-4 w-4" />
                                  {extracting === task.task_id ? "正在启动整理…" : "整理知识笔记"}
                                </DropdownMenuItem>
                                <DropdownMenuItem onSelect={() => navigate("/knowledge")}>
                                  <BookOpen className="mr-2 h-4 w-4" />
                                  查看知识笔记
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                              </>
                            )}
                            <DropdownMenuItem
                              className="text-destructive"
                              onSelect={() => void handleDelete(task.task_id)}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
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
              <EmptyState title="没有符合条件的论文" description="试试其他标题，或清除筛选。">
                <Button
                  variant="outline"
                  onClick={() => {
                    setSearch("");
                    setStatusFilter("all");
                  }}
                >
                  清除筛选
                </Button>
              </EmptyState>
            )}
          </section>
        </>
      )}
    </div>
  );
};

export default Dashboard;
