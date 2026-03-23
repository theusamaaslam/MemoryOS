export type GraphNode = {
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  size: number;
};

export type GraphEdge = {
  from: string;
  to: string;
  label: string;
};

type GraphViewProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export function GraphView({ nodes, edges }: GraphViewProps) {
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));

  return (
    <div className="graph-stage">
      {nodes.length === 0 ? <p className="empty-state">No graph data yet. Trigger memory reflection to populate the graph.</p> : null}
      <svg className="graph-canvas" viewBox="0 0 100 100" preserveAspectRatio="none">
        {edges.map((edge) => {
          const from = byId[edge.from];
          const to = byId[edge.to];
          if (!from || !to) {
            return null;
          }
          return (
            <g key={`${edge.from}-${edge.to}`}>
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} className="graph-edge" />
              <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 1} className="graph-edge-label">
                {edge.label}
              </text>
            </g>
          );
        })}
      </svg>
      {nodes.map((node) => (
        <article
          key={node.id}
          className={`graph-node graph-node-${node.type.toLowerCase().replace(/\s+/g, "-")}`}
          style={{ left: `${node.x}%`, top: `${node.y}%`, width: `${node.size}px` }}
        >
          <span>{node.type}</span>
          <strong>{node.label}</strong>
        </article>
      ))}
    </div>
  );
}
