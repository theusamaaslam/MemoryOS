import { useEffect, useState } from "react";
import { GraphView, type GraphEdge, type GraphNode } from "./components/GraphView";
import { LoginCard } from "./components/LoginCard";
import { TimelinePanel, type TimelineItem } from "./components/TimelinePanel";
import { DocsPanel } from "./components/DocsPanel";
import { fetchGraph, fetchTimeline, login, me, refresh, type Scope } from "./lib/api";

type ApiGraphNode = {
  node_id: string;
  label: string;
  node_type: string;
};

type ApiGraphEdge = {
  from_node: string;
  to_node: string;
  relation: string;
};

export function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("memoryos_token"));
  const [refreshToken, setRefreshToken] = useState<string | null>(() => localStorage.getItem("memoryos_refresh_token"));
  const [error, setError] = useState<string>("");
  const [graph, setGraph] = useState<{ nodes: ApiGraphNode[]; edges: ApiGraphEdge[] }>({
    nodes: [],
    edges: []
  });
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [scope, setScope] = useState<Scope | null>(null);

  useEffect(() => {
    if (!token) {
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        let activeToken = token;
        let currentUser;
        try {
          currentUser = await me(activeToken);
        } catch {
          if (!refreshToken) {
            throw new Error("Session expired");
          }
          const refreshed = await refresh(refreshToken);
          activeToken = refreshed.access_token;
          localStorage.setItem("memoryos_token", refreshed.access_token);
          localStorage.setItem("memoryos_refresh_token", refreshed.refresh_token);
          setToken(refreshed.access_token);
          setRefreshToken(refreshed.refresh_token);
          currentUser = await me(activeToken);
        }
        const nextScope = {
          org_id: currentUser.org_id,
          app_id: "memoryos-dashboard",
          user_id: currentUser.user_id,
          session_id: "default-session"
        };
        const [graphResponse, timelineResponse] = await Promise.all([
          fetchGraph(activeToken, nextScope),
          fetchTimeline(activeToken, nextScope)
        ]);
        if (!cancelled) {
          setScope(nextScope);
          setGraph(graphResponse);
          setTimeline(timelineResponse.items);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Failed to load dashboard");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [token, refreshToken]);

  if (!token) {
    return (
      <LoginCard
        error={error}
        onLogin={async (email, password) => {
          try {
            const tokens = await login(email, password);
            localStorage.setItem("memoryos_token", tokens.access_token);
            localStorage.setItem("memoryos_refresh_token", tokens.refresh_token);
            setToken(tokens.access_token);
            setRefreshToken(tokens.refresh_token);
            setError("");
          } catch (loginError) {
            setError(loginError instanceof Error ? loginError.message : "Login failed");
          }
        }}
      />
    );
  }

  const graphNodes: GraphNode[] = graph.nodes.map((node, index) => ({
    id: String(node.node_id || index),
    label: String(node.label || "Memory"),
    type: String(node.node_type || "Node"),
    x: 20 + ((index * 17) % 60),
    y: 28 + ((index * 13) % 50),
    size: 92 + ((index % 3) * 18)
  }));
  const graphEdges: GraphEdge[] = graph.edges.map((edge) => ({
    from: String(edge.from_node),
    to: String(edge.to_node),
    label: String(edge.relation || "linked_to")
  }));

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">MemoryOS</p>
          <h1>Self-improving memory for AI agents</h1>
        </div>
        <div className="topbar-actions">
          <button className="ghost-button" onClick={() => window.open("/docs", "_blank")}>
            API Docs
          </button>
          <button className="primary-button">{scope ? `${scope.org_id} / ${scope.app_id}` : "Loading..."}</button>
        </div>
      </header>

      <main className="dashboard-grid">
        <section className="hero-panel">
          <div className="hero-copy">
            <p className="eyebrow">Knowledge Graph</p>
            <h2>Watch memory evolve from session logs into retrieval-ready intelligence.</h2>
            <p>
              Live chats land in fast session memory, then reflection promotes durable facts, failure
              lessons, and graph relations that improve the next answer.
            </p>
            {error ? <p className="error-text">{error}</p> : null}
          </div>
          <GraphView nodes={graphNodes} edges={graphEdges} />
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Memory Evolution</p>
              <h3>Timeline</h3>
            </div>
          </div>
          <TimelinePanel items={timeline} />
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Developer Portal</p>
              <h3>API and MCP Docs</h3>
            </div>
          </div>
          <DocsPanel />
        </section>
      </main>
    </div>
  );
}
