import { describe, expect, it } from "vitest";
import {
  indexGraph,
  layoutGraph,
  NODE_HEIGHT,
  NODE_WIDTH,
  relationLabel,
  type GraphNode,
  type GraphEdge,
} from "../knowledge-graph";

const node = (id: string, name = id): GraphNode => ({ id, name, type: "concept", importance: 0.8, paper_id: "paper" });
const edge = (source: string, target: string): GraphEdge => ({
  id: `${source}-${target}`,
  source,
  target,
  type: "uses",
});

describe("knowledge graph exploration", () => {
  it("shows direct relationships without merging identically named concepts from different sources", () => {
    const nodes = [node("a"), node("b", "Same name"), node("c", "Same name"), node("d"), node("isolated")];
    const edges = [edge("a", "b"), edge("c", "a"), edge("b", "d"), edge("a", "missing")];
    const layout = layoutGraph(nodes, edges, "a");
    expect(new Set(layout.nodes.map((n) => n.id))).toEqual(new Set(["a", "b", "c"]));
    expect(layout.edges.map((e) => e.id)).toEqual(["a-b", "c-a"]);
    expect(indexGraph(nodes, edges).ranked[0].id).toBe("a");
  });

  it("keeps every node, including disconnected concepts, in the global view", () => {
    const nodes = [node("a"), node("b"), node("isolated")];
    const layout = layoutGraph(nodes, [edge("a", "b")], null);
    expect(new Set(layout.nodes.map((n) => n.id))).toEqual(new Set(nodes.map((n) => n.id)));
    expect(layout.positions.size).toBe(3);
  });

  it("keeps dense graph labels inside the canvas without overlapping node bounds", () => {
    const nodes = Array.from({ length: 80 }, (_, i) => node(String(i)));
    const edges = nodes.slice(1).map((n) => edge("0", n.id));
    for (const focus of [null, "0", "missing"]) {
      const layout = layoutGraph(nodes, edges, focus);
      const points = [...layout.positions.values()];
      for (let i = 0; i < points.length; i++) {
        const p = points[i];
        expect(p.x - NODE_WIDTH / 2).toBeGreaterThanOrEqual(0);
        expect(p.x + NODE_WIDTH / 2).toBeLessThanOrEqual(layout.width);
        expect(p.y - NODE_HEIGHT / 2).toBeGreaterThanOrEqual(0);
        expect(p.y + NODE_HEIGHT / 2).toBeLessThanOrEqual(layout.height);
        for (const q of points.slice(i + 1)) {
          expect(Math.abs(p.x - q.x) >= NODE_WIDTH || Math.abs(p.y - q.y) >= NODE_HEIGHT).toBe(true);
        }
      }
      expect(layoutGraph(nodes, edges, focus).positions).toEqual(layout.positions);
    }
  });

  it("describes a relationship from the selected concept's direction", () => {
    expect(relationLabel("part_of", true)).toBe("属于");
    expect(relationLabel("part_of", false)).toBe("包含");
    expect(relationLabel("custom_relation", false)).toBe("custom_relation");
  });
});
