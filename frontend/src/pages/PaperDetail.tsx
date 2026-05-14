import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
    ArrowLeft,
    Download,
    Brain,
    Lightbulb,
    Link2,
    FlaskConical,
    Database,
    GraduationCap,
    StickyNote,
    Plus,
    Loader2,
    BookOpenCheck,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";

interface PaperKnowledge {
    id: string;
    metadata: {
        title: string;
        authors: { name: string; affiliation?: string }[];
        year?: number;
        doi?: string;
        venue?: string;
        abstract?: string;
        keywords?: string[];
    };
    entities: { id: string; name: string; type: string; definition?: string; importance: number }[];
    relationships: {
        id: string;
        source_entity_id: string;
        target_entity_id: string;
        type: string;
        description?: string;
        source?: string;
        target?: string;
    }[];
    findings: { id: string; type: string; statement: string; evidence?: string }[];
    methods: { name: string; description: string }[];
    datasets: { name: string; description: string; usage?: string }[];
    flashcards: { id: string; front: string; back: string; tags: string[]; difficulty: number }[];
    annotations: { id: string; type: string; content: string; created_at?: string }[];
    structure?: { sections: { id: string; title: string; level: number; summary?: string }[] };
}

const TYPE_COLORS: Record<string, string> = {
    method: "bg-blue-100 text-blue-700",
    model: "bg-purple-100 text-purple-700",
    dataset: "bg-green-100 text-green-700",
    metric: "bg-amber-100 text-amber-700",
    concept: "bg-gray-100 text-gray-700",
    task: "bg-rose-100 text-rose-700",
    person: "bg-cyan-100 text-cyan-700",
    organization: "bg-orange-100 text-orange-700",
};

