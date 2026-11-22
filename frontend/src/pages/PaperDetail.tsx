import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  ChevronRight,
  Database,
  Download,
  FileText,
  FlaskConical,
  GraduationCap,
  Loader2,
  NotebookPen,
  Plus,
  RotateCcw,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/workspace/PageHeader";
import { useFeatures } from "@/lib/features";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { downloadFile, parseServerDate } from "@/lib/format";
import { relationLabel, TYPE_LABELS } from "@/lib/knowledge-graph";

interface PaperKnowledge {
  id: string;
  task_id?: string | null;
  title?: string;
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

const FINDING_TYPES: Record<string, { label: string; tone: string }> = {
  result: { label: "结果", tone: "is-ok" },
  limitation: { label: "局限", tone: "is-warn" },
  contribution: { label: "贡献", tone: "is-info" },
  observation: { label: "观察", tone: "" },
};
const ENTITY_TONES: Record<string, string> = {
  method: "is-info",
  model: "is-accent",
  dataset: "is-ok",
  metric: "is-warn",
};

const PaperDetail = () => {
  const features = useFeatures();
  const { paperId } = useParams<{ paperId: string }>();
  const navigate = useNavigate();
  const [paper, setPaper] = useState<PaperKnowledge | null>(null);
  const [loading, setLoading] = useState(true);
  const [newNote, setNewNote] = useState("");
  const [addingNote, setAddingNote] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [obsidianSyncing, setObsidianSyncing] = useState(false);
  const [startingExtract, setStartingExtract] = useState(false);

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
        // Keep polling while an extraction is running so results appear without a reload.
        if (!data.metadata && data.extraction_status === "extracting") timer = setTimeout(fetchPaper, 4000);
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

  const startExtraction = useCallback(async () => {
    if (!paper?.task_id) return;
    setStartingExtract(true);
    try {
      await api.post(`/api/knowledge/extract/${paper.task_id}`);
      toast.success("已开始整理知识笔记。");
      setRefreshKey((key) => key + 1);
    } catch (error) {
      toast.error(getApiErrorMessage(error, "无法开始整理。"));
    } finally {
      setStartingExtract(false);
    }
  }, [paper?.task_id]);

  const handleExport = async () => {
    try {
      await downloadFile(
        `/api/knowledge/export/paper/${paperId}`,
        `${paper?.metadata.title || "paper"}.epaper.json`,
        "application/json",
      );
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
      if (response.data.status === "partial") toast.warning("部分笔记已同步到 Obsidian，部分文件写入失败。");
      else toast.success("已同步到 Obsidian。");
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
      const response = await api.get(`/api/knowledge/papers/${paperId}`);
      setPaper(response.data);
      toast.success("笔记已添加。");
    } catch {
      toast.error("添加笔记失败。");
    } finally {
      setAddingNote(false);
    }
  };

  if (loading && !paper) {
    return (
      <div className="page" role="status" aria-label="正在加载论文知识">
        <span className="skeleton" style={{ width: 120, height: 14 }} />
        <span className="skeleton" style={{ width: "72%", height: 38 }} />
        <span className="skeleton" style={{ width: "40%", height: 16 }} />
        <span className="skeleton" style={{ width: "100%", height: 220, borderRadius: 18 }} />
      </div>
    );
  }

  if (loadError || !paper) {
    return (
      <EmptyState title="论文知识加载失败" description={loadError || "未找到论文。"} error>
        <Button onClick={() => setRefreshKey((key) => key + 1)}>重新加载</Button>
        <Button variant="secondary" onClick={() => navigate("/knowledge")}>
          返回知识笔记
        </Button>
      </EmptyState>
    );
  }

  if (!paper.metadata) {
    const failed = ["error", "failed"].includes(paper.extraction_status || "");
    const extracting = paper.extraction_status === "extracting";
    return (
      <div className="page">
        <Button variant="ghost" size="sm" className="detail-back" onClick={() => navigate("/knowledge")}>
          <ArrowLeft />
          知识笔记
        </Button>
        <div className="extract-state ep-enter">
          {extracting ? (
            <span className="extract-orbit" aria-hidden="true" />
          ) : (
            <span className={`empty-state-icon`} aria-hidden="true" style={failed ? { background: "var(--danger-soft)", color: "var(--danger)" } : undefined}>
              <NotebookPen />
            </span>
          )}
          <h1>{failed ? "知识整理失败" : extracting ? "正在整理知识笔记" : "尚未整理知识笔记"}</h1>
          {paper.title ? <p style={{ color: "var(--ink-2)" }}>{paper.title}</p> : null}
          <p>
            {failed
              ? "这次没有整理完成，可能是 AI 服务暂时不可用。可以直接重试。"
              : extracting
                ? "AI 正在提取发现、概念和复习卡，完成后会自动显示在这里。可以先回去继续阅读。"
                : "整理后，这里会出现论文的主要发现、概念关系和复习卡，每一条都能回到原文核实。"}
          </p>
          <div className="empty-actions">
            {paper.task_id && !extracting && (
              <Button disabled={startingExtract} onClick={() => void startExtraction()}>
                {startingExtract ? <Loader2 className="spin" /> : failed ? <RotateCcw /> : <NotebookPen />}
                {startingExtract ? "启动中…" : failed ? "重新整理" : "开始整理"}
              </Button>
            )}
            {paper.task_id && (
              <Button variant="secondary" onClick={() => navigate(`/reader/${paper.task_id}`)}>
                <BookOpenCheck />
                继续阅读
              </Button>
            )}
          </div>
        </div>
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
  const entityMap = new Map(entities.map((entity) => [entity.id, entity.name]));
  const sections = paper.structure?.sections || [];
  const openSource = (blockId: string) => paper.task_id && navigate(`/reader/${paper.task_id}?block=${blockId}`);

  return (
    <div className="page">
      <header className="detail-header ep-enter">
        <Button variant="ghost" size="sm" className="detail-back" onClick={() => navigate("/knowledge")}>
          <ArrowLeft />
          知识笔记
        </Button>
        <h1>{metadata.title}</h1>
        {(metadata.authors?.length || metadata.year || metadata.venue) && (
          <p className="detail-byline">
            {[metadata.authors?.map((a) => a.name).join("、"), metadata.venue, metadata.year].filter(Boolean).join(" · ")}
          </p>
        )}
        {metadata.keywords && metadata.keywords.length > 0 && (
          <div className="detail-keywords">
            {metadata.keywords.map((kw) => (
              <span key={kw} className="pill">
                {kw}
              </span>
            ))}
          </div>
        )}
        <div className="detail-actions">
          {paper.task_id && (
            <Button onClick={() => navigate(`/reader/${paper.task_id}`)}>
              <BookOpenCheck />
              继续阅读
            </Button>
          )}
          {flashcards.length > 0 && (
            <Button variant="secondary" asChild>
              <Link to="/review">
                <GraduationCap />
                复习卡片
              </Link>
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline">
                <Download />
                导出与同步
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onSelect={() => void handleExport()}>
                <FileText />
                知识备份 · JSON
              </DropdownMenuItem>
              {features.local_sync && (
                <>
                  <DropdownMenuItem disabled={obsidianSyncing} onSelect={() => void handleSyncObsidian()}>
                    <NotebookPen />
                    {obsidianSyncing ? "正在同步…" : "同步到 Obsidian"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => navigate("/settings#connection-settings")}>Obsidian 设置</DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {(metadata.abstract || (sections.length > 0 && paper.task_id)) && (
        <div className="disclosure-group ep-enter">
          {metadata.abstract && (
            <details className="disclosure">
              <summary>
                论文摘要
                <ChevronRight aria-hidden="true" />
              </summary>
              <div className="disclosure-body">
                <p>{metadata.abstract}</p>
              </div>
            </details>
          )}
          {sections.length > 0 && paper.task_id && (
            <details className="disclosure">
              <summary>
                论文目录
                <ChevronRight aria-hidden="true" />
              </summary>
              <div className="disclosure-body outline-list">
                {sections.map((section) => (
                  <button
                    key={section.id}
                    type="button"
                    disabled={!section.block_id}
                    onClick={() => section.block_id && openSource(section.block_id)}
                  >
                    <span>{section.title}</span>
                    <span>{section.page ? `第 ${section.page} 页` : ""}</span>
                  </button>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      <Tabs defaultValue="findings" className="detail-tabs">
        <TabsList aria-label="笔记内容">
          <TabsTrigger value="findings">
            发现与证据 <span className="tab-count">{findings.length}</span>
          </TabsTrigger>
          <TabsTrigger value="entities">
            概念与方法 <span className="tab-count">{entities.length}</span>
          </TabsTrigger>
          <TabsTrigger value="relations">
            关系 <span className="tab-count">{relationships.length}</span>
          </TabsTrigger>
          <TabsTrigger value="flashcards">
            复习卡 <span className="tab-count">{flashcards.length}</span>
          </TabsTrigger>
          <TabsTrigger value="notes">
            我的笔记 <span className="tab-count">{annotations.length}</span>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="findings">
          <div className="finding-list">
            <p className="tab-intro">以下内容由 AI 整理，点“原文”回到论文核实。</p>
            {findings.length === 0 && <EmptyState title="还没有整理出发现" description="重新整理后再来看看。" />}
            {findings.map((finding) => {
              const kind = FINDING_TYPES[finding.type] || { label: finding.type, tone: "" };
              return (
                <article key={finding.id} className="finding">
                  <span className={`pill ${kind.tone}`}>{kind.label}</span>
                  <div>
                    <p className="finding-statement">{finding.statement}</p>
                    {finding.evidence && <p className="finding-evidence">{finding.evidence}</p>}
                    {finding.evidence_refs?.length && paper.task_id ? (
                      <div className="finding-sources">
                        {finding.evidence_refs.map((ref) => (
                          <button
                            key={ref.block_id}
                            type="button"
                            className="source-chip"
                            aria-label={`查看第 ${ref.page} 页原文`}
                            onClick={() => openSource(ref.block_id)}
                          >
                            <FileText aria-hidden="true" />
                            原文第 {ref.page} 页
                            <ArrowRight aria-hidden="true" />
                          </button>
                        ))}
                      </div>
                    ) : (
                      <p className="source-missing">未提供可定位的原文来源</p>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </TabsContent>

        <TabsContent value="entities">
          <div className="stack-list">
            {entities.length === 0 && <EmptyState title="还没有整理出概念" />}
            <div className="concept-grid">
              {entities.map((entity) => (
                <article key={entity.id} className="concept-card">
                  <div className="concept-card-head">
                    <strong>{entity.name}</strong>
                    <span className={`pill ${ENTITY_TONES[entity.type] || ""}`}>{TYPE_LABELS[entity.type] || entity.type}</span>
                  </div>
                  {entity.definition && <p>{entity.definition}</p>}
                </article>
              ))}
            </div>
            {methods.length > 0 && (
              <>
                <h3 className="subsection-title">
                  <FlaskConical aria-hidden="true" /> 方法
                </h3>
                <div className="concept-grid">
                  {methods.map((method, index) => (
                    <article key={index} className="concept-card">
                      <strong>{method.name}</strong>
                      <p>{method.description}</p>
                    </article>
                  ))}
                </div>
              </>
            )}
            {datasets.length > 0 && (
              <>
                <h3 className="subsection-title">
                  <Database aria-hidden="true" /> 数据集
                </h3>
                <div className="concept-grid">
                  {datasets.map((dataset, index) => (
                    <article key={index} className="concept-card">
                      <strong>{dataset.name}</strong>
                      <p>{dataset.description}</p>
                      {dataset.usage && <p>用途：{dataset.usage}</p>}
                    </article>
                  ))}
                </div>
              </>
            )}
          </div>
        </TabsContent>

        <TabsContent value="relations">
          {relationships.length === 0 ? (
            <EmptyState title="还没有整理出关系" />
          ) : (
            <div className="group-list">
              {relationships.map((relation) => (
                <div key={relation.id} className="relation-row">
                  <div className="relation-line">
                    <span>{entityMap.get(relation.source_entity_id) || relation.source || "?"}</span>
                    <span className="pill">{relationLabel(relation.type, true)}</span>
                    <span>{entityMap.get(relation.target_entity_id) || relation.target || "?"}</span>
                  </div>
                  {relation.description && <p>{relation.description}</p>}
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="flashcards">
          <div className="stack-list">
            <div className="section-toolbar">
              <p className="tab-intro">复习卡会按记忆曲线安排复习时间。</p>
              <Button variant="secondary" size="sm" asChild>
                <Link to="/review">
                  <GraduationCap />
                  复习到期卡片
                </Link>
              </Button>
            </div>
            {flashcards.length === 0 && <EmptyState title="这篇论文还没有复习卡" />}
            {flashcards.map((card) => (
              <article key={card.id} className="qa-card">
                <p className="qa-q">{card.front}</p>
                <p className="qa-a">{card.back}</p>
                <div className="qa-card-foot">
                  {card.tags.map((tag) => (
                    <span key={tag} className="pill">
                      {tag}
                    </span>
                  ))}
                  <span>难度 {card.difficulty}/5</span>
                </div>
              </article>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="notes">
          <div className="stack-list">
            <p className="tab-intro">这里保存个人笔记。划线和高亮仍保留在阅读器的批注面板中。</p>
            <form
              className="note-compose"
              onSubmit={(event) => {
                event.preventDefault();
                void handleAddNote();
              }}
            >
              <Textarea
                aria-label="添加个人笔记"
                placeholder="写下自己的理解…"
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    void handleAddNote();
                  }
                }}
              />
              <div className="note-compose-foot">
                <span>⌘ Enter 保存</span>
                <Button type="submit" size="sm" disabled={addingNote || !newNote.trim()}>
                  {addingNote ? <Loader2 className="spin" /> : <Plus />}
                  添加
                </Button>
              </div>
            </form>
            {annotations.length > 0 ? (
              <div className="group-list">
                {annotations.map((annotation) => (
                  <div key={annotation.id} className="note-item">
                    <p>{annotation.content}</p>
                    {annotation.created_at && <time>{parseServerDate(annotation.created_at)?.toLocaleString("zh-CN")}</time>}
                  </div>
                ))}
              </div>
            ) : (
              !newNote && <p className="tab-intro" style={{ textAlign: "center", padding: "24px 0" }}>暂无笔记。</p>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default PaperDetail;
