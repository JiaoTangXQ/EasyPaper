import { useWorkspaceValue, useWorkspaceScroll } from "@/components/workspace/useWorkspaceMemory";
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  BookOpen,
  Download,
  Loader2,
  MoreHorizontal,
  NotebookPen,
  RotateCcw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, EmptyState, ListSkeleton } from "@/components/workspace/PageHeader";
import KnowledgeNav from "@/components/knowledge/KnowledgeNav";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { confirmAction } from "@/lib/confirm";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { friendlyDate } from "@/lib/format";
import { EXPORT_FORMATS, exportKnowledge, type ExportFormat } from "@/lib/knowledge-export";

interface Paper {
  id: string;
  task_id: string | null;
  title: string;
  doi: string | null;
  year: number | null;
  venue: string | null;
  extraction_status: string;
  created_at: string | null;
}

const STATUS: Record<string, { label: string; tone: string }> = {
  completed: { label: "已整理", tone: "is-ok" },
  extracting: { label: "正在整理", tone: "is-warn" },
  error: { label: "整理失败", tone: "is-danger" },
  failed: { label: "整理失败", tone: "is-danger" },
};

export function ExportMenu({ disabled }: { disabled?: boolean }) {
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const run = async (format: ExportFormat, label: string) => {
    setExporting(format);
    try {
      await exportKnowledge(format);
      toast.success(`已导出 ${label}`);
    } catch {
      toast.error("导出失败。");
    } finally {
      setExporting(null);
    }
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" disabled={disabled || exporting !== null}>
          {exporting ? <Loader2 className="spin" /> : <Download />}
          导出
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {EXPORT_FORMATS.map(({ format, label, hint }) => (
          <DropdownMenuItem key={format} onSelect={() => void run(format, label)}>
            {label}
            <span className="menu-hint" aria-hidden="true">
              {hint}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function KnowledgeBase() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [search, setSearch] = useWorkspaceValue("knowledge:search");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState("");
  const navigate = useNavigate();
  useWorkspaceScroll("knowledge", !loading);
  const fetchPapers = useCallback(async () => {
    try {
      const response = await api.get<Paper[]>("/api/knowledge/papers");
      setPapers(response.data);
      setError("");
    } catch (err) {
      setError(getApiErrorMessage(err, "无法加载知识笔记，请重试。"));
    } finally {
      setLoading(false);
    }
  }, []);
  const processing = papers.some((p) => p.extraction_status === "extracting");
  useEffect(() => {
    void fetchPapers();
  }, [fetchPapers]);
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void fetchPapers(), 4000);
    return () => window.clearInterval(timer);
  }, [processing, fetchPapers]);

  const handleDelete = async (paper: Paper) => {
    const ok = await confirmAction({
      title: `删除「${paper.title || "未命名论文"}」的知识笔记？`,
      description: "会删除这篇论文整理出的发现、概念、关系、复习卡和你的个人笔记。论文本身和阅读批注不受影响。此操作无法撤销。",
      confirmLabel: "删除笔记",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/knowledge/papers/${paper.id}`);
      setPapers((old) => old.filter((p) => p.id !== paper.id));
      toast.success("知识笔记已删除。");
    } catch (err) {
      toast.error(getApiErrorMessage(err, "删除失败，请重试。"));
    }
  };

  const startExtract = async (paper: Paper, toastMessage: string) => {
    if (!paper.task_id || retrying) return;
    setRetrying(paper.id);
    try {
      await api.post(`/api/knowledge/extract/${paper.task_id}`);
      await fetchPapers();
      toast.success(toastMessage);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "整理失败。"));
    } finally {
      setRetrying("");
    }
  };

  const query = search.trim().toLowerCase();
  const filtered = papers.filter((p) => (p.title || "").toLowerCase().includes(query));
  return (
    <div className="page">
      <div className="knowledge-head">
        <PageHeader
          title="知识笔记"
          description="论文里的发现、概念和你的想法，都整理在这里。"
          actions={<ExportMenu disabled={!papers.length} />}
        />
        <KnowledgeNav />
      </div>
      {loading ? (
        <ListSkeleton rows={3} label="正在加载知识笔记…" />
      ) : error ? (
        <EmptyState title="知识笔记加载失败" description={error} error>
          <Button onClick={() => void fetchPapers()}>重试</Button>
        </EmptyState>
      ) : (
        <section className="section ep-enter">
          <div className="section-toolbar">
            <div className="section-heading">
              <h2>
                论文 <span className="section-count">{papers.length}</span>
              </h2>
            </div>
            <div className="search-field">
              <Search aria-hidden="true" />
              <Input
                aria-label="搜索知识笔记中的论文"
                placeholder="搜索论文标题"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search && (
                <button type="button" className="search-clear" aria-label="清除知识笔记搜索" onClick={() => setSearch("")}>
                  <X size={14} />
                </button>
              )}
            </div>
          </div>
          {filtered.length ? (
            <div className="note-card-grid ep-stagger">
              {filtered.map((paper) => {
                const status = paper.extraction_status;
                const meta = STATUS[status] ?? { label: "尚未整理", tone: "" };
                const failed = status === "error" || status === "failed";
                const pending = status === "pending";
                const open = () => navigate(`/knowledge/paper/${paper.id}`);
                return (
                  <article key={paper.id} className="note-card">
                    <div className="note-card-top">
                      <span className={`pill ${meta.tone}`}>
                        {status === "extracting" ? <Loader2 className="spin" aria-hidden="true" /> : null}
                        {meta.label}
                      </span>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`${paper.title} 的更多操作`}
                            style={{ position: "relative", zIndex: 1 }}
                          >
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {paper.task_id && (
                            <>
                              <DropdownMenuItem onSelect={() => navigate(`/reader/${paper.task_id}`)}>
                                <BookOpen />
                                继续阅读
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                            </>
                          )}
                          <DropdownMenuItem danger onSelect={() => void handleDelete(paper)}>
                            <Trash2 />
                            删除知识笔记
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                    <div>
                      <h3>
                        <button type="button" onClick={open}>
                          {paper.title || "未命名论文"}
                        </button>
                      </h3>
                      <p className="note-card-meta">
                        {[paper.year, paper.venue, paper.created_at ? `${friendlyDate(paper.created_at)}加入` : null]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    </div>
                    <div className="note-card-actions">
                      <Button size="sm" variant="secondary" onClick={open}>
                        查看笔记
                        <ArrowRight />
                      </Button>
                      {(pending || failed) && paper.task_id ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={Boolean(retrying)}
                          onClick={() => void startExtract(paper, pending ? "已开始整理知识笔记。" : "已重新开始整理。")}
                        >
                          {retrying === paper.id ? <Loader2 className="spin" /> : failed ? <RotateCcw /> : <NotebookPen />}
                          {retrying === paper.id ? "启动中…" : pending ? "开始整理" : "重新整理"}
                        </Button>
                      ) : (
                        <span />
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="card">
              <EmptyState
                title={search ? "没有匹配的论文" : "还没有知识笔记"}
                description={
                  search
                    ? "试试其他标题，或清除搜索。"
                    : "打开一篇读完的论文，在“我的论文”的更多操作里选择“整理知识笔记”。"
                }
                icon={<NotebookPen />}
              >
                <Button onClick={() => (search ? setSearch("") : navigate("/dashboard"))}>
                  {search ? "清除搜索" : "选择一篇论文"}
                </Button>
              </EmptyState>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
