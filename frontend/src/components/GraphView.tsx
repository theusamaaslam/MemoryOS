import { useDeferredValue, useEffect, useRef, useState } from "react";
import { BadgeCheck, Network, Orbit, Search, Sparkles, X } from "lucide-react";

export type GraphNode = {
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  size: number;
  confidence?: number;
  supportCount?: number;
  excerpt?: string;
  memoryScope?: string;
  scopeRef?: string | null;
  conversationId?: string | null;
  evidencePreview?: GraphEvidence[];
  metadata?: Record<string, unknown>;
};

export type GraphEdge = {
  from: string;
  to: string;
  label: string;
  confidence?: number;
  supportCount?: number;
  excerpt?: string;
  evidencePreview?: GraphEvidence[];
  metadata?: Record<string, unknown>;
};

export type GraphEvidence = {
  evidenceId: string;
  layer: string;
  kind: string;
  title: string;
  excerpt: string;
  source: string;
  memoryScope: string;
  createdAt: string;
};

type GraphViewProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

type LayoutNode = GraphNode & {
  left: number;
  top: number;
  radius: number;
  degree: number;
  fill: string;
  glow: string;
};

type LayoutEdge = GraphEdge & {
  path: string;
  labelX: number;
  labelY: number;
  gradientId: string;
};

type LayoutScene = {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  clusters: Array<{ key: string; x: number; y: number; radius: number; fill: string; glow: string }>;
};

const PALETTE = [
  { fill: "rgba(40, 201, 255, 0.88)", glow: "rgba(40, 201, 255, 0.24)" },
  { fill: "rgba(255, 120, 173, 0.88)", glow: "rgba(255, 120, 173, 0.22)" },
  { fill: "rgba(255, 200, 74, 0.9)", glow: "rgba(255, 200, 74, 0.2)" },
  { fill: "rgba(74, 222, 128, 0.88)", glow: "rgba(74, 222, 128, 0.22)" },
  { fill: "rgba(129, 140, 248, 0.88)", glow: "rgba(129, 140, 248, 0.24)" },
  { fill: "rgba(251, 146, 60, 0.88)", glow: "rgba(251, 146, 60, 0.2)" },
];

function hashValue(input: string): number {
  let value = 0;
  for (const character of input) {
    value = (value * 33 + character.charCodeAt(0)) % 1009;
  }
  return value;
}

