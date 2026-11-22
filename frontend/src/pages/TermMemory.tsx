import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, BookA, GraduationCap, Search, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { PageHeader, EmptyState, ListSkeleton } from "@/components/workspace/PageHeader";
import KnowledgeNav from "@/components/knowledge/KnowledgeNav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { confirmAction } from "@/lib/confirm";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { dueLabel } from "@/lib/format";
import { announceReviewChanged } from "@/lib/session";

type Term = {
  id: string;
  term: string;
  meaning: string;
  definition: string;
  task_id?: string | null;
  block_id?: string | null;
  source_quote: string;
  repetitions: number;
  times_seen?: number;
  next_review: string;
};

export default function TermMemory() {
  const [terms, setTerms] = useState<Term[]>([]);
  const [filter, setFilter] = useState<"all" | "due">("all");
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(searchInput.trim()), 240);
    return () => window.clearTimeout(timer);
  }, [searchInput]);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<Term[]>("/api/terms", {
        params: { due_only: filter === "due", q: query, limit: 500 },
      });
      setTerms(data);
      setError("");
    } catch (err) {
      setError(getApiErrorMessage(err, "术语本加载失败。"));
    } finally {
      setLoading(false);
    }
  }, [filter, query]);
  useEffect(() => void load(), [load]);

  const remove = async (term: Term) => {
    const ok = await confirmAction({
      title: `删除术语“${term.term}”？`,
      description: "复习记录会一起删除。之后再次在阅读中记住它，会从头开始复习。",
      confirmLabel: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/terms/${term.id}`);
      setTerms((old) => old.filter((item) => item.id !== term.id));
      announceReviewChanged();
      toast.success("术语已删除。");
    } catch (err) {
      toast.error(getApiErrorMessage(err, "删除术语失败。"));
    }
  };

  const dueCount = terms.filter((term) => dueLabel(term.next_review).due).length;
  return (
    <div className="page">
      <div className="knowledge-head">
        <PageHeader
          title="术语本"
          description="阅读时记住的词和术语。到期的会出现在复习里。"
          actions={
            <Button asChild variant={dueCount ? "default" : "outline"}>
              <Link to="/review?deck=terms">
                <GraduationCap />
                {dueCount && filter === "all" ? `复习 ${dueCount} 个术语` : "去复习"}
              </Link>
            </Button>
          }
        />
        <KnowledgeNav />
      </div>
      <section className="section ep-enter">
        <div className="section-toolbar">
          <SegmentedControl
            ariaLabel="筛选术语"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "全部" },
              { value: "due", label: "待复习" },
            ]}
          />
          <div className="search-field">
            <Search aria-hidden="true" />
            <Input
              aria-label="搜索术语"
              placeholder="搜索术语"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
            {searchInput && (
              <button type="button" className="search-clear" aria-label="清除术语搜索" onClick={() => setSearchInput("")}>
                <X size={14} />
              </button>
            )}
          </div>
        </div>
        {error ? (
          <EmptyState title="术语本加载失败" description={error} error>
            <Button onClick={() => void load()}>重试</Button>
          </EmptyState>
        ) : loading ? (
          <ListSkeleton rows={3} label="正在加载术语…" />
        ) : terms.length === 0 ? (
          <div className="card">
            <EmptyState
              icon={<BookA />}
              title={query ? "没有匹配的术语" : filter === "due" ? "今天没有待复习术语" : "还没有保存术语"}
              description={
                query ? "试试其他拼写。" : "在点读释义或“本页解读”里点“记住术语”，这里会积累你的个人词汇。"
              }
            />
          </div>
        ) : (
          <div className="group-list ep-stagger">
            {terms.map((term) => {
              const due = dueLabel(term.next_review);
              return (
                <article key={term.id} className="term-row">
                  <h3>
                    <bdi lang="en">{term.term}</bdi>
                    <span>{term.meaning || "尚未补充中文含义"}</span>
                  </h3>
                  <Button variant="ghost" size="icon-sm" aria-label={`删除 ${term.term}`} onClick={() => void remove(term)}>
                    <Trash2 />
                  </Button>
                  {term.definition ? <p className="term-definition">{term.definition}</p> : null}
                  {term.source_quote && term.source_quote !== term.term ? (
                    <blockquote className="term-quote" lang="en">
                      {term.source_quote}
                    </blockquote>
                  ) : null}
                  <div className="term-meta">
                    <span className={due.due ? "pill is-accent" : "pill"}>{due.label}</span>
                    <span>复习 {term.repetitions} 次</span>
                    {term.times_seen && term.times_seen > 1 ? <span>遇到 {term.times_seen} 次</span> : null}
                    {term.task_id ? (
                      <Link
                        to={`/reader/${term.task_id}${term.block_id ? `?block=${encodeURIComponent(term.block_id)}` : ""}`}
                      >
                        回到原文
                        <ArrowUpRight size={12} style={{ display: "inline", marginLeft: 2 }} />
                      </Link>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
