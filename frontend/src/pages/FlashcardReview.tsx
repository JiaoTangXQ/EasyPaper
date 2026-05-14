import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
    ArrowLeft,
    RotateCcw,
    CheckCircle,
    Brain,
    GraduationCap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import api from "@/lib/api";

interface FlashcardData {
    id: string;
    paper_id: string;
    front: string;
    back: string;
    tags: string[];
    difficulty: number;
    srs: {
        interval_days: number;
        ease_factor: number;
        repetitions: number;
        next_review: string | null;
    };
}

const QUALITY_OPTIONS = [
    { value: 0, label: "忘记", color: "bg-red-500 hover:bg-red-600", desc: "完全想不起来" },
    { value: 1, label: "困难", color: "bg-orange-500 hover:bg-orange-600", desc: "答错但有印象" },
    { value: 3, label: "一般", color: "bg-blue-500 hover:bg-blue-600", desc: "费力答对" },
    { value: 4, label: "简单", color: "bg-green-500 hover:bg-green-600", desc: "稍有犹豫" },
    { value: 5, label: "熟练", color: "bg-emerald-500 hover:bg-emerald-600", desc: "立即想起" },
];

const FlashcardReview = () => {
    const navigate = useNavigate();
    const [cards, setCards] = useState<FlashcardData[]>([]);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [flipped, setFlipped] = useState(false);
    const [loading, setLoading] = useState(true);
    const [reviewed, setReviewed] = useState(0);
    const [sessionDone, setSessionDone] = useState(false);

    const fetchDueCards = useCallback(async () => {
        try {
            const response = await api.get("/api/knowledge/flashcards/due?limit=20");
            setCards(response.data);
            if (response.data.length === 0) {
                setSessionDone(true);
            }
        } catch {
            toast.error("加载闪卡失败。");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchDueCards();
    }, [fetchDueCards]);

    const handleReview = async (quality: number) => {
        const card = cards[currentIndex];
        if (!card) return;

        try {
            await api.post(`/api/knowledge/flashcards/${card.id}/review`, { quality });
            setReviewed((prev) => prev + 1);
            setFlipped(false);

            if (currentIndex + 1 < cards.length) {
                setCurrentIndex((prev) => prev + 1);
            } else {
                setSessionDone(true);
            }
        } catch {
            toast.error("提交复习结果失败。");
        }
    };

    if (loading) {
        return (
            <div className="flex h-[calc(100vh-8rem)] items-center justify-center">
                <Brain className="h-12 w-12 animate-pulse text-primary" />
            </div>
        );
    }

    if (sessionDone) {
        return (
            <div className="flex h-[calc(100vh-8rem)] flex-col items-center justify-center space-y-6">
                <div className="rounded-full bg-green-100 p-6">
                    <CheckCircle className="h-12 w-12 text-green-600" />
                </div>
                <div className="text-center space-y-2">
                    <h2 className="text-2xl font-bold">本轮复习完成</h2>
                    <p className="text-muted-foreground">
                        {reviewed > 0
                            ? `已复习 ${reviewed} 张卡片。`
                            : "当前没有到期闪卡，稍后再来。"}
                    </p>
                </div>
                <div className="flex gap-3">
                    <Button variant="outline" onClick={() => navigate("/knowledge")}>
                        <ArrowLeft className="mr-2 h-4 w-4" />
                        知识库
                    </Button>
                    <Button
                        onClick={() => {
                            setSessionDone(false);
                            setCurrentIndex(0);
                            setReviewed(0);
                            setLoading(true);
                            fetchDueCards();
                        }}
                    >
                        <RotateCcw className="mr-2 h-4 w-4" />
                        新一轮
                    </Button>
                </div>
            </div>
        );
    }

    const currentCard = cards[currentIndex];
    if (!currentCard) return null;

    return (
        <div className="mx-auto max-w-2xl space-y-6 animate-in fade-in duration-500">
            {/* Header */}
            <div className="flex items-center justify-between">
                <Button variant="ghost" size="sm" onClick={() => navigate("/knowledge")}>
                    <ArrowLeft className="mr-2 h-4 w-4" />
                    知识库
                </Button>
                <div className="flex items-center gap-3 text-sm text-muted-foreground">
                    <GraduationCap className="h-4 w-4" />
                    <span>
                        {currentIndex + 1} / {cards.length}
                    </span>
                    <span className="text-green-600">（已复习 {reviewed}）</span>
                </div>
            </div>

            {/* Progress bar */}
            <div className="h-1.5 rounded-full bg-gray-100">
                <div
                    className="h-full rounded-full bg-primary transition-all"
                    style={{ width: `${((currentIndex + 1) / cards.length) * 100}%` }}
                />
            </div>

            {/* Flashcard */}
            <div className="perspective-1000">
                <Card
                    className={cn(
                        "min-h-[300px] cursor-pointer transition-all duration-300",
                        flipped ? "bg-gradient-to-br from-green-50 to-emerald-50 border-green-200" : "bg-white"
                    )}
                    onClick={() => setFlipped(!flipped)}
                >
                    <CardContent className="flex min-h-[300px] flex-col items-center justify-center p-8 text-center">
                        {!flipped ? (
                            <>
                                <div className="mb-4 rounded-full bg-primary/10 p-3">
                                    <Brain className="h-6 w-6 text-primary" />
                                </div>
                                <p className="text-lg font-medium leading-relaxed">{currentCard.front}</p>
                                <p className="mt-6 text-xs text-muted-foreground">点击查看答案</p>
                            </>
                        ) : (
                            <>
                                <div className="mb-4 rounded-full bg-green-100 p-3">
                                    <CheckCircle className="h-6 w-6 text-green-600" />
                                </div>
                                <p className="text-lg leading-relaxed">{currentCard.back}</p>
                            </>
                        )}
                    </CardContent>
                </Card>
            </div>

            {/* Tags */}
            {currentCard.tags.length > 0 && (
                <div className="flex justify-center gap-1.5">
                    {currentCard.tags.map((tag) => (
                        <span key={tag} className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600">
                            {tag}
                        </span>
                    ))}
                </div>
            )}

            {/* Quality Rating */}
            {flipped && (
                <div className="space-y-3 animate-in slide-in-from-bottom-4 duration-300">
                    <p className="text-center text-sm text-muted-foreground">这张卡记得怎么样？</p>
                    <div className="flex justify-center gap-2">
                        {QUALITY_OPTIONS.map((opt) => (
                            <Button
                                key={opt.value}
                                className={cn("flex-1 max-w-[120px] text-white", opt.color)}
                                onClick={() => handleReview(opt.value)}
                            >
                                <div className="text-center">
                                    <div className="text-sm font-medium">{opt.label}</div>
                                </div>
                            </Button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};

export default FlashcardReview;
