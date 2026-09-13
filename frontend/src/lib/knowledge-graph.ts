export interface GraphNode {
  id: string;
  name: string;
  type: string;
  definition?: string;
  importance: number;
  paper_id: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  description?: string;
}

export const NODE_WIDTH = 214;
export const NODE_HEIGHT = 76;
export const TYPE_LABELS: Record<string, string> = {
  method: "方法",
  model: "模型",
  dataset: "数据集",
  metric: "指标",
  concept: "概念",
  task: "任务",
  person: "人物",
  organization: "机构",
};

const RELATION_LABELS: Record<string, [string, string]> = {
  extends: ["扩展", "被扩展于"],
  uses: ["使用", "被使用于"],
  evaluates_on: ["评估于", "用于评估"],
  outperforms: ["优于", "表现低于"],
  similar_to: ["类似于", "类似于"],
  contradicts: ["与之矛盾", "与之矛盾"],
  part_of: ["属于", "包含"],
  requires: ["需要", "被需要于"],
};

export function relationLabel(type: string, outgoing: boolean) {
  return RELATION_LABELS[type]?.[outgoing ? 0 : 1] ?? type;
}

/** Keep source identities intact: identically named concepts can come from different papers. */
export function indexGraph(nodes: GraphNode[], edges: GraphEdge[]) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const adjacency = new Map(nodes.map((node) => [node.id, [] as GraphEdge[]]));
  const validEdges = edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target));
  for (const edge of validEdges) {
    adjacency.get(edge.source)!.push(edge);
    if (edge.source !== edge.target) adjacency.get(edge.target)!.push(edge);
  }
  const ranked = [...nodes].sort(
    (a, b) =>
      adjacency.get(b.id)!.length - adjacency.get(a.id)!.length ||
      b.importance - a.importance ||
      a.name.localeCompare(b.name) ||
      a.id.localeCompare(b.id),
  );
  return { byId, adjacency, edges: validEdges, ranked };
}

export type GraphLayout = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  positions: Map<string, { x: number; y: number }>;
  width: number;
  height: number;
};

/** A fixed layout avoids random reshuffles, clipped labels, and overlapping node bounds. */
export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[], focusId: string | null): GraphLayout {
  const graph = indexGraph(nodes, edges);
  const focus = focusId ? graph.byId.get(focusId) : undefined;
  const positions: GraphLayout["positions"] = new Map();
  if (focus) {
    const connected = new Set([focus.id]);
    for (const edge of graph.adjacency.get(focus.id)!) {
      connected.add(edge.source);
      connected.add(edge.target);
    }
    const neighbors = graph.ranked.filter((node) => node.id !== focus.id && connected.has(node.id));
    const rows = Math.ceil(neighbors.length / 2);
    const height = Math.max(480, rows * 106 + 64);
    positions.set(focus.id, { x: 440, y: height / 2 });
    neighbors.forEach((node, index) => {
      const side = index % 2;
      const sideCount = Math.ceil((neighbors.length - side) / 2);
      positions.set(node.id, {
        x: side === 0 ? 150 : 730,
        y: height / 2 + (Math.floor(index / 2) - (sideCount - 1) / 2) * 106,
      });
    });
    return {
      nodes: [focus, ...neighbors],
      edges: graph.edges.filter((edge) => edge.source === focus.id || edge.target === focus.id),
      positions,
      width: 880,
      height,
    };
  }
  // Breadth-first ordering places connected concepts near each other in the overview.
  const ordered: GraphNode[] = [];
  const visited = new Set<string>();
  for (const root of graph.ranked) {
    if (visited.has(root.id)) continue;
    const queue = [root.id];
    visited.add(root.id);
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      ordered.push(graph.byId.get(id)!);
      for (const edge of graph.adjacency.get(id)!) {
        const other = edge.source === id ? edge.target : edge.source;
        if (!visited.has(other)) {
          visited.add(other);
          queue.push(other);
        }
      }
    }
  }
  const columns = Math.max(1, Math.ceil(Math.sqrt(nodes.length * 0.65)));
  const rows = Math.ceil(nodes.length / columns);
  ordered.forEach((node, index) =>
    positions.set(node.id, {
      x: 132 + (index % columns) * 232,
      y: 88 + Math.floor(index / columns) * 128,
    }),
  );
  return {
    nodes: ordered,
    edges: graph.edges,
    positions,
    width: Math.max(320, columns * 232 + 32),
    height: Math.max(320, rows * 128 + 48),
  };
}

export function graphNameLines(name: string): string[] {
  const segments = name.match(/\S+\s*/gu) ?? [name];
  const lines = [""];
  const weight = (value: string) => [...value].reduce((sum, c) => sum + (c.codePointAt(0)! > 0xff ? 1.7 : 1), 0);
  for (const segment of segments) {
    if (weight(segment.trim()) <= 24 && weight(lines[lines.length - 1] + segment.trim()) > 24) lines.push("");
    for (const char of segment) {
      const last = lines.length - 1;
      if (weight(lines[last] + char) > 24) lines.push(char.trimStart());
      else lines[last] += char;
    }
  }
  return lines
    .slice(0, 2)
    .map((line, index) => (index === 1 && lines.length > 2 ? line.trimEnd().slice(0, -1) + "…" : line.trim()));
}
