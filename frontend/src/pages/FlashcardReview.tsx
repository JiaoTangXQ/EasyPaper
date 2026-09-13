import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { PageHeader, EmptyState } from "@/components/workspace/PageHeader";
import { ArrowUpRight, RotateCcw, CheckCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";

interface FlashcardData {
  id: string;
  paper_id: string;
  front: string;
  back: string;
  tags: string[];
  difficulty: number;
}
const QUALITY_OPTIONS = [
  { value: 0, label: "忘记", desc: "完全想不起来" },
  { value: 1, label: "困难", desc: "答错但有印象" },
  { value: 3, label: "一般", desc: "费力答对" },
  { value: 4, label: "简单", desc: "稍有犹豫" },
  { value: 5, label: "熟练", desc: "立即想起" },
];

export default function FlashcardReview() {
  const [cards, setCards] = useState<FlashcardData[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reviewed, setReviewed] = useState(0);
  const [sessionDone, setSessionDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const fetchDueCards = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<FlashcardData[]>("/api/knowledge/flashcards/due?limit=20");
      setCards(data);
      setSessionDone(data.length === 0);
      setError("");
    } catch (err) {
      setError(getApiErrorMessage(err, "无法加载复习卡，请重试。"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void fetchDueCards();
  }, [fetchDueCards]);
  const handleReview = async (quality: number) => {
    const card = cards[currentIndex];
    if (!card || submitting) return;
    setSubmitting(true);
    try {
      await api.post(`/api/knowledge/flashcards/${card.id}/review`, { quality });
      setReviewed((count) => count + 1);
      setFlipped(false);
      if (currentIndex + 1 < cards.length) setCurrentIndex((index) => index + 1);
      else setSessionDone(true);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "评分未保存，请重试。当前卡片已保留。"));
    } finally {
      setSubmitting(false);
    }
  };
  const currentCard = cards[currentIndex];
  return (
    <div className="page-stack review-page">
      <PageHeader
        title="复习"
        description="把读过的内容，再想一遍。"
        actions={
          <Button variant="ghost" asChild>
            <Link to="/knowledge">返回知识笔记</Link>
          </Button>
        }
      />
      {loading ? (
        <div className="workspace-empty" role="status">
          <Loader2 className="animate-spin text-primary" />
          <p>正在加载到期复习卡…</p>
        </div>
      ) : error ? (
        <EmptyState title="复习卡加载失败" description={error} error>
          <Button onClick={() => void fetchDueCards()}>重试</Button>
        </EmptyState>
      ) : sessionDone ? (
        <EmptyState
          title={reviewed ? "本轮复习完成" : "暂时没有到期卡片"}
          description={
            reviewed
              ? `本轮已复习 ${reviewed} 张卡片，评分已保存。`
              : "可以回到论文继续阅读，或在知识笔记中查看已有卡片。"
          }
        >
          <Button variant="outline" asChild>
            <Link to="/dashboard">返回论文</Link>
          </Button>
          <Button
            onClick={() => {
              setCurrentIndex(0);
              setReviewed(0);
              setFlipped(false);
              void fetchDueCards();
            }}
          >
            <RotateCcw />
            {reviewed ? "检查下一轮" : "刷新到期卡片"}
          </Button>
        </EmptyState>
      ) : currentCard ? (
        <>
          <div className="space-y-3">
            <div className="review-progress" aria-live="polite">
              <span>
                本轮第 {currentIndex + 1} / {cards.length} 张
              </span>
              <span>已复习 {reviewed} 张</span>
            </div>
            <Progress value={(reviewed / cards.length) * 100} className="h-1" aria-label="本轮复习进度" />
          </div>
          <article className="review-card">
            <h2>{currentCard.front}</h2>
            {flipped && (
              <div className="review-answer" id="review-answer">
                <p>{currentCard.back}</p>
              </div>
            )}
            <div>
              <Button variant="link" asChild>
                <Link to={`/knowledge/paper/${currentCard.paper_id}`}>
                  查看来源论文
                  <ArrowUpRight />
                </Link>
              </Button>
            </div>
          </article>
          {currentCard.tags?.length > 0 && (
            <div className="flex flex-wrap justify-center gap-2">
              {currentCard.tags.map((tag) => (
                <span key={tag} className="rounded-md bg-secondary px-2 py-1 text-xs text-muted-foreground">
                  {tag}
                </span>
              ))}
            </div>
          )}
          {!flipped ? (
            <div className="text-center">
              <Button onClick={() => setFlipped(true)} aria-expanded={false} aria-controls="review-answer">
                显示答案
              </Button>
            </div>
          ) : (
            <section className="space-y-4" aria-label="评价掌握程度">
              <p className="text-center text-sm text-muted-foreground">这张卡记得怎么样？</p>
              <div className="review-ratings">
                {QUALITY_OPTIONS.map((option) => (
                  <Button
                    key={option.value}
                    variant="outline"
                    disabled={submitting}
                    onClick={() => void handleReview(option.value)}
                  >
                    {option.label}
                    <span>{option.desc}</span>
                  </Button>
                ))}
              </div>
              {submitting && (
                <p className="text-center text-sm text-muted-foreground" role="status">
                  正在保存评分…
                </p>
              )}
            </section>
          )}
        </>
      ) : null}
      {!loading && !error && sessionDone && reviewed > 0 && (
        <CheckCircle size={24} className="mx-auto text-green-700" aria-hidden="true" />
      )}
    </div>
  );
}
