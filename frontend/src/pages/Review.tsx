import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowUpRight, BookA, GraduationCap, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { PageHeader, EmptyState } from "@/components/workspace/PageHeader";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { announceReviewChanged } from "@/lib/session";
import { cn } from "@/lib/utils";

type Deck = "cards" | "terms";
type Flashcard = { id: string; paper_id: string; front: string; back: string; tags: string[]; difficulty: number };
type Term = {
  id: string;
  term: string;
  meaning: string;
  definition: string;
  source_quote: string;
  paper_id?: string | null;
  task_id?: string | null;
  block_id?: string | null;
};
type Item = { kind: "card"; card: Flashcard } | { kind: "term"; term: Term };
type Rating = { value: number; label: string; desc: string; tone?: "again" | "good" };

const CARD_RATINGS: Rating[] = [
  { value: 0, label: "忘记", desc: "完全想不起来", tone: "again" },
  { value: 1, label: "困难", desc: "答错但有印象" },
  { value: 3, label: "一般", desc: "费力答对" },
  { value: 4, label: "简单", desc: "稍有犹豫" },
  { value: 5, label: "熟练", desc: "立即想起", tone: "good" },
];
const TERM_RATINGS: Rating[] = [
  { value: 0, label: "忘记", desc: "明天再看", tone: "again" },
  { value: 3, label: "模糊", desc: "想了一会儿" },
  { value: 4, label: "记得", desc: "看到就懂" },
  { value: 5, label: "很熟", desc: "不用再常看", tone: "good" },
];
const DECK_ENDPOINT: Record<Deck, string> = {
  cards: "/api/knowledge/flashcards/due?limit=20",
  terms: "/api/terms?due_only=true&limit=30",
};

function CompletionMark() {
  return (
    <svg className="done-check" viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="32" />
      <path d="M20 33l8 8 16-17" />
    </svg>
  );
}

