import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
    Brain,
    Search,
    Download,
    Trash2,
    BookOpen,
    Network,
    FileJson,
    FileText as FileTextIcon,
    GraduationCap,
    Loader2,
    CheckCircle,
    AlertCircle,
    Clock,
} from "lucide-react";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import api from "@/lib/api";

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

const KnowledgeBase = () => {
    const [papers, setPapers] = useState<Paper[]>([]);
    const [search, setSearch] = useState("");
    const [dueCount, setDueCount] = useState(0);
    const navigate = useNavigate();

    const fetchPapers = useCallback(async () => {
        try {
            const response = await api.get("/api/knowledge/papers");
            setPapers(response.data);
        } catch {
            // silently fail
        }
    }, []);

    const fetchDueCount = useCallback(async () => {
        try {
            const response = await api.get("/api/knowledge/flashcards/due?limit=100");
            setDueCount(response.data.length);
        } catch {
            // silently fail
        }
    }, []);

    useEffect(() => {
        const load = async () => {
            await Promise.all([fetchPapers(), fetchDueCount()]);
        };
        void load();
    }, [fetchPapers, fetchDueCount]);

    const handleDelete = async (paperId: string) => {
        try {
            await api.delete(`/api/knowledge/papers/${paperId}`);
            setPapers((prev) => prev.filter((p) => p.id !== paperId));
            toast.success("论文已从知识库删除。");
        } catch {
            toast.error("删除论文失败。");
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

    const getStatusIcon = (status: string) => {
        switch (status) {
            case "completed":
                return <CheckCircle className="h-4 w-4 text-green-600" />;
            case "extracting":
                return <Loader2 className="h-4 w-4 text-blue-600 animate-spin" />;
            case "error":
                return <AlertCircle className="h-4 w-4 text-red-600" />;
            default:
                return <Clock className="h-4 w-4 text-gray-400" />;
        }
    };

    const filteredPapers = search
        ? papers.filter((p) => p.title.toLowerCase().includes(search.toLowerCase()))
        : papers;

    return (
        <div className="space-y-8 animate-in fade-in duration-500">
            {/* Header */}
            <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-violet-500/5 via-purple-500/10 to-transparent p-8 md:p-12 border border-purple-500/10 shadow-sm">
                <div className="relative z-10 mx-auto max-w-2xl text-center space-y-4">
                    <h1 className="text-4xl font-bold tracking-tight text-gray-900 sm:text-5xl">
                        知识库
                    </h1>
                    <p className="text-lg text-gray-600">
                        管理已提取的论文知识、图谱和闪卡。
                    </p>
                    <div className="flex flex-wrap justify-center gap-3 pt-2">
                        <Button
                            variant="outline"
                            className="gap-2"
                            onClick={() => navigate("/knowledge/review")}
                        >
                            <GraduationCap className="h-4 w-4" />
                            复习闪卡
                            {dueCount > 0 && (
                                <span className="ml-1 inline-flex items-center justify-center rounded-full bg-red-500 px-2 py-0.5 text-xs font-medium text-white">
                                    {dueCount}
                                </span>
                            )}
                        </Button>
                        <Button
                            variant="outline"
                            className="gap-2"
                            onClick={() => navigate("/knowledge/graph")}
                        >
                            <Network className="h-4 w-4" />
                            知识图谱
                        </Button>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button variant="outline" className="gap-2">
                                    <Download className="h-4 w-4" />
                                    导出
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent>
                                <DropdownMenuItem onClick={() => handleExport("json")}>
                                    <FileJson className="mr-2 h-4 w-4" />
                                    EasyPaper JSON
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleExport("obsidian")}>
                                    <BookOpen className="mr-2 h-4 w-4" />
                                    Obsidian 笔记库 (ZIP)
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleExport("bibtex")}>
                                    <FileTextIcon className="mr-2 h-4 w-4" />
                                    BibTeX (.bib)
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleExport("csl")}>
                                    <FileJson className="mr-2 h-4 w-4" />
                                    CSL-JSON (Zotero)
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleExport("csv")}>
                                    <FileTextIcon className="mr-2 h-4 w-4" />
                                    CSV (ZIP)
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                </div>
                <div className="absolute top-0 left-0 -translate-x-1/2 -translate-y-1/2 h-64 w-64 rounded-full bg-violet-200/30 blur-3xl" />
                <div className="absolute bottom-0 right-0 translate-x-1/2 translate-y-1/2 h-64 w-64 rounded-full bg-purple-200/30 blur-3xl" />
            </section>

            {/* Paper List */}
            <section className="space-y-4">
                <div className="flex items-center justify-between gap-4 px-2">
                    <h2 className="text-2xl font-semibold tracking-tight shrink-0">论文</h2>
                    {papers.length > 0 && (
                        <div className="relative max-w-xs w-full">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                            <Input
                                placeholder="搜索论文..."
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                className="pl-9 h-9"
                            />
                        </div>
                    )}
                </div>

                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {filteredPapers.map((paper) => (
                        <Card
                            key={paper.id}
                            className={cn(
                                "group relative overflow-hidden transition-all hover:shadow-md border-gray-200/60",
                                paper.extraction_status === "completed" && "cursor-pointer"
                            )}
                            onClick={() => {
                                if (paper.extraction_status === "completed") {
                                    navigate(`/knowledge/paper/${paper.id}`);
                                }
                            }}
                        >
                            <CardHeader className="pb-3">
                                <div className="flex items-start justify-between">
                                    <div className="flex items-center gap-3">
                                        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-violet-100 text-violet-600">
                                            <Brain className="h-5 w-5" />
                                        </div>
                                        <div className="space-y-1 min-w-0 flex-1">
                                            <CardTitle className="text-base font-medium leading-tight line-clamp-2">
                                                {paper.title || "未命名论文"}
                                            </CardTitle>
                                            <CardDescription className="text-xs flex items-center gap-1.5">
                                                {paper.year && <span>{paper.year}</span>}
                                                {paper.venue && <span>- {paper.venue}</span>}
                                            </CardDescription>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-1.5 shrink-0">
                                        {getStatusIcon(paper.extraction_status)}
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-red-600"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleDelete(paper.id);
                                            }}
                                        >
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </Button>
                                    </div>
                                </div>
                            </CardHeader>
                            <CardContent>
                                {paper.doi && (
                                    <p className="text-xs text-muted-foreground truncate">
                                        DOI: {paper.doi}
                                    </p>
                                )}
                            </CardContent>
                        </Card>
                    ))}

                    {filteredPapers.length === 0 && (
                        <div className="col-span-full py-12 text-center text-muted-foreground bg-gray-50/50 rounded-xl border border-dashed">
                            <Brain className="h-12 w-12 mx-auto mb-3 text-gray-300" />
                            <p>
                                {search
                                    ? "没有匹配的论文。"
                                    : "知识库还没有论文。先从已处理文档中提取知识。"}
                            </p>
                        </div>
                    )}
                </div>
            </section>
        </div>
    );
};

export default KnowledgeBase;
