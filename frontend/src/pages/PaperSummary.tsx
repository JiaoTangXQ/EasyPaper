import { useState, useEffect } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
    ArrowLeft,
    Clock,
    Target,
    Layers,
    TrendingUp,
    Sparkles,
    ChevronRight,
    Check,
    AlertTriangle,
    Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface SummaryData {
    one_liner: string;
    novelty_score: number;
    estimated_minutes: number;
    story: {
        problem: string;
        method: string;
        results: string;
        impact: string;
    };
    key_numbers: { value: string; label: string; context?: string }[];
    pipeline: { input: string; steps: string[]; output: string };
    contributions: string[];
    limitations: string[];
    keywords: { text: string; type: string; importance: number }[];
}

/* ------------------------------------------------------------------ */
/*  Story flow config                                                  */
/* ------------------------------------------------------------------ */

const STORY_SECTIONS = [
    {
        key: "problem" as const,
        label: "问题",
        Icon: Target,
        bar: "bg-rose-400",
        iconCls: "text-rose-500",
        labelCls: "text-rose-600",
        bg: "bg-rose-50/60",
    },
    {
        key: "method" as const,
        label: "方法",
        Icon: Layers,
        bar: "bg-blue-400",
        iconCls: "text-blue-500",
        labelCls: "text-blue-600",
        bg: "bg-blue-50/60",
    },
    {
        key: "results" as const,
        label: "结果",
        Icon: TrendingUp,
        bar: "bg-emerald-400",
        iconCls: "text-emerald-500",
        labelCls: "text-emerald-600",
        bg: "bg-emerald-50/60",
    },
    {
        key: "impact" as const,
        label: "影响",
        Icon: Sparkles,
        bar: "bg-amber-400",
        iconCls: "text-amber-500",
        labelCls: "text-amber-600",
        bg: "bg-amber-50/60",
    },
];

