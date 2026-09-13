import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Search,
  Loader2,
  ArrowRight,
  ArrowUpRight,
  X,
  List,
  Network,
  NotebookPen,
  ChevronRight,
  ChevronLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader, EmptyState } from "@/components/workspace/PageHeader";
import GraphCanvas from "@/components/knowledge/GraphCanvas";
import { getApiErrorMessage } from "@/lib/errors";
import {
  indexGraph,
  layoutGraph,
  relationLabel,
  TYPE_LABELS,
  type GraphNode,
  type GraphEdge,
} from "@/lib/knowledge-graph";
import api from "@/lib/api";
import "./knowledge-graph.css";

export default function KnowledgeGraph() {
  const navigate = useNavigate();
  const [data, setData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState(() => (window.matchMedia("(max-width: 700px)").matches ? "list" : "graph"));
  const [scope, setScope] = useState<"focus" | "all">("focus");
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [group, setGroup] = useState(0);
  const inspector = useRef<HTMLElement>(null);
  const explorer = useRef<HTMLElement>(null);
  const graph = useMemo(() => indexGraph(data.nodes, data.edges), [data]);
  const selected = selectedId ? graph.byId.get(selectedId) : undefined;
  const selectedEdges = selected ? graph.adjacency.get(selected.id)! : [];
  const query = search.trim().toLocaleLowerCase();
  const matching = useMemo(
    () =>
      graph.ranked.filter(
        (node) => (type === "all" || node.type === type) && node.name.toLocaleLowerCase().includes(query),
      ),
    [graph, type, query],
  );
  const types = useMemo(() => [...new Set(data.nodes.map((node) => node.type))], [data.nodes]);
  const focusedLayout = useMemo(() => layoutGraph(data.nodes, data.edges, selectedId), [data, selectedId]);
  const neighborCount = Math.max(0, focusedLayout.nodes.length - 1);
  const groupCount = Math.max(1, Math.ceil(neighborCount / 8));
  const visibleGroup = Math.min(group, groupCount - 1);
  const layout = useMemo(() => {
    if (scope === "all") return layoutGraph(data.nodes, data.edges, null);
    const visibleNodes = [
      focusedLayout.nodes[0],
      ...focusedLayout.nodes.slice(1 + visibleGroup * 8, 1 + (visibleGroup + 1) * 8),
    ].filter(Boolean);
    return layoutGraph(visibleNodes, data.edges, selectedId);
  }, [data, scope, focusedLayout, selectedId, visibleGroup]);
  const paperCount = useMemo(() => new Set(data.nodes.map((node) => node.paper_id).filter(Boolean)).size, [data.nodes]);

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<{ nodes: GraphNode[]; edges: GraphEdge[] }>("/api/knowledge/graph");
      setData(response.data);
      setError("");
      setSelectedId((old) =>
        response.data.nodes.some((node) => node.id === old)
          ? old
          : (indexGraph(response.data.nodes, response.data.edges).ranked[0]?.id ?? null),
      );
    } catch (err) {
      setError(getApiErrorMessage(err, "无法加载图谱，请重试。"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void fetchGraph();
  }, [fetchGraph]);

  const selectNode = (id: string) => {
    setSelectedId(id);
    setGroup(0);
    setScope("focus");
    setSearch("");
    setType("all");
    requestAnimationFrame(() => {
      if (inspector.current) inspector.current.scrollTop = 0;
      if (window.matchMedia("(max-width: 1100px)").matches) {
        inspector.current?.scrollIntoView({ block: "start", behavior: "instant" });
        inspector.current?.focus({ preventScroll: true });
      }
    });
  };
  const showGraph = () => {
    setView("graph");
    setSearch("");
    setType("all");
    if (window.matchMedia("(max-width: 1100px)").matches) {
      requestAnimationFrame(() => explorer.current?.scrollIntoView({ block: "start", behavior: "instant" }));
    }
  };
  const showingResults = query.length > 0 || type !== "all";

  return (
    <div className="page-stack concept-page">
      <PageHeader title="关联图谱" description="从一个概念出发，沿着关系读懂论文。" />
      <nav className="knowledge-nav" aria-label="知识浏览方式">
        <NavLink end to="/knowledge">
          <NotebookPen size={17} />
          按论文查看
        </NavLink>
        <NavLink to="/knowledge/graph">
          <Network size={17} />
          关联图谱
        </NavLink>
      </nav>
      {loading ? (
        <div className="workspace-empty" role="status">
          <Loader2 className="animate-spin text-primary" />
          <p>正在加载概念与关系…</p>
        </div>
      ) : error ? (
        <EmptyState title="图谱加载失败" description={error} error>
          <Button onClick={() => void fetchGraph()}>重试</Button>
        </EmptyState>
      ) : data.nodes.length === 0 ? (
        <EmptyState
          title="还没有可查看的关系"
          description="先在“我的论文”中整理一篇论文的知识，概念和关系会显示在这里。"
        >
          <Button onClick={() => navigate("/dashboard")}>
            选择一篇论文
            <ArrowRight />
          </Button>
        </EmptyState>
      ) : (
        <>
          <div className="concept-toolbar">
            <div className="concept-search-controls">
              <div className="search-field concept-search">
                <Search size={16} />
                <Input
                  aria-label="查找概念名称"
                  placeholder="搜索概念、方法或模型"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                {search && (
                  <button className="concept-search-clear" aria-label="清除搜索" onClick={() => setSearch("")}>
                    <X size={15} />
                  </button>
                )}
              </div>
              <select aria-label="筛选概念类型" value={type} onChange={(event) => setType(event.target.value)}>
                <option value="all">全部类型</option>
                {types.map((value) => (
                  <option key={value} value={value}>
                    {TYPE_LABELS[value] || value}
                  </option>
                ))}
              </select>
            </div>
            <div className="concept-view-switch" role="group" aria-label="图谱浏览方式">
              <Button variant="ghost" size="sm" aria-pressed={view === "graph" && !showingResults} onClick={showGraph}>
                <Network size={16} />
                图谱
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-pressed={view === "list" || showingResults}
                onClick={() => setView("list")}
              >
                <List size={16} />
                列表
              </Button>
            </div>
          </div>
          <div className="concept-summary">
            <p>
              <strong>{data.nodes.length}</strong> 个概念<span>·</span>
              <strong>{graph.edges.length}</strong> 条关系<span>·</span>来自 {paperCount} 篇论文
            </p>
            <span>{showingResults ? `找到 ${matching.length} 个概念` : "点击概念查看定义与来源"}</span>
          </div>
          <div className="concept-workbench">
            <section className="concept-explorer" aria-label="概念浏览" ref={explorer}>
              {view === "graph" && !showingResults ? (
                <>
                  <div className="concept-map-heading">
                    <div>
                      <h2>{scope === "focus" ? "当前概念的关系" : "全部关系"}</h2>
                      <p>
                        {scope === "focus"
                          ? `${focusedLayout.nodes.length} 个概念 · ${focusedLayout.edges.length} 条直接关系`
                          : "选择一个概念，展开它的直接关系"}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setScope((old) => (old === "focus" ? "all" : "focus"))}
                    >
                      {scope === "focus" ? "全局图谱" : "聚焦当前概念"}
                      <ArrowUpRight size={15} />
                    </Button>
                  </div>
                  <GraphCanvas layout={layout} selectedId={selectedId} onSelect={selectNode} />
                  <div className="concept-map-footer">
                    <span>
                      <i />
                      当前概念
                    </span>
                    {scope === "focus" && groupCount > 1 ? (
                      <div className="concept-group-controls" role="group" aria-label="关联概念分组">
                        <span>
                          {visibleGroup * 8 + 1}–{Math.min((visibleGroup + 1) * 8, neighborCount)} / {neighborCount}{" "}
                          个关联概念
                        </span>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="上一组关联概念"
                          disabled={visibleGroup === 0}
                          onClick={() => setGroup(visibleGroup - 1)}
                        >
                          <ChevronLeft size={15} />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="下一组关联概念"
                          disabled={visibleGroup === groupCount - 1}
                          onClick={() => setGroup(visibleGroup + 1)}
                        >
                          <ChevronRight size={15} />
                        </Button>
                      </div>
                    ) : (
                      <p>拖动画布移动 · 点击节点展开</p>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="concept-map-heading">
                    <div>
                      <h2>{showingResults ? "搜索结果" : "全部概念"}</h2>
                      <p>选择概念，查看关联及其论文来源</p>
                    </div>
                    <span className="concept-result-count">{matching.length} 项</span>
                  </div>
                  {matching.length ? (
                    <div className="concept-list">
                      {matching.map((node) => (
                        <button
                          key={node.id}
                          aria-label={`${node.name} ${TYPE_LABELS[node.type] || node.type}`}
                          aria-pressed={node.id === selectedId}
                          onClick={() => selectNode(node.id)}
                        >
                          <span className="concept-list-text">
                            <strong>{node.name}</strong>
                            <span>
                              {TYPE_LABELS[node.type] || node.type} · {graph.adjacency.get(node.id)!.length} 条关系
                            </span>
                          </span>
                          <ChevronRight size={17} />
                        </button>
                      ))}
                    </div>
                  ) : (
                    <EmptyState title="没有匹配的概念" description="试试其他名称，或清除类型筛选。">
                      <Button
                        variant="outline"
                        onClick={() => {
                          setSearch("");
                          setType("all");
                        }}
                      >
                        清除筛选
                      </Button>
                    </EmptyState>
                  )}
                </>
              )}
            </section>
            <aside className="concept-inspector" aria-label="选中的概念" tabIndex={-1} ref={inspector}>
              {selected ? (
                <>
                  <div className="concept-inspector-heading">
                    <span className="concept-type-label">{TYPE_LABELS[selected.type] || selected.type}</span>
                    <span className="concept-selection-label">
                      <i />
                      当前概念
                    </span>
                  </div>
                  <h2>{selected.name}</h2>
                  <p className={cn("concept-definition", !selected.definition && "is-empty")}>
                    {selected.definition || "该概念暂未提取定义，可回到来源论文查看。"}
                  </p>
                  {selected.paper_id && (
                    <Button
                      variant="outline"
                      className="concept-source"
                      onClick={() => navigate(`/knowledge/paper/${selected.paper_id}`)}
                    >
                      查看来源论文
                      <ArrowUpRight size={16} />
                    </Button>
                  )}
                  {(view === "list" || showingResults) && (
                    <Button variant="ghost" className="concept-show-map" onClick={showGraph}>
                      <Network size={16} />
                      在图谱中展开
                    </Button>
                  )}
                  <div className="concept-relations-heading">
                    <h3>关联关系</h3>
                    <span>{selectedEdges.length}</span>
                  </div>
                  <div className="concept-relations">
                    {selectedEdges.map((edge) => {
                      const outgoing = edge.source === selected.id;
                      const other = graph.byId.get(outgoing ? edge.target : edge.source)!;
                      return (
                        <button key={edge.id} onClick={() => selectNode(other.id)}>
                          <span className="concept-relation-label">
                            {relationLabel(edge.type, outgoing)}
                            <ArrowRight size={12} />
                          </span>
                          <span className="concept-relation-name">
                            {other.name}
                            <ChevronRight size={15} />
                          </span>
                          {edge.description && <span className="concept-relation-description">{edge.description}</span>}
                        </button>
                      );
                    })}
                    {!selectedEdges.length && <p className="concept-no-relations">暂未整理出关联关系。</p>}
                  </div>
                </>
              ) : (
                <EmptyState title="选择一个概念" description="查看定义、关系和来源论文。" />
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