export default function Review() {
  const [params, setParams] = useSearchParams();
  const deck: Deck = params.get("deck") === "terms" ? "terms" : "cards";
  const [counts, setCounts] = useState<Record<Deck, number | null>>({ cards: null, terms: null });
  const [items, setItems] = useState<Item[]>([]);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [reviewed, setReviewed] = useState(0);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const ratings = deck === "cards" ? CARD_RATINGS : TERM_RATINGS;

  const loadCounts = useCallback(async () => {
    const [cards, terms] = await Promise.allSettled([
      api.get<unknown[]>("/api/knowledge/flashcards/due?limit=100"),
      api.get<unknown[]>("/api/terms?due_only=true&limit=100"),
    ]);
    setCounts({
      cards: cards.status === "fulfilled" ? cards.value.data.length : null,
      terms: terms.status === "fulfilled" ? terms.value.data.length : null,
    });
  }, []);

  const loadDeck = useCallback(async (which: Deck) => {
    setLoading(true);
    setIndex(0);
    setFlipped(false);
    setReviewed(0);
    try {
      const { data } = await api.get(DECK_ENDPOINT[which]);
      const next: Item[] =
        which === "cards"
          ? (data as Flashcard[]).map((card) => ({ kind: "card", card }))
          : (data as Term[]).map((term) => ({ kind: "term", term }));
      setItems(next);
      setDone(next.length === 0);
      setError("");
    } catch (err) {
      setError(getApiErrorMessage(err, "无法加载复习内容，请重试。"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDeck(deck);
  }, [deck, loadDeck]);
  useEffect(() => {
    void loadCounts();
  }, [loadCounts]);

  const current = items[index];
  const rate = useCallback(
    async (quality: number) => {
      if (!current || submitting) return;
      setSubmitting(true);
      try {
        if (current.kind === "card") await api.post(`/api/knowledge/flashcards/${current.card.id}/review`, { quality });
        else await api.post(`/api/terms/${current.term.id}/review`, { quality });
        setReviewed((count) => count + 1);
        setCounts((old) => ({ ...old, [deck]: Math.max(0, (old[deck] ?? 1) - 1) }));
        announceReviewChanged();
        setFlipped(false);
        if (index + 1 < items.length) setIndex((value) => value + 1);
        else setDone(true);
      } catch (err) {
        toast.error(getApiErrorMessage(err, "评分未保存，请重试。当前卡片已保留。"));
      } finally {
        setSubmitting(false);
      }
    },
    [current, deck, index, items.length, submitting],
  );

  useEffect(() => {
    if (loading || error || done) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select, button, a, [contenteditable='true']"))
        return;
      if ((event.key === " " || event.key === "Enter") && !flipped) {
        event.preventDefault();
        setFlipped(true);
        return;
      }
      if (!flipped || submitting) return;
      const option = ratings[Number(event.key) - 1];
      if (option) {
        event.preventDefault();
        void rate(option.value);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [done, error, flipped, loading, rate, ratings, submitting]);

  const switchDeck = (next: Deck) => {
    const updated = new URLSearchParams(params);
    if (next === "cards") updated.delete("deck");
    else updated.set("deck", next);
    setParams(updated, { replace: true });
  };

  const sourceLink =
    current?.kind === "card"
      ? `/knowledge/paper/${current.card.paper_id}`
      : current?.kind === "term" && current.term.task_id
        ? `/reader/${current.term.task_id}${current.term.block_id ? `?block=${encodeURIComponent(current.term.block_id)}` : ""}`
        : null;

  return (
    <div className="page review-page">
      <PageHeader
        title="复习"
        description="把读过的内容，再想一遍。每次只看到期的。"
        actions={
          <SegmentedControl
            ariaLabel="复习内容"
            value={deck}
            onChange={switchDeck}
            options={[
              { value: "cards", label: "知识卡片", icon: <GraduationCap />, hint: counts.cards || undefined, ariaLabel: "知识卡片" },
              { value: "terms", label: "术语", icon: <BookA />, hint: counts.terms || undefined, ariaLabel: "术语" },
            ]}
          />
        }
      />
      {loading ? (
        <div className="review-card" aria-busy="true" role="status" aria-label="正在加载复习内容">
          <div className="review-face">
            <span className="skeleton" style={{ width: 80, height: 12 }} />
            <span className="skeleton" style={{ width: "70%", height: 28 }} />
            <span className="skeleton" style={{ width: "50%", height: 28 }} />
          </div>
        </div>
      ) : error ? (
        <EmptyState title="复习内容加载失败" description={error} error>
          <Button onClick={() => void loadDeck(deck)}>重试</Button>
        </EmptyState>
      ) : done ? (
        <section className="review-done ep-enter">
          {reviewed ? <CompletionMark /> : <span className="empty-state-icon" aria-hidden="true">{deck === "cards" ? <GraduationCap /> : <BookA />}</span>}
          <h2>{reviewed ? "本轮复习完成" : deck === "cards" ? "暂时没有到期卡片" : "今天没有待复习的术语"}</h2>
          <p>
            {reviewed
              ? `本轮复习了 ${reviewed} ${deck === "cards" ? "张卡片" : "个术语"}，评分已保存，下次会按记忆曲线安排。`
              : deck === "cards"
                ? "整理一篇论文的知识笔记后，会自动生成复习卡。"
                : "在点读或本页解读里点“记住术语”，生词会加入这里。"}
          </p>
          <div className="empty-actions">
            {deck === "cards" && counts.terms ? (
              <Button variant="secondary" onClick={() => switchDeck("terms")}>
                <BookA />
                复习 {counts.terms} 个术语
              </Button>
            ) : deck === "terms" && counts.cards ? (
              <Button variant="secondary" onClick={() => switchDeck("cards")}>
                <GraduationCap />
                复习 {counts.cards} 张卡片
              </Button>
            ) : (
              <Button variant="secondary" asChild>
                <Link to={deck === "terms" ? "/knowledge/terms" : "/dashboard"}>{deck === "terms" ? "打开术语本" : "返回论文"}</Link>
              </Button>
            )}
            <Button onClick={() => void loadDeck(deck)}>
              <RotateCcw />
              {reviewed ? "检查下一轮" : "刷新"}
            </Button>
          </div>
        </section>
      ) : current ? (
        <>
          <div className="review-progress" aria-live="polite">
            <div className="review-progress-row">
              <span>
                第 {index + 1} / {items.length} {deck === "cards" ? "张" : "个"}
              </span>
              <span>已复习 {reviewed}</span>
            </div>
            <Progress value={(reviewed / items.length) * 100} aria-label="本轮复习进度" />
          </div>
          <div className="flip-stage ep-enter" key={current.kind === "card" ? current.card.id : current.term.id}>
            <article
              className={cn("review-card", flipped && "is-flipped")}
              onClick={() => !flipped && setFlipped(true)}
            >
              <div className="review-face" aria-hidden={flipped}>
                <span className="review-face-label">{current.kind === "card" ? "问题" : "这个术语是什么意思？"}</span>
                {current.kind === "card" ? (
                  <h2>{current.card.front}</h2>
                ) : (
                  <>
                    <h2 lang="en" style={{ fontFamily: "var(--font-serif)" }}>
                      {current.term.term}
                    </h2>
                    {current.term.source_quote && current.term.source_quote !== current.term.term ? (
                      <p className="review-quote" lang="en">
                        {current.term.source_quote}
                      </p>
                    ) : null}
                  </>
                )}
              </div>
              <div className="review-face review-face-back" aria-hidden={!flipped}>
                {flipped ? (
                  <>
                    <span className="review-face-label">{current.kind === "card" ? "答案" : current.term.term}</span>
                    {current.kind === "card" ? (
                      <div className="review-answer" id="review-answer">
                        <p>{current.card.back}</p>
                      </div>
                    ) : (
                      <div id="review-answer" style={{ display: "grid", gap: 12, justifyItems: "center" }}>
                        <h2>{current.term.meaning || "尚未补充中文含义"}</h2>
                        {current.term.definition ? <p className="review-answer">{current.term.definition}</p> : null}
                      </div>
                    )}
                    {sourceLink ? (
                      <Link className="review-source" to={sourceLink} onClick={(event) => event.stopPropagation()}>
                        {current.kind === "card" ? "查看来源论文" : "回到原文"}
                        <ArrowUpRight size={14} style={{ display: "inline", marginLeft: 3 }} />
                      </Link>
                    ) : null}
                  </>
                ) : null}
              </div>
            </article>
          </div>
          {current.kind === "card" && current.card.tags?.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 6 }}>
              {current.card.tags.map((tag) => (
                <span key={tag} className="pill">
                  {tag}
                </span>
              ))}
            </div>
          )}
          {!flipped ? (
            <div className="review-reveal">
              <Button size="lg" onClick={() => setFlipped(true)} aria-expanded={false} aria-controls="review-answer">
                显示答案
              </Button>
              <p className="review-hint">
                点卡片或按 <kbd>空格</kbd> 翻面
              </p>
            </div>
          ) : (
            <section aria-label="评价掌握程度" style={{ display: "grid", gap: 12 }}>
              <div className="review-ratings" style={{ "--rating-count": ratings.length } as React.CSSProperties}>
                {ratings.map((option, position) => (
                  <button
                    key={option.value}
                    type="button"
                    data-tone={option.tone}
                    disabled={submitting}
                    onClick={() => void rate(option.value)}
                  >
                    {option.label}
                    <span>{option.desc}</span>
                    <kbd aria-hidden="true">{position + 1}</kbd>
                  </button>
                ))}
              </div>
              <p className="review-hint" role={submitting ? "status" : undefined}>
                {submitting ? "正在保存评分…" : `也可以按 1–${ratings.length} 键快速评分`}
              </p>
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}