function truncateText(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 3)}...`;
}

function normalizeSearchValue(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\s_-]+/g, " ").replace(/\s+/g, " ").trim();
}

function formatEvidenceDate(value: string) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function paletteForType(type: string) {
  return PALETTE[hashValue(type) % PALETTE.length];
}

function filterGraphData(nodes: GraphNode[], edges: GraphEdge[], searchValue: string, activeType: string) {
  const typeFilteredNodes = activeType === "all" ? nodes : nodes.filter((node) => node.type === activeType);
  const visibleNodeIds = new Set(typeFilteredNodes.map((node) => node.id));
  const typeFilteredEdges = edges.filter((edge) => visibleNodeIds.has(edge.from) && visibleNodeIds.has(edge.to));
  const query = normalizeSearchValue(searchValue);
  if (!query) {
    return { nodes: typeFilteredNodes, edges: typeFilteredEdges };
  }

  const nodesById = new Map(typeFilteredNodes.map((node) => [node.id, node]));
  const matchedNodeIds = new Set(
    typeFilteredNodes
      .filter((node) => normalizeSearchValue(`${node.label} ${node.type} ${node.excerpt ?? ""}`).includes(query))
      .map((node) => node.id),
  );
  const matchedEdges = typeFilteredEdges.filter((edge) => {
    const fromNode = nodesById.get(edge.from);
    const toNode = nodesById.get(edge.to);
    return normalizeSearchValue(`${edge.label} ${edge.excerpt ?? ""} ${fromNode?.label ?? ""} ${toNode?.label ?? ""}`).includes(query);
  });

  const contextNodeIds = new Set(matchedNodeIds);
  for (const edge of typeFilteredEdges) {
    if (matchedNodeIds.has(edge.from) || matchedNodeIds.has(edge.to)) {
      contextNodeIds.add(edge.from);
      contextNodeIds.add(edge.to);
    }
  }
  for (const edge of matchedEdges) {
    contextNodeIds.add(edge.from);
    contextNodeIds.add(edge.to);
  }

  return {
    nodes: typeFilteredNodes.filter((node) => contextNodeIds.has(node.id)),
    edges: typeFilteredEdges.filter((edge) => contextNodeIds.has(edge.from) && contextNodeIds.has(edge.to)),
  };
}

function normalizePositions(
  positioned: Array<LayoutNode & { vx: number; vy: number; clusterX: number; clusterY: number }>,
  width: number,
  height: number,
  margin: number,
) {
  if (positioned.length === 0) {
    return positioned;
  }

  const minLeft = Math.min(...positioned.map((node) => node.left));
  const maxLeft = Math.max(...positioned.map((node) => node.left));
  const minTop = Math.min(...positioned.map((node) => node.top));
  const maxTop = Math.max(...positioned.map((node) => node.top));
  const spanX = Math.max(maxLeft - minLeft, 1);
  const spanY = Math.max(maxTop - minTop, 1);
  const usableWidth = Math.max(width - margin * 2, 240);
  const usableHeight = Math.max(height - margin * 2, 180);
  const scale = Math.min(usableWidth / spanX, usableHeight / spanY, 1.16);
  const offsetX = margin + (usableWidth - spanX * scale) / 2 - minLeft * scale;
  const offsetY = margin + (usableHeight - spanY * scale) / 2 - minTop * scale;

  for (const node of positioned) {
    node.left = node.left * scale + offsetX;
    node.top = node.top * scale + offsetY;
    node.clusterX = node.clusterX * scale + offsetX;
    node.clusterY = node.clusterY * scale + offsetY;
  }
  return positioned;
}

function buildScene(nodes: GraphNode[], edges: GraphEdge[], width: number, height: number): LayoutScene {
  const safeWidth = Math.max(width, 680);
  const safeHeight = Math.max(height, 440);
  const margin = 82;
  const centerX = safeWidth / 2;
  const centerY = safeHeight / 2;

  const degreeMap = new Map<string, number>();
  const byType = new Map<string, GraphNode[]>();
  for (const node of nodes) {
    degreeMap.set(node.id, 0);
    const bucket = byType.get(node.type) ?? [];
    bucket.push(node);
    byType.set(node.type, bucket);
  }
  for (const edge of edges) {
    degreeMap.set(edge.from, (degreeMap.get(edge.from) ?? 0) + 1);
    degreeMap.set(edge.to, (degreeMap.get(edge.to) ?? 0) + 1);
  }

  const typeKeys = Array.from(byType.keys());
  const typeCenters = new Map<string, { x: number; y: number; fill: string; glow: string; radius: number }>();
  const columns = Math.min(Math.max(Math.ceil(Math.sqrt(Math.max(typeKeys.length, 1))), 1), 3);
  const rows = Math.max(Math.ceil(typeKeys.length / columns), 1);
  const cellWidth = Math.max((safeWidth - margin * 2) / columns, 180);
  const cellHeight = Math.max((safeHeight - margin * 2) / rows, 160);

  typeKeys.forEach((type, index) => {
    const palette = PALETTE[hashValue(type) % PALETTE.length];
    const column = index % columns;
    const row = Math.floor(index / columns);
    const jitterX = ((hashValue(`${type}:x`) % 15) - 7) * 3;
    const jitterY = ((hashValue(`${type}:y`) % 15) - 7) * 3;
    typeCenters.set(type, {
      x: margin + cellWidth * column + cellWidth / 2 + jitterX,
      y: margin + cellHeight * row + cellHeight / 2 + jitterY,
      fill: palette.fill,
      glow: palette.glow,
      radius: Math.min(cellWidth, cellHeight) * 0.46,
    });
  });

  const positioned = nodes.map((node, index) => {
    const siblings = byType.get(node.type) ?? [node];
    const siblingIndex = siblings.findIndex((entry) => entry.id === node.id);
    const cluster = typeCenters.get(node.type) ?? { x: centerX, y: centerY, fill: PALETTE[0].fill, glow: PALETTE[0].glow, radius: 130 };
    const goldenAngle = 2.399963229728653;
    const orbitRadius = Math.min(cluster.radius, 32 + Math.sqrt(siblingIndex + 1) * 34 + (degreeMap.get(node.id) ?? 0) * 6);
    const angle = siblingIndex * goldenAngle + index * 0.09;
    const confidence = typeof node.confidence === "number" ? node.confidence : 0.68;
    return {
      ...node,
      left: cluster.x + Math.cos(angle) * orbitRadius,
      top: cluster.y + Math.sin(angle) * orbitRadius,
      radius: Math.max(62, Math.min(94, 58 + (degreeMap.get(node.id) ?? 0) * 6 + confidence * 12)),
      degree: degreeMap.get(node.id) ?? 0,
      fill: cluster.fill,
      glow: cluster.glow,
      vx: 0,
      vy: 0,
      clusterX: cluster.x,
      clusterY: cluster.y,
    };
  });

  for (let step = 0; step < 110; step += 1) {
    for (let leftIndex = 0; leftIndex < positioned.length; leftIndex += 1) {
      const leftNode = positioned[leftIndex];
      for (let rightIndex = leftIndex + 1; rightIndex < positioned.length; rightIndex += 1) {
        const rightNode = positioned[rightIndex];
        const dx = rightNode.left - leftNode.left;
        const dy = rightNode.top - leftNode.top;
        const distanceSquared = Math.max(dx * dx + dy * dy, 1);
        const distance = Math.sqrt(distanceSquared);
        const desiredGap = (leftNode.radius + rightNode.radius) * 0.62;
        const repel = distance < desiredGap ? 2.3 : 0.36;
        const force = (repel * 6400) / distanceSquared;
        const nx = dx / distance;
        const ny = dy / distance;
        leftNode.vx -= nx * force;
        leftNode.vy -= ny * force;
        rightNode.vx += nx * force;
        rightNode.vy += ny * force;
      }
    }

    for (const edge of edges) {
      const fromNode = positioned.find((node) => node.id === edge.from);
      const toNode = positioned.find((node) => node.id === edge.to);
      if (!fromNode || !toNode) {
        continue;
      }
      const dx = toNode.left - fromNode.left;
      const dy = toNode.top - fromNode.top;
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const targetDistance = Math.max(140, (fromNode.radius + toNode.radius) * 0.92);
      const spring = (distance - targetDistance) * 0.024;
      const nx = dx / distance;
      const ny = dy / distance;
      fromNode.vx += nx * spring;
      fromNode.vy += ny * spring;
      toNode.vx -= nx * spring;
      toNode.vy -= ny * spring;
    }

    for (const node of positioned) {
      node.vx += (node.clusterX - node.left) * 0.018;
      node.vy += (node.clusterY - node.top) * 0.018;
      node.vx += (centerX - node.left) * 0.002;
      node.vy += (centerY - node.top) * 0.002;
      node.vx *= 0.76;
      node.vy *= 0.76;
      node.left = Math.min(safeWidth - margin, Math.max(margin, node.left + node.vx));
      node.top = Math.min(safeHeight - margin, Math.max(margin, node.top + node.vy));
    }
  }

  normalizePositions(positioned, safeWidth, safeHeight, margin);

  const layoutNodes: LayoutNode[] = positioned.map(({ vx, vy, clusterX, clusterY, ...node }) => node);
  const layoutEdges: LayoutEdge[] = edges
    .map((edge, index) => {
      const fromNode = layoutNodes.find((node) => node.id === edge.from);
      const toNode = layoutNodes.find((node) => node.id === edge.to);
      if (!fromNode || !toNode) {
        return null;
      }
      const dx = toNode.left - fromNode.left;
      const dy = toNode.top - fromNode.top;
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const nx = -dy / distance;
      const ny = dx / distance;
      const curve = Math.min(52, 14 + distance * 0.06 + (index % 2) * 10);
      const controlX = (fromNode.left + toNode.left) / 2 + nx * curve;
      const controlY = (fromNode.top + toNode.top) / 2 + ny * curve;
      return {
        ...edge,
        path: `M ${fromNode.left} ${fromNode.top} Q ${controlX} ${controlY} ${toNode.left} ${toNode.top}`,
        labelX: (fromNode.left + 2 * controlX + toNode.left) / 4,
        labelY: (fromNode.top + 2 * controlY + toNode.top) / 4,
        gradientId: `graph-edge-gradient-${index}`,
      };
    })
    .filter((edge): edge is LayoutEdge => edge !== null);

  const clusters = typeKeys.map((type) => {
    const members = positioned.filter((node) => node.type === type);
    const cluster = typeCenters.get(type)!;
    const x = members.length > 0 ? members.reduce((sum, node) => sum + node.clusterX, 0) / members.length : cluster.x;
    const y = members.length > 0 ? members.reduce((sum, node) => sum + node.clusterY, 0) / members.length : cluster.y;
    return {
      key: type,
      x,
      y,
      radius: cluster.radius * 1.7,
      fill: cluster.fill,
      glow: cluster.glow,
    };
  });

  return { nodes: layoutNodes, edges: layoutEdges, clusters };
}

export function GraphView({ nodes, edges }: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [dimensions, setDimensions] = useState({ width: 920, height: 520 });
  const [scene, setScene] = useState<LayoutScene>({ nodes: [], edges: [], clusters: [] });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(nodes[0]?.id ?? null);
  const [searchValue, setSearchValue] = useState("");
  const [activeType, setActiveType] = useState<string>("all");
  const deferredSearchValue = useDeferredValue(searchValue);
  const filteredGraph = filterGraphData(nodes, edges, deferredSearchValue, activeType);
  const hasActiveFilters = searchValue.trim().length > 0 || activeType !== "all";
  const typeSummary = Array.from(new Set(nodes.map((node) => node.type)))
    .sort((left, right) => left.localeCompare(right))
    .map((type) => {
      const palette = paletteForType(type);
      return {
        type,
        fill: palette.fill,
        glow: palette.glow,
        totalCount: nodes.filter((node) => node.type === type).length,
        visibleCount: filteredGraph.nodes.filter((node) => node.type === type).length,
      };
    });

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      setDimensions({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setScene(buildScene(filteredGraph.nodes, filteredGraph.edges, dimensions.width, dimensions.height));
  }, [nodes, edges, dimensions.width, dimensions.height, deferredSearchValue, activeType]);

  useEffect(() => {
    if (!filteredGraph.nodes.find((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(filteredGraph.nodes[0]?.id ?? null);
    }
  }, [filteredGraph.nodes, selectedNodeId]);

  if (nodes.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center p-6 text-center h-full w-full text-secondary"
        style={{ opacity: 0.72 }}
      >
        <Network size={56} className="mb-4 text-brand" />
        <p style={{ fontSize: "1.1rem", marginBottom: "0.5rem", fontWeight: 600 }}>Knowledge Graph is Empty</p>
        <p className="text-sm" style={{ maxWidth: "26rem" }}>
          No grounded entities have been extracted yet. Add evidence, then run reflection to build a clean graph snapshot.
        </p>
      </div>
    );
  }

  const selectedNode = scene.nodes.find((node) => node.id === selectedNodeId) ?? scene.nodes[0];
  const connectedEdges = scene.edges.filter((edge) => edge.from === selectedNode?.id || edge.to === selectedNode?.id);
  const relatedIds = new Set(connectedEdges.map((edge) => (edge.from === selectedNode?.id ? edge.to : edge.from)));
  const relatedNodes = scene.nodes.filter((node) => relatedIds.has(node.id));
  const relatedConnections = connectedEdges
    .map((edge) => {
      const neighborId = edge.from === selectedNode?.id ? edge.to : edge.from;
      const neighbor = scene.nodes.find((node) => node.id === neighborId) ?? relatedNodes.find((node) => node.id === neighborId);
      return { edge, neighbor };
    })
    .sort((left, right) => (right.edge.supportCount ?? 0) - (left.edge.supportCount ?? 0));
  const averageConfidence =
    scene.nodes.length > 0
      ? scene.nodes.reduce((sum, node) => sum + (typeof node.confidence === "number" ? node.confidence : 0.7), 0) / scene.nodes.length
      : 0;

  return (
    <div
      ref={containerRef}
      className="w-full h-full"
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        minHeight: "440px",
        overflow: "hidden",
        borderRadius: "var(--radius-md)",
        background:
          "radial-gradient(circle at 18% 18%, rgba(40, 201, 255, 0.12), transparent 28%), radial-gradient(circle at 82% 16%, rgba(255, 120, 173, 0.1), transparent 24%), radial-gradient(circle at 52% 84%, rgba(74, 222, 128, 0.11), transparent 26%), linear-gradient(180deg, #fbfdff 0%, #f3f7fd 100%)",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(rgba(39,74,135,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(39,74,135,0.05) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
          maskImage: "radial-gradient(circle at center, black 44%, transparent 100%)",
          opacity: 0.55,
          pointerEvents: "none",
        }}
      />

      <div
        style={{
          position: "absolute",
          top: "1rem",
          left: "1rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.75rem",
          maxWidth: "min(420px, calc(100% - 2rem))",
          zIndex: 5,
        }}
      >
        <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
          <div className="glass-panel" style={{ padding: "0.65rem 0.9rem", borderRadius: "999px", background: "rgba(255, 255, 255, 0.94)" }}>
            <div className="flex items-center gap-2 text-sm">
              <Orbit size={16} className="text-brand" />
              <span>
                {scene.nodes.length}/{nodes.length} nodes
              </span>
            </div>
          </div>
          <div className="glass-panel" style={{ padding: "0.65rem 0.9rem", borderRadius: "999px", background: "rgba(255, 255, 255, 0.94)" }}>
            <div className="flex items-center gap-2 text-sm">
              <Sparkles size={16} className="text-brand" />
              <span>
                {scene.edges.length}/{edges.length} relations
              </span>
            </div>
          </div>
          <div className="glass-panel" style={{ padding: "0.65rem 0.9rem", borderRadius: "999px", background: "rgba(255, 255, 255, 0.94)" }}>
            <div className="flex items-center gap-2 text-sm">
              <BadgeCheck size={16} className="text-brand" />
              <span>{Math.round(averageConfidence * 100)}% grounded confidence</span>
            </div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: "0.85rem 1rem", background: "rgba(255, 255, 255, 0.94)" }}>
          <p className="text-xs text-secondary" style={{ textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.55rem" }}>
            Focus Graph
          </p>
          <div className="flex items-center gap-3" style={{ flexWrap: "wrap" }}>
            <div style={{ position: "relative", flex: "1 1 260px", minWidth: "220px" }}>
              <Search
                size={15}
                style={{ position: "absolute", left: "0.9rem", top: "50%", transform: "translateY(-50%)", color: "var(--text-secondary)" }}
              />
              <input
                className="input-base"
                value={searchValue}
                onChange={(event) => setSearchValue(event.target.value)}
                placeholder="Search entity, relation, or evidence excerpt"
                style={{ paddingLeft: "2.35rem", background: "#fff" }}
              />
            </div>
            {hasActiveFilters ? (
              <button className="btn btn-ghost" type="button" onClick={() => { setSearchValue(""); setActiveType("all"); }}>
                <X size={14} />
                Clear
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div
        className="glass-panel"
        style={{
          position: "absolute",
          top: "1rem",
          right: "1rem",
          padding: "0.9rem 1rem",
          background: "rgba(255, 255, 255, 0.94)",
          maxWidth: "260px",
          zIndex: 5,
        }}
      >
        <p className="text-xs text-secondary" style={{ textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.65rem" }}>
          Entity Types
        </p>
        <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
          <button
            type="button"
            className={`btn btn-ghost${activeType === "all" ? " active" : ""}`}
            onClick={() => setActiveType("all")}
            style={{ padding: "0.4rem 0.7rem" }}
          >
            All
          </button>
          {typeSummary.map((entry) => (
            <button
              key={entry.type}
              type="button"
              className={`btn btn-ghost${activeType === entry.type ? " active" : ""}`}
              onClick={() => setActiveType((current) => (current === entry.type ? "all" : entry.type))}
              style={{
                padding: "0.4rem 0.75rem",
                background: activeType === entry.type ? "rgba(39, 74, 135, 0.08)" : "#fff",
                borderColor: activeType === entry.type ? "rgba(39, 74, 135, 0.18)" : "var(--border-subtle)",
              }}
            >
              <span style={{ width: "10px", height: "10px", borderRadius: "999px", background: entry.fill, boxShadow: `0 0 12px ${entry.glow}` }} />
              <span>{entry.type}</span>
              <span style={{ opacity: 0.7 }}>
                {entry.visibleCount}/{entry.totalCount}
              </span>
            </button>
          ))}
        </div>
      </div>

      {scene.nodes.length === 0 ? (
        <div className="flex flex-col items-center justify-center text-center" style={{ position: "absolute", inset: 0, padding: "2rem", zIndex: 4 }}>
          <Search size={54} className="text-brand" style={{ marginBottom: "1rem" }} />
          <p style={{ fontSize: "1.1rem", marginBottom: "0.4rem" }}>No graph matches the current focus</p>
          <p className="text-sm text-secondary" style={{ maxWidth: "430px", marginBottom: "1rem" }}>
            Try another entity name, relation label, or evidence phrase. Clearing the focus restores the full grounded graph.
          </p>
          {hasActiveFilters ? (
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => {
                setSearchValue("");
                setActiveType("all");
              }}
            >
              Reset Focus
            </button>
          ) : null}
        </div>
      ) : (
        <>
          {scene.clusters.map((cluster) => (
            <div
              key={cluster.key}
              style={{
                position: "absolute",
                left: cluster.x,
                top: cluster.y,
                width: cluster.radius * 2,
                height: cluster.radius * 2,
                borderRadius: "999px",
                transform: "translate(-50%, -50%)",
                background: `radial-gradient(circle, ${cluster.glow} 0%, transparent 70%)`,
                filter: "blur(18px)",
                opacity: 0.95,
                pointerEvents: "none",
              }}
            />
          ))}

          <svg
            viewBox={`0 0 ${Math.max(dimensions.width, 680)} ${Math.max(dimensions.height, 440)}`}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
          >
            <defs>
              {scene.edges.map((edge) => {
                const fromNode = scene.nodes.find((node) => node.id === edge.from);
                const toNode = scene.nodes.find((node) => node.id === edge.to);
                if (!fromNode || !toNode) {
                  return null;
                }
                return (
                  <linearGradient key={edge.gradientId} id={edge.gradientId} x1={fromNode.left} y1={fromNode.top} x2={toNode.left} y2={toNode.top}>
                    <stop offset="0%" stopColor={fromNode.fill} />
                    <stop offset="100%" stopColor={toNode.fill} />
                  </linearGradient>
                );
              })}
            </defs>

            {scene.edges.map((edge) => {
              const active = edge.from === selectedNode?.id || edge.to === selectedNode?.id;
              const opacity = active ? 1 : Math.max(typeof edge.confidence === "number" ? edge.confidence : 0.55, 0.2);
              return (
                <g key={`${edge.from}-${edge.to}-${edge.label}`}>
                  <path d={edge.path} fill="none" stroke="rgba(39,74,135,0.08)" strokeWidth={active ? 7 : 5} strokeLinecap="round" />
                  <path
                    d={edge.path}
                    fill="none"
                    stroke={`url(#${edge.gradientId})`}
                    strokeWidth={active ? 3.4 : 2.5}
                    strokeLinecap="round"
                    opacity={opacity}
                  />
                  {active ? (
                    <g transform={`translate(${edge.labelX}, ${edge.labelY})`}>
                      <rect x={-60} y={-12} width={120} height={24} rx={12} fill="rgba(255, 255, 255, 0.96)" stroke="rgba(39, 74, 135, 0.12)" />
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        fill="var(--text-primary)"
                        style={{ fontSize: "10px", letterSpacing: "0.08em", textTransform: "uppercase" }}
                      >
                        {truncateText(edge.label.replace(/_/g, " "), 18)}
                      </text>
                    </g>
                  ) : null}
                </g>
              );
            })}
          </svg>

          {scene.nodes.map((node) => {
            const active = node.id === selectedNode?.id;
            const isRelated = relatedIds.has(node.id);
            const confidence = Math.round((typeof node.confidence === "number" ? node.confidence : 0.7) * 100);
            return (
              <button
                key={node.id}
                type="button"
                onClick={() => setSelectedNodeId(node.id)}
                title={node.label}
                style={{
                  position: "absolute",
                  left: `${node.left}px`,
                  top: `${node.top}px`,
                  transform: "translate(-50%, -50%)",
                width: `${node.radius}px`,
                height: `${node.radius}px`,
                borderRadius: "999px",
                border: active ? "1px solid rgba(39, 74, 135, 0.26)" : "1px solid rgba(39, 74, 135, 0.1)",
                background: "linear-gradient(180deg, rgba(255,255,255,0.99), rgba(244,247,252,0.98))",
                boxShadow: active
                  ? "0 0 0 5px rgba(39, 74, 135, 0.08), 0 26px 54px rgba(22, 41, 75, 0.18)"
                  : isRelated
                    ? "0 16px 36px rgba(22, 41, 75, 0.14)"
                    : "0 12px 24px rgba(22, 41, 75, 0.1)",
                  color: "var(--text-primary)",
                  cursor: "pointer",
                  padding: "0.7rem",
                  transition: "box-shadow 0.22s ease, transform 0.22s ease, border-color 0.22s ease",
                  zIndex: active ? 3 : 2,
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    inset: "6px",
                    borderRadius: "999px",
                    background: `radial-gradient(circle at 35% 26%, rgba(255,255,255,0.95), transparent 32%), radial-gradient(circle at 50% 115%, ${node.glow}, transparent 68%)`,
                    border: "1px solid rgba(39, 74, 135, 0.06)",
                  }}
                />
                <div style={{ position: "relative", zIndex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "0.28rem" }}>
                  <span
                    style={{
                      fontSize: "10px",
                      letterSpacing: "0.12em",
                      textTransform: "uppercase",
                      opacity: 0.9,
                      padding: "0.18rem 0.45rem",
                      borderRadius: "999px",
                      background: "rgba(39, 74, 135, 0.08)",
                    }}
                  >
                    {truncateText(node.type, 12)}
                  </span>
                  <strong style={{ fontSize: "0.8rem", lineHeight: 1.1, textAlign: "center", maxWidth: "100%" }}>
                    {truncateText(node.label, 18)}
                  </strong>
                  <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)" }}>{confidence}%</span>
                </div>
              </button>
            );
          })}
        </>
      )}

      {selectedNode && scene.nodes.length > 0 ? (
        <div
          className="glass-panel"
          style={{
            position: "absolute",
            right: "1.25rem",
            bottom: "1.25rem",
            width: "min(340px, calc(100% - 2.5rem))",
            maxHeight: "min(48%, 430px)",
            overflowY: "auto",
            padding: "1rem 1.05rem",
            background: "rgba(255, 255, 255, 0.96)",
            zIndex: 5,
          }}
        >
          <div className="flex items-center justify-between gap-4 mb-2">
            <div>
              <p className="text-xs text-secondary" style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Selected Entity
              </p>
              <h4 style={{ fontSize: "1.1rem", marginTop: "0.25rem" }}>{selectedNode.label}</h4>
            </div>
            <span className="badge badge-info">{selectedNode.type}</span>
          </div>
          <div className="flex gap-2 mb-3" style={{ flexWrap: "wrap" }}>
            <span className="badge badge-info">{Math.round((selectedNode.confidence ?? 0.7) * 100)}% confidence</span>
            <span className="badge badge-info">{selectedNode.supportCount ?? 0} evidence link{selectedNode.supportCount === 1 ? "" : "s"}</span>
            <span className="badge badge-info">{connectedEdges.length} relation{connectedEdges.length === 1 ? "" : "s"}</span>
            {selectedNode.memoryScope ? <span className="badge badge-success">{selectedNode.memoryScope}</span> : null}
            {selectedNode.scopeRef ? <span className="badge badge-warning">{truncateText(selectedNode.scopeRef, 24)}</span> : null}
          </div>
          {selectedNode.excerpt ? (
            <p className="text-sm text-secondary" style={{ marginBottom: "0.85rem" }}>
              {selectedNode.excerpt}
            </p>
          ) : (
            <p className="text-sm text-secondary" style={{ marginBottom: "0.85rem" }}>
              This node is part of the current grounded graph snapshot for the active scope.
            </p>
          )}
          <p className="text-xs text-secondary" style={{ textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.6rem" }}>
            Grounding Evidence
          </p>
          <div style={{ display: "grid", gap: "0.55rem", marginBottom: "0.9rem", maxHeight: "210px", overflow: "auto", paddingRight: "0.15rem" }}>
            {selectedNode.evidencePreview && selectedNode.evidencePreview.length > 0 ? (
              selectedNode.evidencePreview.slice(0, 4).map((evidence) => (
                <div
                  key={evidence.evidenceId}
                  style={{
                    display: "grid",
                    gap: "0.4rem",
                    padding: "0.75rem 0.8rem",
                    borderRadius: "14px",
                    border: "1px solid var(--border-subtle)",
                    background: "var(--bg-surface-alt)",
                  }}
                >
                  <div className="flex items-center justify-between gap-3" style={{ flexWrap: "wrap" }}>
                    <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
                      <span className="badge badge-info">{evidence.layer}</span>
                      <span className="badge badge-warning">{evidence.kind}</span>
                      <span className="badge badge-success">{evidence.memoryScope}</span>
                    </div>
                    <span className="text-xs text-secondary">{formatEvidenceDate(evidence.createdAt)}</span>
                  </div>
                  <strong style={{ fontSize: "0.92rem" }}>{evidence.title}</strong>
                  <p className="text-xs text-secondary">{evidence.excerpt}</p>
                  <span className="text-xs text-secondary">{evidence.source}</span>
                </div>
              ))
            ) : (
              <span className="text-xs text-secondary">No evidence previews are attached to this node yet.</span>
            )}
          </div>
          <p className="text-xs text-secondary" style={{ textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "0.6rem" }}>
            Connected Evidence
          </p>
          <div style={{ display: "grid", gap: "0.55rem" }}>
            {relatedConnections.length > 0 ? (
              relatedConnections.slice(0, 5).map(({ edge, neighbor }) => (
                <button
                  key={`${edge.from}-${edge.to}-${edge.label}`}
                  type="button"
                  onClick={() => neighbor && setSelectedNodeId(neighbor.id)}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.35rem",
                    padding: "0.7rem 0.8rem",
                    borderRadius: "14px",
                    border: "1px solid var(--border-subtle)",
                    background: "var(--bg-surface-alt)",
                    color: "inherit",
                    textAlign: "left",
                    cursor: neighbor ? "pointer" : "default",
                  }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2" style={{ flexWrap: "wrap" }}>
                      <span className="badge badge-info">{edge.label.replace(/_/g, " ")}</span>
                      <strong style={{ fontSize: "0.9rem" }}>{neighbor?.label ?? "Linked entity"}</strong>
                    </div>
                    <span className="text-xs text-secondary">{Math.round((edge.confidence ?? 0.6) * 100)}%</span>
                  </div>
                  <p className="text-xs text-secondary">
                    {edge.excerpt || neighbor?.excerpt || "Grounded by the current graph evidence set."}
                  </p>
                </button>
              ))
            ) : (
              <span className="text-xs text-secondary">This entity has no visible neighboring nodes yet.</span>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
