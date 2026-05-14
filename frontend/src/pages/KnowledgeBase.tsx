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
    Settings,
    Save,
    FolderOpen,
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

interface ObsidianVault {
    name: string;
    path: string;
    exists: boolean;
    writable: boolean;
    open: boolean;
}

const KnowledgeBase = () => {
    const [papers, setPapers] = useState<Paper[]>([]);
    const [search, setSearch] = useState("");
    const [dueCount, setDueCount] = useState(0);
    const [obsidianOpen, setObsidianOpen] = useState(false);
    const [obsidianVaults, setObsidianVaults] = useState<ObsidianVault[]>([]);
    const [obsidianPath, setObsidianPath] = useState("");
    const [obsidianRootFolder, setObsidianRootFolder] = useState("EasyPaper");
    const [obsidianLoading, setObsidianLoading] = useState(false);
    const [obsidianSaving, setObsidianSaving] = useState(false);
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

    const fetchObsidianSettings = useCallback(async () => {
        try {
            const [settingsResponse, vaultsResponse] = await Promise.all([
                api.get("/api/knowledge/settings/obsidian"),
                api.get("/api/knowledge/settings/obsidian/vaults"),
            ]);
            const vaults = vaultsResponse.data.vaults || [];
            setObsidianVaults(vaults);
            setObsidianPath(
                settingsResponse.data.vault_path ||
                    vaults.find((vault: ObsidianVault) => vault.exists && vault.writable)?.path ||
                    "",
            );
            setObsidianRootFolder(settingsResponse.data.root_folder || "EasyPaper");
        } catch {
            setObsidianVaults([]);
        }
    }, []);

    useEffect(() => {
        const load = async () => {
            await Promise.all([fetchPapers(), fetchDueCount(), fetchObsidianSettings()]);
        };
        void load();
    }, [fetchPapers, fetchDueCount, fetchObsidianSettings]);

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

    const handleRefreshObsidianVaults = async () => {
        setObsidianLoading(true);
        try {
            await fetchObsidianSettings();
        } finally {
            setObsidianLoading(false);
        }
    };

    const handleTestObsidian = async () => {
        if (!obsidianPath.trim()) {
            toast.error("请先选择或填写 Obsidian vault 路径。");
            return;
        }
        setObsidianLoading(true);
        try {
            await api.post("/api/knowledge/settings/obsidian/test", {
                vault_path: obsidianPath,
                root_folder: obsidianRootFolder,
            });
            toast.success("Obsidian 目录可写。");
        } catch (error) {
            toast.error(getApiErrorMessage(error, "Obsidian 写入测试失败。"));
        } finally {
            setObsidianLoading(false);
        }
    };

    const handleSaveObsidian = async () => {
        if (!obsidianPath.trim()) {
            toast.error("请先选择或填写 Obsidian vault 路径。");
            return;
        }
        setObsidianSaving(true);
        try {
            const response = await api.post("/api/knowledge/settings/obsidian", {
                vault_path: obsidianPath,
                root_folder: obsidianRootFolder,
            });
            setObsidianPath(response.data.vault_path);
            setObsidianRootFolder(response.data.root_folder || "EasyPaper");
            toast.success("Obsidian 设置已保存。");
        } catch (error) {
            toast.error(getApiErrorMessage(error, "保存 Obsidian 设置失败。"));
        } finally {
            setObsidianSaving(false);
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
                        <Button
                            variant="outline"
                            className="gap-2"
                            onClick={() => setObsidianOpen((open) => !open)}
                        >
                            <Settings className="h-4 w-4" />
                            Obsidian 设置
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

            {obsidianOpen && (
                <section className="space-y-4 rounded-2xl border bg-white p-5 shadow-sm">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                            <h2 className="text-lg font-semibold">Obsidian 本地同步</h2>
                            <p className="text-sm text-muted-foreground">
                                保存后，可在论文详情页把主笔记和实体笔记写入本机 vault。
                            </p>
                        </div>
                        <Button
                            variant="outline"
                            size="sm"
                            className="gap-2"
                            onClick={handleRefreshObsidianVaults}
                            disabled={obsidianLoading}
                        >
                            {obsidianLoading ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                                <FolderOpen className="h-4 w-4" />
                            )}
                            重新检测
                        </Button>
                    </div>

                    {obsidianVaults.length > 0 && (
                        <div className="grid gap-2 md:grid-cols-2">
                            {obsidianVaults.map((vault) => (
                                <button
                                    type="button"
                                    key={vault.path}
                                    className={cn(
                                        "rounded-lg border p-3 text-left transition-colors",
                                        obsidianPath === vault.path
                                            ? "border-primary bg-primary/5"
                                            : "border-gray-200 hover:border-gray-300",
                                        (!vault.exists || !vault.writable) && "opacity-60",
                                    )}
                                    onClick={() => setObsidianPath(vault.path)}
                                >
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="font-medium">{vault.name}</span>
                                        <span
                                            className={cn(
                                                "rounded-full px-2 py-0.5 text-xs",
                                                vault.exists && vault.writable
                                                    ? "bg-green-100 text-green-700"
                                                    : "bg-red-100 text-red-700",
                                            )}
                                        >
                                            {vault.exists && vault.writable ? "可写" : "不可写"}
                                        </span>
                                    </div>
                                    <p className="mt-1 break-all text-xs text-muted-foreground">
                                        {vault.path}
                                    </p>
                                </button>
                            ))}
                        </div>
                    )}

                    <div className="grid gap-3 md:grid-cols-[1fr_220px]">
                        <div className="space-y-1.5">
                            <label className="text-sm font-medium" htmlFor="obsidian-path">
                                Vault 路径
                            </label>
                            <Input
                                id="obsidian-path"
                                value={obsidianPath}
                                onChange={(event) => setObsidianPath(event.target.value)}
                                placeholder="/Users/you/Documents/ObsidianVault"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <label className="text-sm font-medium" htmlFor="obsidian-root">
                                同步目录
                            </label>
                            <Input
                                id="obsidian-root"
                                value={obsidianRootFolder}
                                onChange={(event) => setObsidianRootFolder(event.target.value)}
                                placeholder="EasyPaper"
                            />
                        </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                        <Button
                            variant="outline"
                            className="gap-2"
                            onClick={handleTestObsidian}
                            disabled={obsidianLoading}
                        >
                            {obsidianLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                            测试写入
                        </Button>
                        <Button
                            className="gap-2"
                            onClick={handleSaveObsidian}
                            disabled={obsidianSaving}
                        >
                            {obsidianSaving ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                                <Save className="h-4 w-4" />
                            )}
                            保存设置
                        </Button>
                    </div>
                </section>
            )}

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
