import { useEffect, useMemo, useRef, useState } from "react";
import { Minus, Plus, Scan } from "lucide-react";
import { Button } from "@/components/ui/button";
import { graphNameLines, NODE_HEIGHT, NODE_WIDTH, TYPE_LABELS, type GraphLayout } from "@/lib/knowledge-graph";

type Props = { layout: GraphLayout; selectedId: string | null; onSelect: (id: string) => void };

export default function GraphCanvas({ layout, selectedId, onSelect }: Props) {
  const stage = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 570 });
  const [camera, setCamera] = useState({ zoom: 1, x: 0, y: 0 });
  const [cameraLayout, setCameraLayout] = useState(layout);
  const [hovered, setHovered] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  useEffect(() => {
    const element = stage.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  if (cameraLayout !== layout) {
    setCameraLayout(layout);
    setCamera({ zoom: 1, x: 0, y: 0 });
  }
  const scale = Math.min(size.width / layout.width, size.height / layout.height) * 0.94 * camera.zoom;
  const x = (size.width - layout.width * scale) / 2 + camera.x;
  const y = (size.height - layout.height * scale) / 2 + camera.y;
  const labels = useMemo(
    () => new Map(layout.nodes.map((node) => [node.id, graphNameLines(node.name)])),
    [layout.nodes],
  );
  const changeZoom = (amount: number) =>
    setCamera((old) => {
      const zoom = Math.max(0.5, Math.min(3, Math.round((old.zoom + amount) * 10) / 10));
      return { zoom, x: (old.x * zoom) / old.zoom, y: (old.y * zoom) / old.zoom };
    });

  return (
    <div className="concept-map-stage" ref={stage}>
      <svg
        className="concept-map-svg"
        viewBox={`0 0 ${size.width} ${size.height}`}
        role="group"
        aria-label="论文概念关系图。可选择概念，或拖动画布。"
        onPointerDown={(event) => {
          if (event.button !== 0 || (event.target as Element).closest("[data-graph-node]")) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = { x: event.clientX, y: event.clientY, panX: camera.x, panY: camera.y };
        }}
        onPointerMove={(event) => {
          const start = drag.current;
          if (start)
            setCamera((old) => ({
              ...old,
              x: start.panX + event.clientX - start.x,
              y: start.panY + event.clientY - start.y,
            }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onLostPointerCapture={() => {
          drag.current = null;
        }}
      >
        <g transform={`translate(${x} ${y}) scale(${scale})`}>
          <g aria-hidden="true" className="concept-map-edges">
            {layout.edges.map((edge) => {
              const from = layout.positions.get(edge.source)!;
              const to = layout.positions.get(edge.target)!;
              const direction = to.x >= from.x ? 1 : -1;
              const startX = from.x + (direction * NODE_WIDTH) / 2;
              const endX = to.x - (direction * NODE_WIDTH) / 2;
              const middleX = (startX + endX) / 2;
              const path =
                edge.source === edge.target
                  ? `M ${from.x - 40} ${from.y - NODE_HEIGHT / 2} C ${from.x - 60} ${from.y - 90}, ${from.x + 60} ${from.y - 90}, ${from.x + 40} ${from.y - NODE_HEIGHT / 2}`
                  : `M ${startX} ${from.y} C ${middleX} ${from.y}, ${middleX} ${to.y}, ${endX} ${to.y}`;
              return (
                <path
                  key={edge.id}
                  d={path}
                  data-active={hovered === edge.source || hovered === edge.target || undefined}
                />
              );
            })}
          </g>
          {layout.nodes.map((node) => {
            const position = layout.positions.get(node.id)!;
            const lines = labels.get(node.id)!;
            const selected = node.id === selectedId;
            return (
              <g
                key={node.id}
                className="concept-map-node"
                data-graph-node={node.id}
                data-selected={selected || undefined}
                transform={`translate(${position.x - NODE_WIDTH / 2} ${position.y - NODE_HEIGHT / 2})`}
                role="button"
                tabIndex={0}
                aria-label={`${node.name} ${TYPE_LABELS[node.type] || node.type}`}
                aria-pressed={selected}
                onClick={() => onSelect(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(node.id);
                  }
                }}
                onMouseEnter={() => setHovered(node.id)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(node.id)}
                onBlur={() => setHovered(null)}
              >
                <title>{node.name}</title>
                <rect width={NODE_WIDTH} height={NODE_HEIGHT} rx={8} />
                <circle className="concept-map-node-dot" cx={17} cy={17} r={3} />
                <text className="concept-map-type" x={27} y={21}>
                  {TYPE_LABELS[node.type] || node.type}
                </text>
                <text className="concept-map-name" x={14} y={43}>
                  {lines.map((line, index) => (
                    <tspan key={index} x={14} dy={index ? 17 : 0}>
                      {line}
                    </tspan>
                  ))}
                </text>
                {selected && <path className="concept-map-selected-tick" d="M 163 17 l 4 4 l 7 -8" />}
              </g>
            );
          })}
        </g>
      </svg>
      <div className="concept-map-controls" role="group" aria-label="图谱缩放">
        <Button
          variant="ghost"
          size="icon"
          aria-label="缩小图谱"
          disabled={camera.zoom <= 0.5}
          onClick={() => changeZoom(-0.2)}
        >
          <Minus size={16} />
        </Button>
        <output aria-label="图谱缩放比例">{Math.round(camera.zoom * 100)}%</output>
        <Button
          variant="ghost"
          size="icon"
          aria-label="放大图谱"
          disabled={camera.zoom >= 3}
          onClick={() => changeZoom(0.2)}
        >
          <Plus size={16} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="适应画布"
          title="适应画布"
          onClick={() => setCamera({ zoom: 1, x: 0, y: 0 })}
        >
          <Scan size={17} />
        </Button>
      </div>
    </div>
  );
}
