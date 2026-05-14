import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Download, Loader2, FileText, Sparkles, Palette, Brain, Highlighter, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import api from "@/lib/api";

interface HighlightStats {
    core_conclusions: number;
    method_innovations: number;
    key_data: number;
    total: number;
    failed_matches: number;
}

interface HighlightSentence {
    sentence_id: string;
    page_index: number;
    text: string;
    category: "core_conclusion" | "method_innovation" | "key_data";
    rects: number[][];
}

const HIGHLIGHT_LABELS: Record<HighlightSentence["category"], string> = {
    core_conclusion: "核心结论",
    method_innovation: "方法创新",
    key_data: "关键数据",
};

const HIGHLIGHT_DOT: Record<HighlightSentence["category"], string> = {
    core_conclusion: "bg-yellow-300",
    method_innovation: "bg-blue-300",
    key_data: "bg-green-300",
};

const Reader = () => {
    const { taskId } = useParams<{ taskId: string }>();
    const navigate = useNavigate();
    const [status, setStatus] = useState<string>("loading");
    const [originalPdfUrl, setOriginalPdfUrl] = useState<string | null>(null);
    const [resultPdfUrl, setResultPdfUrl] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [focusMode, setFocusMode] = useState(() => window.innerWidth < 768);
    const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);
    const [highlightStats, setHighlightStats] = useState<HighlightStats | null>(null);
    const [highlightStatus, setHighlightStatus] = useState<string | null>(null);
    const [highlightSentences, setHighlightSentences] = useState<HighlightSentence[]>([]);
    const [highlightFilter, setHighlightFilter] = useState<HighlightSentence["category"] | "all">("all");
    const [selectedPage, setSelectedPage] = useState(1);
    const [hasDualPdf, setHasDualPdf] = useState(false);
    const [knowledgeLoading, setKnowledgeLoading] = useState(false);
    const [extractingPaperId, setExtractingPaperId] = useState<string | null>(null);
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Track mobile breakpoint and auto-enable focus mode
    useEffect(() => {
        const onResize = () => {
            const mobile = window.innerWidth < 768;
            setIsMobile(mobile);
            if (mobile) setFocusMode(true);
        };
        window.addEventListener("resize", onResize);
        return () => window.removeEventListener("resize", onResize);
    }, []);

    useEffect(() => {
        let cancelled = false;

        const fetchStatus = async () => {
            try {
                const response = await api.get(`/api/status/${taskId}`);
                if (cancelled) return;
                setStatus(response.data.status);

                if (response.data.status === "completed") {
                    if (response.data.highlight_stats) {
                        setHighlightStats(response.data.highlight_stats);
                    }
                    setHighlightStatus(response.data.highlight_status || null);
                    setHighlightSentences(response.data.highlight_sentences || []);
                    setHasDualPdf(Boolean(response.data.has_dual_pdf));
                    const [originalResponse, resultResponse] = await Promise.all([
                        api.get(`/api/original/${taskId}/pdf`, { responseType: "blob" }),
                        api.get(`/api/result/${taskId}/pdf`, { responseType: "blob" }),
                    ]);
                    if (cancelled) return;

                    setOriginalPdfUrl(URL.createObjectURL(new Blob([originalResponse.data], { type: "application/pdf" })));
                    setResultPdfUrl(URL.createObjectURL(new Blob([resultResponse.data], { type: "application/pdf" })));
                    setLoading(false);
                } else if (response.data.status === "failed" || response.data.status === "error") {
                    setLoading(false);
                } else {
                    timeoutRef.current = setTimeout(fetchStatus, 2000);
                }
            } catch {
                if (cancelled) return;
                setLoading(false);
                setStatus("error");
            }
        };

        fetchStatus();

        return () => {
            cancelled = true;
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
        };
    }, [taskId]);

    // Cleanup blob URLs on unmount
    useEffect(() => {
        return () => {
            if (originalPdfUrl) URL.revokeObjectURL(originalPdfUrl);
            if (resultPdfUrl) URL.revokeObjectURL(resultPdfUrl);
        };
    }, [originalPdfUrl, resultPdfUrl]);

    useEffect(() => {
        if (!extractingPaperId) return;

        let cancelled = false;
        const interval = window.setInterval(async () => {
            try {
                const response = await api.get(`/api/knowledge/extract/status/${extractingPaperId}`);
                if (cancelled) return;
                if (response.data.status === "completed") {
                    window.clearInterval(interval);
                    toast.success("知识提取完成。");
                    navigate(`/knowledge/paper/${extractingPaperId}`);
                } else if (response.data.status === "error") {
                    window.clearInterval(interval);
                    toast.error(response.data.error || "知识提取失败。");
                    setExtractingPaperId(null);
                }
            } catch {
                if (!cancelled) {
                    window.clearInterval(interval);
                    toast.error("无法查询知识提取状态。");
                    setExtractingPaperId(null);
                }
            }
        }, 3000);

        return () => {
            cancelled = true;
            window.clearInterval(interval);
        };
    }, [extractingPaperId, navigate]);

    const downloadBlob = (url: string, filename: string) => {
        const link = document.createElement("a");
        link.href = url;
        link.setAttribute("download", filename);
        document.body.appendChild(link);
        link.click();
        link.parentNode?.removeChild(link);
    };

    const handleDownload = async (format: "mono" | "dual" = "mono") => {
        if (format === "mono" && resultPdfUrl) {
            downloadBlob(resultPdfUrl, `translated_${taskId}.pdf`);
            return;
        }
        try {
            const response = await api.get(`/api/result/${taskId}/pdf?format=${format}`, { responseType: "blob" });
            const url = URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
            downloadBlob(url, format === "dual" ? `dual_${taskId}.pdf` : `translated_${taskId}.pdf`);
            URL.revokeObjectURL(url);
        } catch {
            toast.error("下载失败。");
        }
    };

    const handleKnowledgeExtraction = async () => {
        if (!taskId || knowledgeLoading) return;
        setKnowledgeLoading(true);
        try {
            const response = await api.post(`/api/knowledge/extract/${taskId}`);
            if (response.data.status === "already_completed") {
                navigate(`/knowledge/paper/${response.data.paper_id}`);
                return;
            }
            setExtractingPaperId(response.data.paper_id);
            toast.success("知识提取已开始。");
        } catch {
            toast.error("知识提取启动失败。");
        } finally {
            setKnowledgeLoading(false);
        }
    };

    const filteredHighlights = highlightSentences.filter((sentence) =>
        highlightFilter === "all" ? true : sentence.category === highlightFilter
    );

    if (loading || status === "processing" || status === "pending" || status === "parsing" || status === "rewriting" || status === "rendering" || status === "highlighting") {
        return (
            <div className="flex h-[calc(100vh-4rem)] flex-col items-center justify-center space-y-4">
                <Loader2 className="h-12 w-12 animate-spin text-primary" />
                <p className="text-lg font-medium text-muted-foreground">
                    {["processing", "parsing", "rewriting", "rendering", "highlighting"].includes(status)
                        ? "正在处理文档..."
                        : "正在加载..."}
                </p>
            </div>
        );
    }

    if (status === "failed" || status === "error") {
        return (
            <div className="flex h-[calc(100vh-4rem)] flex-col items-center justify-center space-y-4">
                <div className="rounded-full bg-red-100 p-4 text-red-600">
                    <FileText className="h-8 w-8" />
                </div>
                <h2 className="text-xl font-semibold">处理失败</h2>
                <p className="text-muted-foreground">处理文档时出现错误。</p>
                <Button onClick={() => navigate("/dashboard")}>返回首页</Button>
            </div>
        );
    }

    return (
        <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
            {/* Toolbar */}
            <div className="flex items-center justify-between rounded-xl border bg-white p-3 shadow-sm">
                <div className="flex items-center gap-2">
                    <Button variant="ghost" size="sm" onClick={() => navigate("/dashboard")}>
                        <ArrowLeft className="mr-2 h-4 w-4" />
                        返回
                    </Button>
                    <div className="h-4 w-px bg-gray-200 mx-2 hidden sm:block" />
                    <h1 className="text-sm font-medium text-gray-900 hidden sm:block">论文阅读器</h1>
                </div>
                <div className="flex items-center gap-2">
                    {highlightStats && highlightStats.total > 0 && (
                        <>
                            <div className="hidden md:flex items-center gap-3 px-3 py-1.5 rounded-lg bg-gray-50 border text-xs">
                                <div className="flex items-center gap-1.5">
                                    <span className="inline-block h-3 w-3 rounded-sm" style={{ backgroundColor: "rgb(255, 242, 153)" }} />
                                    <span className="text-gray-600">结论 ({highlightStats.core_conclusions})</span>
                                </div>
                                <div className="flex items-center gap-1.5">
                                    <span className="inline-block h-3 w-3 rounded-sm" style={{ backgroundColor: "rgb(179, 217, 255)" }} />
                                    <span className="text-gray-600">方法 ({highlightStats.method_innovations})</span>
                                </div>
                                <div className="flex items-center gap-1.5">
                                    <span className="inline-block h-3 w-3 rounded-sm" style={{ backgroundColor: "rgb(179, 255, 179)" }} />
                                    <span className="text-gray-600">数据 ({highlightStats.key_data})</span>
                                </div>
                            </div>
                            <Button
                                variant="ghost"
                                size="sm"
                                className="md:hidden"
                                title={`高亮：${highlightStats.core_conclusions} 条结论，${highlightStats.method_innovations} 条方法，${highlightStats.key_data} 条数据`}
                            >
                                <Palette className="h-4 w-4 text-amber-500" />
                            </Button>
                        </>
                    )}
                    {highlightStatus === "partial" && (
                        <Button variant="ghost" size="sm" title={`有 ${highlightStats?.failed_matches || 0} 条高亮未定位`}>
                            <AlertTriangle className="h-4 w-4 text-amber-500" />
                        </Button>
                    )}
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setFocusMode(!focusMode)}
                        className={cn("gap-2", focusMode && "bg-primary/10 text-primary border-primary/20")}
                    >
                        <Sparkles className="h-4 w-4" />
                        <span className="hidden sm:inline">{focusMode ? "显示原文" : "专注模式"}</span>
                    </Button>
                    <Button
                        variant="outline"
                        size="sm"
                        className="gap-2 text-violet-600 border-violet-200 hover:bg-violet-50"
                        onClick={handleKnowledgeExtraction}
                        disabled={knowledgeLoading || Boolean(extractingPaperId)}
                    >
                        {knowledgeLoading || extractingPaperId ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <Brain className="h-4 w-4" />
                        )}
                        <span className="hidden sm:inline">{extractingPaperId ? "提取中" : "提取知识"}</span>
                    </Button>
                    {hasDualPdf && (
                        <Button variant="outline" size="sm" onClick={() => handleDownload("dual")} className="gap-2">
                            <Download className="h-4 w-4" />
                            <span className="hidden sm:inline">中英对照版</span>
                        </Button>
                    )}
                    <Button size="sm" onClick={() => handleDownload("mono")} className="gap-2">
                        <Download className="h-4 w-4" />
                        <span className="hidden sm:inline">下载 PDF</span>
                    </Button>
                </div>
            </div>

            {/* Split Pane */}
            <ResizablePanelGroup
                direction={isMobile ? "vertical" : "horizontal"}
                className="min-h-0 flex-1 rounded-xl border bg-white shadow-sm overflow-hidden"
                style={{ direction: "ltr" }}
            >
                {/* Left Panel: AI Result PDF */}
                <ResizablePanel defaultSize={focusMode ? 78 : 46} minSize={30}>
                    <div className="flex h-full flex-col bg-white">
                        <div className="flex items-center justify-between border-b bg-white px-4 py-2">
                            <div className="flex items-center gap-2">
                                <Sparkles className="h-3 w-3 text-primary" />
                                <span className="text-xs font-medium text-primary uppercase tracking-wider">处理结果 PDF</span>
                            </div>
                        </div>
                        <div className="flex-1 bg-gray-100/50">
                            {resultPdfUrl && (
                                <iframe
                                    src={`${resultPdfUrl}#page=${selectedPage}`}
                                    className="h-full w-full border-none"
                                    title="处理结果 PDF"
                                />
                            )}
                        </div>
                    </div>
                </ResizablePanel>

                {/* Right Panel: Original PDF - Hidden in Focus Mode */}
                {!focusMode && (
                    <>
                        <ResizableHandle withHandle />
                        <ResizablePanel defaultSize={32} minSize={24}>
                            <div className="flex h-full flex-col">
                                <div className="flex items-center justify-between border-b bg-gray-50/50 px-4 py-2">
                                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">原始 PDF</span>
                                </div>
                                <div className="flex-1 bg-gray-100/50">
                                    {originalPdfUrl && (
                                        <iframe
                                            src={originalPdfUrl}
                                            className="h-full w-full border-none"
                                            title="原始 PDF"
                                        />
                                    )}
                                </div>
                            </div>
                        </ResizablePanel>
                    </>
                )}
                {highlightSentences.length > 0 && (
                    <>
                        <ResizableHandle withHandle />
                        <ResizablePanel defaultSize={22} minSize={18}>
                            <div className="flex h-full flex-col bg-white">
                                <div className="border-b px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        <Highlighter className="h-4 w-4 text-amber-500" />
                                        <span className="text-sm font-medium">高亮句子</span>
                                        <span className="ml-auto text-xs text-muted-foreground">{filteredHighlights.length}</span>
                                    </div>
                                    <div className="mt-3 flex flex-wrap gap-1.5">
                                        {(["all", "core_conclusion", "method_innovation", "key_data"] as const).map((value) => (
                                            <button
                                                key={value}
                                                onClick={() => setHighlightFilter(value)}
                                                className={cn(
                                                    "rounded-md border px-2 py-1 text-xs",
                                                    highlightFilter === value
                                                        ? "border-primary bg-primary text-primary-foreground"
                                                        : "border-gray-200 text-gray-600 hover:bg-gray-50"
                                                )}
                                            >
                                                {value === "all" ? "全部" : HIGHLIGHT_LABELS[value]}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                                <div className="min-h-0 flex-1 overflow-y-auto">
                                    {filteredHighlights.map((sentence) => (
                                        <button
                                            key={sentence.sentence_id}
                                            className="block w-full border-b px-4 py-3 text-left hover:bg-gray-50"
                                            onClick={() => setSelectedPage(sentence.page_index + 1)}
                                        >
                                            <div className="mb-1.5 flex items-center gap-2 text-xs text-muted-foreground">
                                                <span className={cn("h-2.5 w-2.5 rounded-sm", HIGHLIGHT_DOT[sentence.category])} />
                                                <span>{HIGHLIGHT_LABELS[sentence.category]}</span>
                                                <span className="ml-auto">第 {sentence.page_index + 1} 页</span>
                                            </div>
                                            <p className="line-clamp-4 text-xs leading-relaxed text-gray-700">{sentence.text}</p>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </ResizablePanel>
                    </>
                )}
            </ResizablePanelGroup>
        </div>
    );
};

export default Reader;
