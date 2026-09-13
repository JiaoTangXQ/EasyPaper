import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ArrowLeft, Download, FlaskConical, Database, Plus, Loader2, BookOpenCheck } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";

interface PaperKnowledge {
  id: string;
  task_id?: string | null;
  extraction_status?: string;
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
  findings: {
    id: string;
    type: string;
    statement: string;
    evidence?: string;
    evidence_refs?: { block_id: string; page: number }[];
  }[];
  methods: { name: string; description: string }[];
  datasets: { name: string; description: string; usage?: string }[];
  flashcards: { id: string; front: string; back: string; tags: string[]; difficulty: number }[];
  annotations: { id: string; type: string; content: string; created_at?: string }[];
  structure?: {
    sections: { id: string; title: string; level?: number; page?: number; block_id?: string; summary?: string }[];
  };
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
  const [addingNote, setAddingNote] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [obsidianSyncing, setObsidianSyncing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    setLoading(true);
    const fetchPaper = async () => {
      try {
        const { data } = await api.get(`/api/knowledge/papers/${paperId}`);
        if (cancelled) return;
        setPaper(data);
        setLoadError("");
        if (!data.metadata && !["error", "failed"].includes(data.extraction_status))
          timer = setTimeout(fetchPaper, 4000);
      } catch (error) {
        if (!cancelled) setLoadError(getApiErrorMessage(error, "无法加载论文知识，请重试。"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void fetchPaper();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [paperId, refreshKey]);

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
      URL.revokeObjectURL(link.href);
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
    if (!newNote.trim() || addingNote) return;
    setAddingNote(true);
    try {
      await api.post(`/api/knowledge/papers/${paperId}/annotations`, { type: "note", content: newNote });
      setNewNote("");
      // Refresh paper data
      const response = await api.get(`/api/knowledge/papers/${paperId}`);
      setPaper(response.data);
      toast.success("笔记已添加。");
    } catch {
      toast.error("添加笔记失败。");
    } finally {
      setAddingNote(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-8rem)] items-center justify-center">
        <Loader2 className="h-12 w-12 animate-spin text-primary" />
      </div>
    );
  }

  if (loadError || !paper) {
    return (
      <div className="flex h-[calc(100vh-8rem)] flex-col items-center justify-center space-y-4">
        <h1 className="text-xl font-semibold">论文知识加载失败</h1>
        <p className="text-muted-foreground">{loadError || "未找到论文。"}</p>
        <Button onClick={() => setRefreshKey((key) => key + 1)}>重新加载</Button>
        <Button onClick={() => navigate("/knowledge")}>返回知识笔记</Button>
      </div>
    );
  }

  if (!paper.metadata) {
    return (
      <div className="flex min-h-[calc(100vh-8rem)] flex-col items-center justify-center gap-4 text-center">
        {paper.extraction_status !== "error" && <Loader2 className="h-8 w-8 animate-spin text-primary" />}
        <h1 className="text-xl font-semibold">
          {paper.extraction_status === "error" ? "知识整理失败" : "知识正在整理"}
        </h1>
        <p className="max-w-md text-sm text-muted-foreground">
          {paper.extraction_status === "error"
            ? "请返回知识笔记列表重新整理。"
            : "发现、概念和复习卡会在完成后自动显示，可先返回阅读。"}
        </p>
        <Button variant="outline" onClick={() => navigate("/knowledge")}>
          返回知识笔记
        </Button>
        {paper.task_id && (
          <Button onClick={() => navigate(`/reader/${paper.task_id}`)}>
            <BookOpenCheck className="mr-2 h-4 w-4" />
            继续阅读
          </Button>
        )}
      </div>
    );
  }

  const {
    metadata,
    entities = [],
    relationships = [],
    findings = [],
    methods = [],
    datasets = [],
    flashcards = [],
    annotations = [],
  } = paper;

  // Build entity name map for relationship display
  const entityMap: Record<string, string> = {};
  entities.forEach((e) => {
    entityMap[e.id] = e.name;
  });

  return (
    <div className="page-stack knowledge-detail">
      {/* Header */}
      <div className="knowledge-detail-header">
        <div className="space-y-2">
          <Button variant="ghost" size="sm" onClick={() => navigate("/knowledge")}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            知识笔记
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
                <span
                  key={kw}
                  className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600"
                >
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          {paper.task_id && (
            <Button variant="default" size="sm" className="gap-2" onClick={() => navigate(`/reader/${paper.task_id}`)}>
              <BookOpenCheck className="h-4 w-4" />
              继续阅读
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Download className="h-4 w-4" />
                导出与同步
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled={obsidianSyncing} onSelect={() => void handleSyncObsidian()}>
                {obsidianSyncing ? "正在同步…" : "同步到 Obsidian"}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => void handleExport()}>知识备份 · JSON</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate("/settings")}>配置 Obsidian 连接</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {paper.structure?.sections && paper.structure.sections.length > 0 && paper.task_id && (
        <details className="knowledge-outline">
          <summary>论文目录</summary>
          <div className="grid gap-2 sm:grid-cols-2 mt-3">
            {paper.structure.sections.map((section) => (
              <button
                key={section.id}
                disabled={!section.block_id}
                className="flex justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-white"
                onClick={() => navigate(`/reader/${paper.task_id}?block=${section.block_id}`)}
              >
                <span>{section.title}</span>
                <span className="shrink-0 text-muted-foreground">{section.page ? `第 ${section.page} 页` : ""}</span>
              </button>
            ))}
          </div>
        </details>
      )}
      {/* Tabs */}
      <Tabs defaultValue="findings" className="space-y-4">
        <TabsList className="knowledge-tabs">
          <TabsTrigger value="findings">发现与证据 ({findings.length})</TabsTrigger>
          <TabsTrigger value="entities">概念与方法 ({entities.length})</TabsTrigger>
          <TabsTrigger value="notes">我的笔记 ({annotations.length})</TabsTrigger>
          <TabsTrigger value="flashcards">复习卡 ({flashcards.length})</TabsTrigger>
          <TabsTrigger value="relations">关系 ({relationships.length})</TabsTrigger>
        </TabsList>

        {/* Entities Tab */}
        <TabsContent value="entities" className="space-y-3">
          {entities.length === 0 && <p className="text-sm text-muted-foreground py-5">这篇论文还没有整理出的概念。</p>}
          <div className="grid gap-3 md:grid-cols-2">
            {entities.map((ent) => (
              <Card key={ent.id} className="border-gray-200/60">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-sm break-words">{ent.name}</span>
                        <span
                          className={cn(
                            "rounded-full px-2 py-0.5 text-[10px] font-medium",
                            TYPE_COLORS[ent.type] || "bg-gray-100 text-gray-600",
                          )}
                        >
                          {{
                            method: "方法",
                            model: "模型",
                            dataset: "数据集",
                            metric: "指标",
                            concept: "概念",
                            task: "任务",
                            person: "人物",
                            organization: "机构",
                          }[ent.type] || ent.type}
                        </span>
                      </div>
                      {ent.definition && (
                        <p className="text-xs text-muted-foreground leading-relaxed">{ent.definition}</p>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
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
          )}{" "}
        </TabsContent>

        {/* Findings Tab */}
        <TabsContent value="findings" className="space-y-4">
          <p className="text-sm text-muted-foreground">以下内容由 AI 整理，点击来源可回到原文核实。</p>
          {findings.length === 0 && <p className="py-5 text-muted-foreground">这篇论文尚未整理出发现。</p>}
          {findings.map((f) => (
            <Card key={f.id} className="border-gray-200/60">
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      "shrink-0 mt-0.5 rounded-full px-2 py-0.5 text-[10px] font-medium",
                      f.type === "result"
                        ? "bg-green-100 text-green-700"
                        : f.type === "limitation"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-blue-100 text-blue-700",
                    )}
                  >
                    {{ result: "结果", limitation: "局限", contribution: "贡献", observation: "观察" }[f.type] ||
                      f.type}
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm">{f.statement}</p>
                    {f.evidence && <p className="text-xs text-muted-foreground">证据：{f.evidence}</p>}
                    {(!f.evidence_refs?.length || !paper.task_id) && (
                      <p className="text-xs text-muted-foreground">未提供可定位的原文来源</p>
                    )}
                    {f.evidence_refs?.map(
                      (ref) =>
                        paper.task_id && (
                          <button
                            key={ref.block_id}
                            className="mt-1 inline-flex items-center text-xs text-primary hover:underline"
                            onClick={() => navigate(`/reader/${paper.task_id}?block=${ref.block_id}`)}
                          >
                            查看第 {ref.page} 页原文
                          </button>
                        ),
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
          {metadata.abstract && (
            <details className="knowledge-outline">
              <summary>论文摘要</summary>
              <p className="mt-3">{metadata.abstract}</p>
            </details>
          )}
        </TabsContent>

        {/* Flashcards Tab */}
        <TabsContent value="flashcards" className="space-y-3">
          <div className="section-heading">
            <h2 className="font-medium">复习卡</h2>
            <Button variant="outline" onClick={() => navigate("/knowledge/review")}>
              复习到期卡片
            </Button>
          </div>
          {flashcards.length === 0 && <p className="py-5 text-muted-foreground">这篇论文还没有复习卡。</p>}
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
                  <span className="text-[10px] text-muted-foreground ml-auto">难度：{fc.difficulty}/5</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        {/* Relations Tab */}
        <TabsContent value="relations" className="space-y-3">
          {relationships.length === 0 && <p className="py-5 text-muted-foreground">这篇论文还没有整理出的关系。</p>}
          {relationships.map((rel) => (
            <Card key={rel.id} className="border-gray-200/60">
              <CardContent className="p-4">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{entityMap[rel.source_entity_id] || rel.source || "?"}</span>
                  <span className="rounded-full bg-primary/10 text-primary px-2.5 py-0.5 text-xs font-medium">
                    {rel.type}
                  </span>
                  <span className="font-medium">{entityMap[rel.target_entity_id] || rel.target || "?"}</span>
                </div>
                {rel.description && <p className="text-xs text-muted-foreground mt-1">{rel.description}</p>}
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        {/* Notes Tab */}
        <TabsContent value="notes" className="space-y-3">
          <p className="text-sm text-muted-foreground">这里保存个人笔记。划线和高亮仍保留在阅读器的批注面板中。</p>
          <div className="flex gap-2">
            <Input
              aria-label="添加个人笔记"
              placeholder="写下自己的理解…"
              value={newNote}
              onChange={(e) => setNewNote(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
            />
            <Button
              size="sm"
              disabled={addingNote || !newNote.trim()}
              onClick={handleAddNote}
              className="gap-1 shrink-0"
            >
              <Plus className="h-4 w-4" />
              添加
            </Button>
          </div>
          {annotations?.map((ann) => (
            <Card key={ann.id} className="border-gray-200/60">
              <CardContent className="p-4">
                <p className="text-sm">{ann.content}</p>
                {ann.created_at && (
                  <p className="text-xs text-muted-foreground mt-1">{new Date(ann.created_at).toLocaleString()}</p>
                )}
              </CardContent>
            </Card>
          ))}
          {(!annotations || annotations.length === 0) && !newNote && (
            <p className="text-sm text-muted-foreground text-center py-8">暂无笔记。可在上方添加。</p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default PaperDetail;