const PaperDetail = () => {
    const { paperId } = useParams<{ paperId: string }>();
    const navigate = useNavigate();
    const [paper, setPaper] = useState<PaperKnowledge | null>(null);
    const [loading, setLoading] = useState(true);
    const [newNote, setNewNote] = useState("");
    const [obsidianSyncing, setObsidianSyncing] = useState(false);

    useEffect(() => {
        const fetchPaper = async () => {
            try {
                const response = await api.get(`/api/knowledge/papers/${paperId}`);
                setPaper(response.data);
            } catch {
                toast.error("加载论文失败。");
            } finally {
                setLoading(false);
            }
        };
        fetchPaper();
    }, [paperId]);

    const handleExport = async () => {
        try {
            const response = await api.get(`/api/knowledge/export/paper/${paperId}`, {
                responseType: "blob",
            });
            const blob = new Blob([response.data], { type: "application/json" });
            const link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = `${paper?.metadata.title || "paper"}.epaper.json`;
            document.body.appendChild(link);
            link.click();
            link.parentNode?.removeChild(link);
            toast.success("已导出为 .epaper.json。");
        } catch {
            toast.error("导出失败。");
        }
    };

    const handleSyncObsidian = async () => {
        if (!paperId) return;
        setObsidianSyncing(true);
        try {
            const response = await api.post(`/api/knowledge/papers/${paperId}/sync/obsidian`);
            if (response.data.status === "partial") {
                toast.warning("部分笔记已同步到 Obsidian，部分文件写入失败。");
            } else {
                toast.success("已同步到 Obsidian。");
            }
        } catch (error) {
            toast.error(getApiErrorMessage(error, "同步到 Obsidian 失败。"));
        } finally {
            setObsidianSyncing(false);
        }
    };

    const handleAddNote = async () => {
        if (!newNote.trim()) return;
        try {
            await api.post(`/api/knowledge/papers/${paperId}/annotations`, { type: "note", content: newNote });
            setNewNote("");
            // Refresh paper data
            const response = await api.get(`/api/knowledge/papers/${paperId}`);
            setPaper(response.data);
            toast.success("笔记已添加。");
        } catch {
            toast.error("添加笔记失败。");
        }
    };

    if (loading) {
        return (
            <div className="flex h-[calc(100vh-8rem)] items-center justify-center">
                <Loader2 className="h-12 w-12 animate-spin text-primary" />
            </div>
        );
    }

    if (!paper) {
        return (
            <div className="flex h-[calc(100vh-8rem)] flex-col items-center justify-center space-y-4">
                <p className="text-muted-foreground">未找到论文。</p>
                <Button onClick={() => navigate("/knowledge")}>返回知识库</Button>
            </div>
        );
    }

    const { metadata, entities, relationships, findings, methods, datasets, flashcards, annotations } = paper;

    // Build entity name map for relationship display
    const entityMap: Record<string, string> = {};
    entities.forEach((e) => {
        entityMap[e.id] = e.name;
    });

    return (
        <div className="space-y-6 animate-in fade-in duration-500">
            {/* Header */}
            <div className="flex items-start justify-between gap-4">
                <div className="space-y-2">
                    <Button variant="ghost" size="sm" onClick={() => navigate("/knowledge")}>
                        <ArrowLeft className="mr-2 h-4 w-4" />
                        知识库
                    </Button>
                    <h1 className="text-2xl font-bold tracking-tight">{metadata.title}</h1>
                    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                        <span>{metadata.authors?.map((a) => a.name).join(", ")}</span>
                        {metadata.year && <span>({metadata.year})</span>}
                        {metadata.venue && <span>- {metadata.venue}</span>}
                    </div>
                    {metadata.keywords && metadata.keywords.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                            {metadata.keywords.map((kw) => (
                                <span key={kw} className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600">
                                    {kw}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
                <div className="flex shrink-0 flex-wrap justify-end gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={handleSyncObsidian}
                        disabled={obsidianSyncing}
                    >
                        {obsidianSyncing ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <BookOpenCheck className="h-4 w-4" />
                        )}
                        同步 Obsidian
                    </Button>
                    <Button variant="outline" size="sm" className="gap-2" onClick={handleExport}>
                        <Download className="h-4 w-4" />
                        .epaper.json
                    </Button>
                </div>
            </div>

            {/* Abstract */}
            {metadata.abstract && (
                <Card>
                    <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground uppercase tracking-wider">摘要</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <p className="text-sm leading-relaxed">{metadata.abstract}</p>
                    </CardContent>
                </Card>
            )}

            {/* Tabs */}
            <Tabs defaultValue="entities" className="space-y-4">
                <TabsList className="grid w-full grid-cols-5 lg:w-auto lg:inline-grid">
                    <TabsTrigger value="entities" className="gap-1.5">
                        <Brain className="h-3.5 w-3.5" />
                        <span className="hidden sm:inline">实体 ({entities.length})</span>
                        <span className="sm:hidden">{entities.length}</span>
                    </TabsTrigger>
                    <TabsTrigger value="findings" className="gap-1.5">
                        <Lightbulb className="h-3.5 w-3.5" />
                        <span className="hidden sm:inline">发现 ({findings.length})</span>
                        <span className="sm:hidden">{findings.length}</span>
                    </TabsTrigger>
                    <TabsTrigger value="flashcards" className="gap-1.5">
                        <GraduationCap className="h-3.5 w-3.5" />
                        <span className="hidden sm:inline">闪卡 ({flashcards.length})</span>
                        <span className="sm:hidden">{flashcards.length}</span>
                    </TabsTrigger>
                    <TabsTrigger value="relations" className="gap-1.5">
                        <Link2 className="h-3.5 w-3.5" />
                        <span className="hidden sm:inline">关系 ({relationships.length})</span>
                        <span className="sm:hidden">{relationships.length}</span>
                    </TabsTrigger>
                    <TabsTrigger value="notes" className="gap-1.5">
                        <StickyNote className="h-3.5 w-3.5" />
                        <span className="hidden sm:inline">笔记</span>
                    </TabsTrigger>
                </TabsList>

                {/* Entities Tab */}
                <TabsContent value="entities" className="space-y-3">
                    <div className="grid gap-3 md:grid-cols-2">
                        {entities.map((ent) => (
                            <Card key={ent.id} className="border-gray-200/60">
                                <CardContent className="p-4">
                                    <div className="flex items-start justify-between gap-2">
                                        <div className="space-y-1">
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium text-sm">{ent.name}</span>
                                                <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", TYPE_COLORS[ent.type] || "bg-gray-100 text-gray-600")}>
                                                    {ent.type}
                                                </span>
                                            </div>
                                            {ent.definition && (
                                                <p className="text-xs text-muted-foreground leading-relaxed">{ent.definition}</p>
                                            )}
                                        </div>
                                        <div className="text-xs text-muted-foreground shrink-0">
                                            {Math.round(ent.importance * 100)}%
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                </TabsContent>

                {/* Findings Tab */}
                <TabsContent value="findings" className="space-y-3">
                    {findings.map((f) => (
                        <Card key={f.id} className="border-gray-200/60">
                            <CardContent className="p-4">
                                <div className="flex items-start gap-3">
                                    <div className={cn(
                                        "shrink-0 mt-0.5 rounded-full px-2 py-0.5 text-[10px] font-medium",
                                        f.type === "result" ? "bg-green-100 text-green-700" :
                                        f.type === "limitation" ? "bg-amber-100 text-amber-700" :
                                        "bg-blue-100 text-blue-700"
                                    )}>
                                        {f.type}
                                    </div>
                                    <div className="space-y-1">
                                        <p className="text-sm">{f.statement}</p>
                                        {f.evidence && (
                                            <p className="text-xs text-muted-foreground">证据：{f.evidence}</p>
                                        )}
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    ))}
                    {methods.length > 0 && (
                        <div className="space-y-3 pt-4">
                            <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                                <FlaskConical className="h-4 w-4" /> 方法
                            </h3>
                            {methods.map((m, i) => (
                                <Card key={i} className="border-gray-200/60">
                                    <CardContent className="p-4">
                                        <p className="text-sm font-medium">{m.name}</p>
                                        <p className="text-xs text-muted-foreground mt-1">{m.description}</p>
                                    </CardContent>
                                </Card>
                            ))}
                        </div>
                    )}
                    {datasets.length > 0 && (
                        <div className="space-y-3 pt-4">
                            <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                                <Database className="h-4 w-4" /> 数据集
                            </h3>
                            {datasets.map((d, i) => (
                                <Card key={i} className="border-gray-200/60">
                                    <CardContent className="p-4">
                                        <p className="text-sm font-medium">{d.name}</p>
                                        <p className="text-xs text-muted-foreground mt-1">{d.description}</p>
                                        {d.usage && <p className="text-xs text-muted-foreground">用途：{d.usage}</p>}
                                    </CardContent>
                                </Card>
                            ))}
                        </div>
                    )}
                </TabsContent>

                {/* Flashcards Tab */}
                <TabsContent value="flashcards" className="space-y-3">
                    {flashcards.map((fc) => (
                        <Card key={fc.id} className="border-gray-200/60">
                            <CardContent className="p-4 space-y-2">
                                <p className="text-sm font-medium">问：{fc.front}</p>
                                <p className="text-sm text-muted-foreground">答：{fc.back}</p>
                                <div className="flex items-center gap-2">
                                    {fc.tags.map((tag) => (
                                        <span key={tag} className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600">
                                            {tag}
                                        </span>
                                    ))}
                                    <span className="text-[10px] text-muted-foreground ml-auto">
                                        难度：{fc.difficulty}/5
                                    </span>
                                </div>
                            </CardContent>
                        </Card>
                    ))}
                </TabsContent>

                {/* Relations Tab */}
                <TabsContent value="relations" className="space-y-3">
                    {relationships.map((rel) => (
                        <Card key={rel.id} className="border-gray-200/60">
                            <CardContent className="p-4">
                                <div className="flex items-center gap-2 text-sm">
                                    <span className="font-medium">
                                        {entityMap[rel.source_entity_id] || rel.source || "?"}
                                    </span>
                                    <span className="rounded-full bg-primary/10 text-primary px-2.5 py-0.5 text-xs font-medium">
                                        {rel.type}
                                    </span>
                                    <span className="font-medium">
                                        {entityMap[rel.target_entity_id] || rel.target || "?"}
                                    </span>
                                </div>
                                {rel.description && (
                                    <p className="text-xs text-muted-foreground mt-1">{rel.description}</p>
                                )}
                            </CardContent>
                        </Card>
                    ))}
                </TabsContent>

                {/* Notes Tab */}
                <TabsContent value="notes" className="space-y-3">
                    <div className="flex gap-2">
                        <Input
                            placeholder="添加笔记..."
                            value={newNote}
                            onChange={(e) => setNewNote(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
                        />
                        <Button size="sm" onClick={handleAddNote} className="gap-1 shrink-0">
                            <Plus className="h-4 w-4" />
                            添加
                        </Button>
                    </div>
                    {annotations?.map((ann) => (
                        <Card key={ann.id} className="border-gray-200/60">
                            <CardContent className="p-4">
                                <p className="text-sm">{ann.content}</p>
                                {ann.created_at && (
                                    <p className="text-xs text-muted-foreground mt-1">
                                        {new Date(ann.created_at).toLocaleString()}
                                    </p>
                                )}
                            </CardContent>
                        </Card>
                    ))}
                    {(!annotations || annotations.length === 0) && !newNote && (
                        <p className="text-sm text-muted-foreground text-center py-8">
                            暂无笔记。可在上方添加。
                        </p>
                    )}
                </TabsContent>
            </Tabs>
        </div>
    );
};

export default PaperDetail;
