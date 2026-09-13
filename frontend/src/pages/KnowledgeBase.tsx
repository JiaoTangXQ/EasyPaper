import { useWorkspaceValue, useWorkspaceScroll } from "@/components/workspace/useWorkspaceMemory";
import { useState, useEffect, useCallback } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, EmptyState } from "@/components/workspace/PageHeader";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  FileText,
  Search,
  Download,
  Trash2,
  BookOpen,
  Network,
  Loader2,
  MoreHorizontal,
  ArrowRight,
  NotebookPen,
} from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";

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

export default function KnowledgeBase() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [search, setSearch] = useWorkspaceValue("knowledge:search");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState("");
  const [exporting, setExporting] = useState(false);
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
  const processing = papers.some((p) => ["pending", "extracting"].includes(p.extraction_status));
  useEffect(() => {
    void fetchPapers();
  }, [fetchPapers]);
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void fetchPapers(), 4000);
    return () => window.clearInterval(timer);
  }, [processing, fetchPapers]);
  const handleDelete = async (paperId: string) => {
    if (!window.confirm("确定删除这篇论文的知识笔记、关系和复习卡吗？此操作无法撤销。")) return;
    try {
      await api.delete(`/api/knowledge/papers/${paperId}`);
      setPapers((old) => old.filter((p) => p.id !== paperId));
      toast.success("知识笔记已删除。");
    } catch (err) {
      toast.error(getApiErrorMessage(err, "删除失败，请重试。"));
    }
  };
  const handleExport = async (format: string) => {
    try {
      let url = "";
      let filename = "";
      switch (format) {
        case "json":
          url = "/api/knowledge/export/json";
          filename = "easypaper_knowledge.json";
          break;
        case "bibtex":
          url = "/api/knowledge/export/bibtex";
          filename = "easypaper_references.bib";
          break;
        case "obsidian":
          url = "/api/knowledge/export/obsidian";
          filename = "easypaper_vault.zip";
          break;
        case "csv":
          url = "/api/knowledge/export/csv";
          filename = "easypaper_csv.zip";
          break;
        case "csl":
          url = "/api/knowledge/export/csl-json";
          filename = "easypaper_references.json";
          break;
        default:
          return;
      }

      const response = await api.get(url, { responseType: "blob" });
      const blob = new Blob([response.data]);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.parentNode?.removeChild(link);
      URL.revokeObjectURL(link.href);
      toast.success(`已导出为 ${format.toUpperCase()}`);
    } catch {
      toast.error("导出失败。");
    }
  };

  const filtered = papers.filter((p) => (p.title || "").toLowerCase().includes(search.trim().toLowerCase()));
  const retry = async (paper: Paper) => {
    if (!paper.task_id || retrying) return;
    setRetrying(paper.id);
    try {
      await api.post(`/api/knowledge/extract/${paper.task_id}`);
      await fetchPapers();
      toast.success("已重新开始整理。");
    } catch (err) {
      toast.error(getApiErrorMessage(err, "重试失败。"));
    } finally {
      setRetrying("");
    }
  };
  return (
    <div className="page-stack">
      <PageHeader
        title="知识笔记"
        description="回看论文中的发现和自己的笔记。"
        actions={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" disabled={exporting || !papers.length}>
                {exporting ? <Loader2 className="animate-spin" /> : <Download />}导出
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {[
                ["json", "知识备份 · JSON"],
                ["obsidian", "Obsidian 笔记 · ZIP"],
                ["bibtex", "文献引用 · BibTeX"],
                ["csl", "文献引用 · CSL-JSON"],
                ["csv", "论文表格 · CSV ZIP"],
              ].map(([format, label]) => (
                <DropdownMenuItem
                  key={format}
                  onSelect={() => {
                    setExporting(true);
                    void handleExport(format).finally(() => setExporting(false));
                  }}
                >
                  {label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        }
      />
      <nav className="knowledge-nav" aria-label="知识浏览方式">
        <NavLink end to="/knowledge">
          <NotebookPen size={17} />
          按论文查看
        </NavLink>
        <NavLink to="/knowledge/graph">
          <Network size={17} />
          关联图谱
        </NavLink>
      </nav>
      {loading ? (
        <div className="workspace-empty" role="status">
          <Loader2 className="animate-spin text-primary" />
          <p>正在加载知识笔记…</p>
        </div>
      ) : error ? (
        <EmptyState title="知识笔记加载失败" description={error} error>
          <Button onClick={() => void fetchPapers()}>重试</Button>
        </EmptyState>
      ) : (
        <section>
          <div className="section-heading">
            <h2>
              论文 <span className="text-sm font-normal text-muted-foreground">{papers.length}</span>
            </h2>
            <div className="search-field">
              <Search size={16} />
              <Input
                aria-label="搜索知识笔记中的论文"
                placeholder="搜索论文标题"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
          {filtered.length ? (
            <div className="paper-list">
              {filtered.map((paper) => {
                const failed = ["error", "failed"].includes(paper.extraction_status);
                return (
                  <article key={paper.id} className="paper-row">
                    <div className="paper-row-main">
                      <FileText size={20} />
                      <div className="paper-row-text">
                        <button className="paper-title" onClick={() => navigate(`/knowledge/paper/${paper.id}`)}>
                          {paper.title || "未命名论文"}
                        </button>
                        <div className="paper-meta">
                          <span
                            className={`task-status ${paper.extraction_status === "completed" ? "is-ready" : failed ? "is-error" : "is-pending"}`}
                          >
                            {paper.extraction_status === "completed" ? "已整理" : failed ? "整理失败" : "正在整理知识"}
                          </span>
                          {paper.year && <span>{paper.year}</span>}
                          {paper.venue && <span>{paper.venue}</span>}
                        </div>
                        {paper.doi && <p className="text-xs text-muted-foreground mt-2 break-all">DOI: {paper.doi}</p>}
                      </div>
                    </div>
                    <div className="paper-row-actions">
                      <Button size="sm" variant="outline" onClick={() => navigate(`/knowledge/paper/${paper.id}`)}>
                        查看笔记
                        <ArrowRight />
                      </Button>
                      {failed && paper.task_id && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={Boolean(retrying)}
                          onClick={() => void retry(paper)}
                        >
                          {retrying === paper.id ? "启动中…" : "重新整理"}
                        </Button>
                      )}
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" aria-label={`${paper.title} 的更多操作`}>
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {paper.task_id && (
                            <>
                              <DropdownMenuItem onSelect={() => navigate(`/reader/${paper.task_id}`)}>
                                <BookOpen className="mr-2 h-4 w-4" />
                                继续阅读
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                            </>
                          )}
                          <DropdownMenuItem className="text-destructive" onSelect={() => void handleDelete(paper.id)}>
                            <Trash2 className="mr-2 h-4 w-4" />
                            删除知识笔记
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState
              title={search ? "没有匹配的论文" : "还没有知识笔记"}
              description={search ? "试试其他标题，或清除搜索。" : "在“我的论文”的更多操作中，选择“整理知识笔记”。"}
            >
              <Button onClick={() => (search ? setSearch("") : navigate("/dashboard"))}>
                {search ? "清除搜索" : "选择一篇论文"}
              </Button>
            </EmptyState>
          )}
        </section>
      )}
    </div>
  );
}