const KEYWORD_COLORS: Record<string, string> = {
    method: "bg-blue-50 text-blue-700 ring-blue-200/50",
    model: "bg-purple-50 text-purple-700 ring-purple-200/50",
    dataset: "bg-emerald-50 text-emerald-700 ring-emerald-200/50",
    metric: "bg-amber-50 text-amber-700 ring-amber-200/50",
    concept: "bg-gray-50 text-gray-600 ring-gray-200/50",
    task: "bg-rose-50 text-rose-700 ring-rose-200/50",
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

const PaperSummary = () => {
    const { taskId } = useParams<{ taskId: string }>();
    const navigate = useNavigate();
    const location = useLocation();
    const filename = (location.state as { filename?: string })?.filename || "Paper";

    const [data, setData] = useState<SummaryData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchSummary = async () => {
            try {
                const res = await api.post(`/api/summary/${taskId}`);
                setData(res.data);
            } catch (err: unknown) {
                const msg = getApiErrorMessage(err, "摘要生成失败。");
                setError(msg);
                toast.error(msg);
            } finally {
                setLoading(false);
            }
        };
        fetchSummary();
    }, [taskId]);

    /* Loading state */
    if (loading) {
        return (
            <div className="flex h-[calc(100vh-8rem)] flex-col items-center justify-center gap-4">
                <div className="relative">
                    <div className="h-16 w-16 rounded-2xl bg-primary/10 flex items-center justify-center">
                        <Loader2 className="h-8 w-8 animate-spin text-primary" />
                    </div>
                </div>
                <div className="text-center space-y-1">
                    <p className="text-sm font-medium text-gray-900">
                        正在生成摘要...
                    </p>
                    <p className="text-xs text-gray-500">
                        AI 正在阅读和分析论文
                    </p>
                </div>
            </div>
        );
    }

    /* Error state */
    if (error || !data) {
        return (
            <div className="flex h-[calc(100vh-8rem)] flex-col items-center justify-center gap-4">
                <p className="text-sm text-red-500">{error || "暂无数据"}</p>
                <Button variant="outline" onClick={() => navigate("/dashboard")}>
                    <ArrowLeft className="mr-2 h-4 w-4" /> 返回
                </Button>
            </div>
        );
    }

    return (
        <div className="mx-auto max-w-4xl space-y-12 pb-16 animate-in fade-in duration-700">
            {/* ── Back ── */}
            <Button
                variant="ghost"
                size="sm"
                className="text-gray-400 hover:text-gray-900 -ml-2"
                onClick={() => navigate("/dashboard")}
            >
                <ArrowLeft className="mr-1.5 h-4 w-4" />
                {filename}
            </Button>

            {/* ── Hero: One-liner ── */}
            <section className="space-y-5">
                <h1 className="text-3xl sm:text-4xl font-bold tracking-tight leading-tight text-gray-900">
                    {data.one_liner}
                </h1>
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-gray-400">
                    <span className="flex items-center gap-1.5">
                        <Clock className="h-3.5 w-3.5" />
                        {data.estimated_minutes} 分钟阅读
                    </span>
                    <span className="flex items-center gap-1.5">
                        <span className="text-xs font-medium text-gray-500">
                            新颖度
                        </span>
                        <span className="flex gap-0.5">
                            {[...Array(5)].map((_, i) => (
                                <span
                                    key={i}
                                    className={cn(
                                        "h-2 w-2 rounded-full transition-colors",
                                        i < data.novelty_score
                                            ? "bg-gray-900"
                                            : "bg-gray-200"
                                    )}
                                />
                            ))}
                        </span>
                    </span>
                </div>
            </section>

            {/* ── Story Flow ── */}
            <section>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3 md:gap-0">
                    {STORY_SECTIONS.map((sec, i) => (
                        <div key={sec.key} className="flex items-stretch">
                            {/* Card */}
                            <div
                                className={cn(
                                    "flex-1 rounded-2xl p-5 space-y-3",
                                    sec.bg
                                )}
                            >
                                <div
                                    className={cn(
                                        "h-0.5 w-8 rounded-full",
                                        sec.bar
                                    )}
                                />
                                <div className="flex items-center gap-2">
                                    <sec.Icon
                                        className={cn("h-4 w-4", sec.iconCls)}
                                    />
                                    <span
                                        className={cn(
                                            "text-xs font-semibold uppercase tracking-wider",
                                            sec.labelCls
                                        )}
                                    >
                                        {sec.label}
                                    </span>
                                </div>
                                <p className="text-sm leading-relaxed text-gray-700">
                                    {data.story[sec.key]}
                                </p>
                            </div>

                            {/* Arrow between cards (desktop only) */}
                            {i < STORY_SECTIONS.length - 1 && (
                                <div className="hidden md:flex items-center px-1 text-gray-300">
                                    <ChevronRight className="h-4 w-4" />
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </section>

            {/* ── Key Numbers + Pipeline ── */}
            <section className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                {/* Key Numbers */}
                {data.key_numbers.length > 0 && (
                    <div className="space-y-4">
                        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                            关键数据
                        </h2>
                        <div className="grid grid-cols-2 gap-3">
                            {data.key_numbers.map((num, i) => (
                                <div
                                    key={i}
                                    className="rounded-2xl bg-gray-50 p-5 space-y-1"
                                >
                                    <p className="text-2xl font-bold tracking-tight text-gray-900">
                                        {num.value}
                                    </p>
                                    <p className="text-xs font-medium text-gray-500">
                                        {num.label}
                                    </p>
                                    {num.context && (
                                        <p className="text-xs text-gray-400">
                                            {num.context}
                                        </p>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Pipeline */}
                {data.pipeline?.steps?.length > 0 && (
                    <div className="space-y-4">
                        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                            技术流程
                        </h2>
                        <div className="rounded-2xl bg-gray-50 p-6">
                            <div className="flex flex-wrap items-center gap-2">
                                {/* Input */}
                                <span className="rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm ring-1 ring-gray-200/60">
                                    {data.pipeline.input}
                                </span>

                                {data.pipeline.steps.map((step, i) => (
                                    <div
                                        key={i}
                                        className="flex items-center gap-2"
                                    >
                                        <ChevronRight className="h-3 w-3 text-gray-300 shrink-0" />
                                        <span className="rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm ring-1 ring-gray-200/60">
                                            {step}
                                        </span>
                                    </div>
                                ))}

                                {/* Output */}
                                <ChevronRight className="h-3 w-3 text-gray-300 shrink-0" />
                                <span className="rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm">
                                    {data.pipeline.output}
                                </span>
                            </div>
                        </div>
                    </div>
                )}
            </section>

            {/* ── Contributions & Limitations ── */}
            <section className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Contributions */}
                {data.contributions.length > 0 && (
                    <div className="space-y-4">
                        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                            主要贡献
                        </h2>
                        <ul className="space-y-3">
                            {data.contributions.map((item, i) => (
                                <li
                                    key={i}
                                    className="flex gap-3 text-sm leading-relaxed text-gray-700"
                                >
                                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100">
                                        <Check className="h-3 w-3 text-emerald-600" />
                                    </span>
                                    {item}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                {/* Limitations */}
                {data.limitations.length > 0 && (
                    <div className="space-y-4">
                        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                            局限性
                        </h2>
                        <ul className="space-y-3">
                            {data.limitations.map((item, i) => (
                                <li
                                    key={i}
                                    className="flex gap-3 text-sm leading-relaxed text-gray-700"
                                >
                                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100">
                                        <AlertTriangle className="h-3 w-3 text-amber-600" />
                                    </span>
                                    {item}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </section>

            {/* ── Keywords ── */}
            {data.keywords.length > 0 && (
                <section className="space-y-4">
                    <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                        关键概念
                    </h2>
                    <div className="flex flex-wrap gap-2">
                        {data.keywords
                            .sort((a, b) => b.importance - a.importance)
                            .map((kw, i) => (
                                <span
                                    key={i}
                                    className={cn(
                                        "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ring-1",
                                        KEYWORD_COLORS[kw.type] ||
                                            KEYWORD_COLORS.concept
                                    )}
                                >
                                    {kw.text}
                                </span>
                            ))}
                    </div>
                </section>
            )}
        </div>
    );
};

export default PaperSummary;
