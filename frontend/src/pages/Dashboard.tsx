import { type ChangeEvent, type FormEvent, useEffect, useState } from "react";
import { Brain, Copy, Database, FileUp, Network, Plus, RefreshCw, Search, Settings2, Sparkles, WandSparkles } from "lucide-react";
import { GraphView, type GraphEdge, type GraphEvidence, type GraphNode } from "../components/GraphView";
import type { TimelineItem } from "../components/TimelinePanel";
import {
  closeConversation,
  fetchGraph,
  fetchMcpTools,
  fetchSessions,
  fetchTimeline,
  type GraphResult,
  ingestDocumentFile,
  ingestDocumentText,
  type McpToolDescriptor,
  type MemoryScope,
  recallMemories,
  reflectSession,
  type RecallResult,
  type Scope,
  type SessionSummary,
} from "../lib/api";
import { useToast } from "../components/ToastProvider";

interface DashboardProps {
  scope: Scope | null;
  token: string | null;
  onSessionChange: (sessionId: string) => void;
}

function parseTags(rawTags: string): string[] {
  return rawTags
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function buildSessionId(): string {
  return `session-${new Date().toISOString().replace(/[:.]/g, "-")}`;
}

const MCP_API_KEY_STORAGE_KEY = "memoryos_mcp_api_key";
const MCP_API_KEY_APP_STORAGE_KEY = "memoryos_mcp_api_key_app_id";

function resolveDirectBackendBaseUrl(): string {
  if (typeof window === "undefined") {
    return "http://127.0.0.1:8000";
  }
  const host = ["localhost", "127.0.0.1"].includes(window.location.hostname) ? "127.0.0.1" : window.location.hostname;
  return `${window.location.protocol}//${host}:8000`;
}

function buildMcpSseServerBlock(params: {
  endpoint: string;
  apiKey: string;
  orgId: string;
  appId: string;
  userId: string;
  sessionId: string;
}): string {
  return `"memoryos": {
  "command": "npx",
  "args": [
    "-y",
    "mcp-remote",
    "${params.endpoint}",
    "--allow-http",
    "--transport",
    "sse-only",
    "--header",
    "X-API-Key:${params.apiKey}",
    "--header",
    "X-MemoryOS-Org-Id:${params.orgId}",
    "--header",
    "X-MemoryOS-App-Id:${params.appId}",
    "--header",
    "X-MemoryOS-User-Id:${params.userId}",
    "--header",
    "X-MemoryOS-Session-Id:${params.sessionId}"
  ],
  "env": {}
}`;
}

function formatSessionActivity(value?: string | null): string {
  if (!value) {
    return "No activity yet";
  }
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTimelineDate(value: string): string {
  return new Date(value).toLocaleString([], {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function truncateText(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 3)}...`;
}

function layerBadgeClass(layer: string): string {
  if (layer === "resolution") return "badge-success";
  if (layer === "failure") return "badge-danger";
  if (layer === "retrieval_hint") return "badge-warning";
  return "badge-info";
}

function sessionStatusBadge(status?: string | null): string {
  if (status === "resolved") return "badge-success";
  if (status === "archived") return "badge-warning";
  return "badge-info";
}

function recallScore(metadata: Record<string, unknown>): string {
  const score = metadata.retrieval_score;
  if (typeof score === "number") {
    return score.toFixed(2);
  }
  return "n/a";
}

function mapGraphEvidencePreview(
  evidencePreview: GraphResult["nodes"][number]["evidence_preview"] | GraphResult["edges"][number]["evidence_preview"] | undefined,
): GraphEvidence[] {
  if (!Array.isArray(evidencePreview)) {
    return [];
  }
  return evidencePreview.map((item, index) => ({
    evidenceId: String(item.evidence_id || `evidence-${index}`),
    layer: String(item.layer || "unknown"),
    kind: String(item.kind || "evidence"),
    title: String(item.title || item.source || "Evidence"),
    excerpt: String(item.excerpt || ""),
    source: String(item.source || item.title || "MemoryOS"),
    memoryScope: String(item.memory_scope || "conversation"),
    createdAt: String(item.created_at || ""),
  }));
}

export function Dashboard({ scope, token, onSessionChange }: DashboardProps) {
  const { showToast } = useToast();
  const [error, setError] = useState("");
  const [graphScope, setGraphScope] = useState<MemoryScope>("app");
  const [graph, setGraph] = useState<GraphResult>({
    memory_scope: "app",
    scope_counts: {},
    summary: {
      node_count: 0,
      edge_count: 0,
      evidence_count: 0,
      source_count: 0,
      orphan_node_count: 0,
      duplicate_label_count: 0,
      ungrounded_node_count: 0,
      ungrounded_edge_count: 0,
      source_names: [],
    },
    nodes: [],
    edges: [],
  });
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [isReflecting, setIsReflecting] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [isRecalling, setIsRecalling] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState("");
  const [historyFilter, setHistoryFilter] = useState("all");
  const [sourceName, setSourceName] = useState("Manual knowledge drop");
  const [documentText, setDocumentText] = useState("");
  const [documentTags, setDocumentTags] = useState("manual,uploaded");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [recallQuery, setRecallQuery] = useState("");
  const [recallTopK, setRecallTopK] = useState(5);
  const [recallResult, setRecallResult] = useState<RecallResult | null>(null);
  const [recallError, setRecallError] = useState("");
  const [mcpTools, setMcpTools] = useState<McpToolDescriptor[]>([]);
  const [storedMcpApiKey, setStoredMcpApiKey] = useState<string>(() => (typeof window !== "undefined" ? localStorage.getItem(MCP_API_KEY_STORAGE_KEY) || "" : ""));
  const [storedMcpApiKeyAppId, setStoredMcpApiKeyAppId] = useState<string>(() => (typeof window !== "undefined" ? localStorage.getItem(MCP_API_KEY_APP_STORAGE_KEY) || "" : ""));

  async function refreshDashboard(showLoader = false) {
    const authToken = token;
    const activeScope = scope;
    if (!authToken || !activeScope) return;

    if (showLoader) {
      setLoading(true);
    }

    try {
      const [graphResponse, timelineResponse, sessionResponse] = await Promise.all([
        fetchGraph(authToken, activeScope, graphScope),
        fetchTimeline(authToken, activeScope, graphScope),
        fetchSessions(authToken, activeScope),
      ]);
      setGraph(graphResponse);
      setTimeline(timelineResponse.items);
      setSessions(sessionResponse.items);
      setLastSyncedAt(
        new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }),
      );
      setError("");
    } catch {
      setError("Failed to synchronize dashboard streams.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!token || !scope) return;

    const authToken = token;
    const activeScope = scope;
    let cancelled = false;

    async function sync(showLoader = false) {
      if (cancelled) return;
      if (showLoader) {
        setLoading(true);
      }

      try {
        const [graphResponse, timelineResponse, sessionResponse] = await Promise.all([
          fetchGraph(authToken, activeScope, graphScope),
          fetchTimeline(authToken, activeScope, graphScope),
          fetchSessions(authToken, activeScope),
        ]);
        if (cancelled) return;
        setGraph(graphResponse);
        setTimeline(timelineResponse.items);
        setSessions(sessionResponse.items);
        setLastSyncedAt(
          new Date().toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }),
        );
        setError("");
      } catch {
        if (!cancelled) {
          setError("Failed to synchronize dashboard streams.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void sync(true);
    const intervalId = window.setInterval(() => {
      void sync(false);
    }, 8000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [graphScope, scope, token]);

  useEffect(() => {
    if (!token) {
      setMcpTools([]);
      return;
    }
    let cancelled = false;
    async function loadTools() {
      try {
        const tools = await fetchMcpTools(token);
        if (!cancelled) {
          setMcpTools(tools);
        }
      } catch {
        if (!cancelled) {
          setMcpTools([]);
        }
      }
    }
    void loadTools();
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const syncStoredMcpKey = () => {
      setStoredMcpApiKey(localStorage.getItem(MCP_API_KEY_STORAGE_KEY) || "");
      setStoredMcpApiKeyAppId(localStorage.getItem(MCP_API_KEY_APP_STORAGE_KEY) || "");
    };
    window.addEventListener("storage", syncStoredMcpKey);
    window.addEventListener("focus", syncStoredMcpKey);
    return () => {
      window.removeEventListener("storage", syncStoredMcpKey);
      window.removeEventListener("focus", syncStoredMcpKey);
    };
  }, []);

  function handleFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setSelectedFile(file);
    if (!sourceName.trim() || sourceName === "Manual knowledge drop") {
      setSourceName(file.name.replace(/\.[^.]+$/, ""));
    }
    showToast(`Selected ${file.name}. Parsing and chunking will happen on the server.`, "info");
    event.target.value = "";
  }

  function clearSelectedFile() {
    setSelectedFile(null);
  }

  async function handleIngestSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !scope) return;

    const resolvedSourceName = (sourceName || selectedFile?.name || "Manual knowledge drop").trim();
    const tags = parseTags(documentTags);

    if (!selectedFile && !documentText.trim()) {
      showToast("Paste text or select a document before ingesting.", "error");
      return;
    }

    setIsIngesting(true);
    try {
      const result = selectedFile
        ? await ingestDocumentFile(token, scope, {
            file: selectedFile,
            source_name: resolvedSourceName,
            tags,
            metadata: { upload_origin: "dashboard_file" },
          })
        : await ingestDocumentText(token, scope, {
            source_type: "manual_text",
            source_name: resolvedSourceName,
            content: documentText.trim(),
            tags,
            metadata: { upload_origin: "dashboard_text" },
          });

      await refreshDashboard();
      showToast(
        `Ingested ${result.chunks_received} chunk${result.chunks_received === 1 ? "" : "s"}${result.parser ? ` with ${result.parser}` : ""}.`,
        "success",
      );
      if (selectedFile) {
        clearSelectedFile();
      } else {
        setDocumentText("");
      }
    } catch (ingestionError) {
      const message = ingestionError instanceof Error ? ingestionError.message : "Document ingestion failed.";
      showToast(message, "error");
    } finally {
      setIsIngesting(false);
    }
  }

  async function handleReflect() {
    if (!token || !scope) return;

    setIsReflecting(true);
    try {
      const result = await reflectSession(token, scope, graphScope);
      await refreshDashboard();
      showToast(
        result.summary ? `${result.summary}${result.provider ? ` (${result.provider})` : ""}` : `Reflection completed${result.provider ? ` via ${result.provider}` : ""}.`,
        "success",
      );
    } catch {
      showToast("Reflection failed.", "error");
    } finally {
      setIsReflecting(false);
    }
  }

  async function handleRecall(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !scope) return;
    if (!recallQuery.trim()) {
      showToast("Enter a retrieval question first.", "error");
      return;
    }

    setIsRecalling(true);
    setRecallError("");
    try {
      const result = await recallMemories(token, scope, {
        query: recallQuery.trim(),
        top_k: recallTopK,
      });
      setRecallResult(result);
    } catch (recallFailure) {
      const message = recallFailure instanceof Error ? recallFailure.message : "Recall failed.";
      setRecallError(message);
      showToast(message, "error");
    } finally {
      setIsRecalling(false);
    }
  }

  async function handleCloseSession(sessionId: string) {
    if (!token) {
      return;
    }
    setLoading(true);
    try {
      await closeConversation(token, sessionId, "Closed from dashboard session explorer");
      const nextSession = sessions.find((item) => item.session_id !== sessionId && item.status !== "archived");
      onSessionChange(nextSession?.session_id ?? buildSessionId());
      await refreshDashboard();
      showToast("Chat session closed.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to close chat session.", "error");
    } finally {
      setLoading(false);
    }
  }

  const graphNodes: GraphNode[] = graph.nodes.map((node, index) => ({
    id: String(node.node_id || index),
    label: String(node.label || "Entity"),
    type: String(node.node_type || "Node"),
    x: 20 + ((index * 17) % 60),
    y: 28 + ((index * 13) % 50),
    size: 100 + ((index % 3) * 10),
    confidence: typeof node.confidence === "number" ? node.confidence : 0.6,
    supportCount: Array.isArray(node.evidence_ids)
      ? node.evidence_ids.length
      : typeof node.metadata?.support_count === "number"
        ? Number(node.metadata.support_count)
        : 0,
    excerpt:
      typeof node.metadata?.supporting_excerpt === "string"
        ? node.metadata.supporting_excerpt
        : typeof node.evidence_preview?.[0]?.excerpt === "string"
          ? node.evidence_preview[0].excerpt
          : "",
    memoryScope: String(node.memory_scope || "conversation"),
    scopeRef: node.scope_ref ?? null,
    conversationId: node.conversation_id ?? null,
    metadata: node.metadata ?? {},
    evidencePreview: mapGraphEvidencePreview(node.evidence_preview),
  }));

  const graphEdges: GraphEdge[] = graph.edges.map((edge) => ({
    from: String(edge.from_node),
    to: String(edge.to_node),
    label: String(edge.relation || "linked_to"),
    confidence: typeof edge.confidence === "number" ? edge.confidence : 0.55,
    supportCount: Array.isArray(edge.evidence_ids)
      ? edge.evidence_ids.length
      : typeof edge.metadata?.support_count === "number"
        ? Number(edge.metadata.support_count)
        : 0,
    excerpt:
      typeof edge.metadata?.supporting_excerpt === "string"
        ? edge.metadata.supporting_excerpt
        : typeof edge.evidence_preview?.[0]?.excerpt === "string"
          ? edge.evidence_preview[0].excerpt
          : "",
    metadata: edge.metadata ?? {},
    evidencePreview: mapGraphEvidencePreview(edge.evidence_preview),
  }));

  const filteredTimeline =
    historyFilter === "all" ? timeline : timeline.filter((item) => item.layer === historyFilter);
  const activeSession = sessions.find((item) => item.session_id === scope?.session_id);
  const directBackendBaseUrl = resolveDirectBackendBaseUrl();
  const mcpSseEndpoint = `${directBackendBaseUrl}/sse/`;
  const mcpSessionId = scope?.session_id ?? "default-session";
  const activeMcpApiKey =
    storedMcpApiKey && (!scope?.app_id || !storedMcpApiKeyAppId || storedMcpApiKeyAppId === scope.app_id)
      ? storedMcpApiKey
      : "";
  const mcpSseConfig = buildMcpSseServerBlock({
    endpoint: mcpSseEndpoint,
    apiKey: activeMcpApiKey || "<generate in Admin > API Access>",
    orgId: scope?.org_id ?? "<org_id>",
    appId: scope?.app_id ?? "<app_id>",
    userId: scope?.user_id ?? "<user_id>",
    sessionId: mcpSessionId,
  });
  const selectedScopeCounts = graph.scope_counts?.[graphScope] ?? { nodes: graph.nodes.length, edges: graph.edges.length };
  const visibleMcpTools = mcpTools.slice(0, 8);
  const graphScopeLabel =
    graphScope === "app" ? "Shared app memory" : graphScope === "user" ? "User memory" : "Conversation memory";
  const graphScopeDescription =
    graphScope === "app"
      ? "Durable knowledge promoted beyond a single session."
      : graphScope === "user"
        ? "User-specific memory that follows the same person across sessions."
        : "The event-first session graph built from the active conversation stream.";

  async function handleCopyMcpBlock() {
    try {
      await navigator.clipboard.writeText(mcpSseConfig);
      showToast("MCP SSE block copied.", "success");
    } catch {
      showToast("Clipboard access failed. Copy the block manually.", "error");
    }
  }

  return (
    <div className="animate-fade-in w-full" style={{ display: "grid", gap: "1.25rem" }}>
      <div className="glass-panel" style={{ padding: "1.15rem 1.25rem" }}>
        <div className="flex justify-between items-center" style={{ gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <p className="section-label" style={{ marginBottom: "0.35rem" }}>Graph-First Workspace</p>
            <h2 style={{ fontSize: "1.7rem", marginBottom: "0.2rem" }}>Knowledge Graph and Retrieval Control</h2>
            <p className="text-sm text-secondary">
              MemoryOS is centered on the grounded graph first, with session routing, retrieval inspection, history, ingestion, and MCP setup around it.
            </p>
          </div>
          <div className="flex items-center gap-2" style={{ flexWrap: "wrap" }}>
            <span className="badge badge-info">{sessions.length || 1} sessions</span>
            <span className="badge badge-success">{selectedScopeCounts.nodes} nodes</span>
            <span className="badge badge-warning">{selectedScopeCounts.edges} relations</span>
            <span className="badge badge-info">{graphScopeLabel}</span>
            <button className="btn btn-ghost" type="button" onClick={() => void refreshDashboard(true)}>
              <RefreshCw size={16} />
              Refresh
            </button>
            <button className="btn btn-primary" type="button" onClick={() => onSessionChange(buildSessionId())} disabled={!scope || !token}>
              <Plus size={16} />
              New Session
            </button>
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "1rem" }}>
        <div className="glass-panel" style={{ padding: "1rem 1.05rem" }}>
          <div className="flex items-center gap-2 mb-2 text-secondary text-sm">
            <Brain size={16} className="text-brand" />
            Active Session
          </div>
          <div style={{ fontSize: "1rem", fontWeight: 700 }}>
            {truncateText(activeSession?.title || scope?.session_id || "default-session", 28)}
          </div>
          <div className="text-xs text-secondary" style={{ marginTop: "0.2rem" }}>
            {truncateText(scope?.session_id ?? "default-session", 28)}
          </div>
          <div className="text-xs text-secondary" style={{ marginTop: "0.35rem" }}>{formatSessionActivity(activeSession?.last_activity_at)}</div>
        </div>
        <div className="glass-panel" style={{ padding: "1rem 1.05rem" }}>
          <div className="flex items-center gap-2 mb-2 text-secondary text-sm">
            <Database size={16} className="text-brand" />
            Memory Footprint
          </div>
          <div className="text-3xl">{activeSession?.memory_count ?? 0}</div>
          <div className="text-xs text-secondary" style={{ marginTop: "0.35rem" }}>Durable and session records in this run.</div>
        </div>
        <div className="glass-panel" style={{ padding: "1rem 1.05rem" }}>
          <div className="flex items-center gap-2 mb-2 text-secondary text-sm">
            <Network size={16} className="text-brand" />
            Graph Scope
          </div>
          <div style={{ fontSize: "1rem", fontWeight: 700 }}>{graphScopeLabel}</div>
          <div className="text-xs text-secondary" style={{ marginTop: "0.35rem" }}>{graphScopeDescription}</div>
        </div>
        <div className="glass-panel" style={{ padding: "1rem 1.05rem" }}>
          <div className="flex items-center gap-2 mb-2 text-secondary text-sm">
            <Sparkles size={16} className="text-brand" />
            Graph Health
          </div>
          <div style={{ fontSize: "1.1rem", fontWeight: 700 }}>
            {graph.summary.orphan_node_count} orphan{graph.summary.orphan_node_count === 1 ? "" : "s"} / {graph.summary.duplicate_label_count} duplicate{graph.summary.duplicate_label_count === 1 ? "" : "s"}
          </div>
          <div className="text-xs text-secondary" style={{ marginTop: "0.35rem" }}>
            {graph.summary.evidence_count} evidence links across {graph.summary.source_count} sources. {error || `Last sync ${lastSyncedAt || "--:--:--"}.`}
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.7fr) minmax(360px, 0.95fr)", gap: "1.25rem", minHeight: "760px" }}>
        <div className="glass-panel" style={{ padding: "1.1rem", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div className="flex justify-between items-center mb-4" style={{ gap: "1rem", flexWrap: "wrap" }}>
            <div>
              <h3 style={{ fontSize: "1.35rem", marginBottom: "0.2rem" }}>Knowledge Graph</h3>
              <p className="text-sm text-secondary">{graphScopeDescription}</p>
              <div className="flex items-center gap-2" style={{ flexWrap: "wrap", marginTop: "0.6rem" }}>
                {(["app", "user", "conversation"] as const).map((scopeOption) => (
                  <button
                    key={scopeOption}
                    className={`btn btn-ghost${graphScope === scopeOption ? " active" : ""}`}
                    type="button"
                    onClick={() => setGraphScope(scopeOption)}
                    style={{
                      padding: "0.45rem 0.75rem",
                      background: graphScope === scopeOption ? "rgba(39, 74, 135, 0.08)" : "transparent",
                      borderColor: graphScope === scopeOption ? "rgba(39, 74, 135, 0.2)" : "var(--border-subtle)",
                    }}
                  >
                    {scopeOption}
                  </button>
                ))}
                <span className="badge badge-info">{graph.summary.evidence_count} evidence links</span>
                <span className="badge badge-warning">{graph.summary.source_count} sources</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button className="btn btn-ghost" type="button" onClick={() => void refreshDashboard(true)}>
                <RefreshCw size={16} />
                Refresh
              </button>
              <button className="btn btn-primary" type="button" onClick={() => void handleReflect()} disabled={isReflecting || !scope || !token}>
                <WandSparkles size={16} />
                {isReflecting ? "Reflecting..." : "Run Reflection"}
              </button>
            </div>
          </div>

          <div
            style={{
              flex: 1,
              minHeight: 0,
              borderRadius: "20px",
              overflow: "hidden",
              border: "1px solid var(--border-subtle)",
              background: "#f8fbff",
            }}
          >
            {loading ? (
              <div className="flex items-center justify-center text-secondary" style={{ height: "100%" }}>
                Loading visible memory topology...
              </div>
            ) : (
              <GraphView nodes={graphNodes} edges={graphEdges} />
            )}
          </div>
        </div>

        <div style={{ display: "grid", gap: "1rem", minHeight: 0 }}>
          <div className="glass-panel" style={{ padding: "1rem" }}>
            <div className="section-label" style={{ marginBottom: "0.35rem" }}>Retrieval Inspector</div>
            <form onSubmit={(event) => void handleRecall(event)} style={{ display: "grid", gap: "0.8rem" }}>
              <input
                className="input-base"
                value={recallQuery}
                onChange={(event) => setRecallQuery(event.target.value)}
                placeholder="Ask a memory question for this session..."
              />
              <div className="grid" style={{ gridTemplateColumns: "120px minmax(0, 1fr)", gap: "0.75rem" }}>
                <select className="input-base" value={String(recallTopK)} onChange={(event) => setRecallTopK(Number(event.target.value))}>
                  <option value="3">Top 3</option>
                  <option value="5">Top 5</option>
                  <option value="8">Top 8</option>
                  <option value="10">Top 10</option>
                </select>
                <button className="btn btn-primary" type="submit" disabled={isRecalling || !scope || !token}>
                  <Search size={16} />
                  {isRecalling ? "Running..." : "Inspect Retrieval"}
                </button>
              </div>
            </form>
            {recallError ? <div className="text-sm text-danger" style={{ marginTop: "0.75rem" }}>{recallError}</div> : null}

            {recallResult ? (
              <div style={{ display: "grid", gap: "0.75rem", marginTop: "1rem" }}>
                <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
                  <span className="badge badge-info">{recallResult.trace.query_mode}</span>
                  {recallResult.trace.query_intent ? <span className="badge badge-info">{recallResult.trace.query_intent}</span> : null}
                  {recallResult.trace.grounding_policy ? <span className="badge badge-warning">{recallResult.trace.grounding_policy}</span> : null}
                  <span className="badge badge-success">{recallResult.trace.graph_matches} graph matches</span>
                  <span className="badge badge-warning">{recallResult.trace.graph_expansions} expansions</span>
                </div>
                {recallResult.trace.query_rewrite_applied && recallResult.trace.rewritten_query ? (
                  <div className="text-xs text-secondary">
                    Rewritten query: <strong style={{ color: "var(--text-primary)" }}>{recallResult.trace.rewritten_query}</strong>
                  </div>
                ) : null}
                <div className="text-xs text-secondary">{recallResult.trace.reasons[0] ?? "No retrieval rationale was returned."}</div>
                <div style={{ display: "grid", gap: "0.65rem", maxHeight: "260px", overflowY: "auto" }}>
                  {recallResult.items.map((item) => (
                    <div key={item.memory_id} style={{ padding: "0.85rem", borderRadius: "14px", background: "var(--bg-surface-alt)", border: "1px solid var(--border-subtle)", display: "grid", gap: "0.3rem" }}>
                      <div className="flex justify-between items-center" style={{ gap: "0.8rem", flexWrap: "wrap" }}>
                        <span className={`badge ${layerBadgeClass(item.layer)}`}>{item.layer}</span>
                        <span className="badge badge-info">score {recallScore(item.metadata)}</span>
                      </div>
                      <div style={{ fontWeight: 600 }}>{truncateText(item.content, 120)}</div>
                      <div className="text-xs text-secondary">{formatTimelineDate(item.created_at)}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-secondary" style={{ marginTop: "0.9rem" }}>
                Run recall here to inspect the full hybrid path: query rewrite when needed, embeddings recall, graph expansion, reranking, and the final grounded memory set.
              </p>
            )}
          </div>

          <div className="glass-panel" style={{ padding: "1rem" }}>
            <div className="section-label" style={{ marginBottom: "0.25rem" }}>Graph Ops</div>
            <h3 style={{ fontSize: "1.05rem", marginBottom: "0.75rem" }}>{graphScopeLabel}</h3>
            <div style={{ display: "grid", gap: "0.65rem" }}>
              <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
                <span className="badge badge-info">{graph.summary.node_count} nodes</span>
                <span className="badge badge-warning">{graph.summary.edge_count} relations</span>
                <span className="badge badge-info">{graph.summary.orphan_node_count} orphan nodes</span>
              </div>
              <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
                <span className="badge badge-warning">{graph.summary.duplicate_label_count} duplicate labels</span>
                <span className="badge badge-info">{graph.summary.ungrounded_node_count} ungrounded nodes</span>
                <span className="badge badge-info">{graph.summary.ungrounded_edge_count} ungrounded edges</span>
              </div>
              {graph.summary.source_names.length > 0 ? (
                <div>
                  <div className="text-xs text-secondary" style={{ marginBottom: "0.45rem" }}>Top evidence sources</div>
                  <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
                    {graph.summary.source_names.map((sourceName) => (
                      <span key={sourceName} className="badge badge-info">
                        {truncateText(sourceName, 28)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-secondary">
                  This graph slice does not have grounded evidence yet. Ingest durable sources or run reflection for the active scope.
                </p>
              )}
            </div>
          </div>

          <div className="glass-panel" style={{ padding: "1rem", minHeight: 0 }}>
            <div className="flex justify-between items-center mb-3" style={{ gap: "1rem" }}>
              <div>
                <div className="section-label" style={{ marginBottom: "0.25rem" }}>Session Explorer</div>
                <h3 style={{ fontSize: "1.05rem" }}>Recent sessions</h3>
              </div>
              <button className="btn btn-ghost" type="button" onClick={() => onSessionChange(buildSessionId())} style={{ padding: "0.55rem 0.75rem" }}>
                <Plus size={14} />
              </button>
            </div>
            <div style={{ display: "grid", gap: "0.7rem", maxHeight: "330px", overflowY: "auto", paddingRight: "0.15rem" }}>
              {(sessions.length > 0 ? sessions : [{ session_id: scope?.session_id ?? "default-session", event_count: 0, memory_count: 0 }]).map((session) => {
                const active = session.session_id === scope?.session_id;
                const closable = session.session_id.startsWith("conv-") && session.status !== "archived";
                return (
                  <article
                    key={session.session_id}
                    style={{
                      padding: "0.95rem",
                      borderRadius: "16px",
                      border: active ? "1px solid rgba(39, 74, 135, 0.2)" : "1px solid var(--border-subtle)",
                      background: active ? "rgba(39, 74, 135, 0.08)" : "var(--bg-surface-alt)",
                      display: "grid",
                      gap: "0.55rem",
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => onSessionChange(session.session_id)}
                      style={{
                        textAlign: "left",
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        display: "grid",
                        gap: "0.35rem",
                        color: "inherit",
                        padding: 0,
                      }}
                    >
                      <div className="flex justify-between" style={{ gap: "0.8rem", alignItems: "flex-start" }}>
                        <div>
                          <strong style={{ fontSize: "0.92rem", display: "block" }}>
                            {truncateText(session.title || session.session_id, 30)}
                          </strong>
                          <span className="text-xs text-secondary">{truncateText(session.session_id, 28)}</span>
                        </div>
                        <div className="trace-chip-row">
                          {session.status ? <span className={`badge ${sessionStatusBadge(session.status)}`}>{session.status}</span> : null}
                          {active ? <span className="badge badge-info">Active</span> : null}
                        </div>
                      </div>
                      <div className="text-xs text-secondary">{formatSessionActivity(session.last_activity_at)}</div>
                      <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
                        {session.agent_id ? <span className="badge badge-info">{truncateText(session.agent_id, 18)}</span> : null}
                        <span className="badge badge-info">{session.memory_count} mem</span>
                        <span className="badge badge-warning">{session.event_count} evt</span>
                      </div>
                    </button>
                    {closable ? (
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={() => void handleCloseSession(session.session_id)}
                        style={{ width: "100%" }}
                      >
                        Close chat session
                      </button>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.2fr) minmax(360px, 0.8fr)", gap: "1.25rem", alignItems: "start" }}>
        <div className="glass-panel" style={{ padding: "1rem", minHeight: 0 }}>
          <div className="flex justify-between items-center mb-4" style={{ gap: "1rem", flexWrap: "wrap" }}>
            <div>
              <h3 style={{ fontSize: "1.25rem", marginBottom: "0.2rem" }}>Session History</h3>
              <p className="text-sm text-secondary">Events and memories stay readable below the graph instead of competing with it.</p>
            </div>
            <select className="input-base" value={historyFilter} onChange={(event) => setHistoryFilter(event.target.value)} style={{ minWidth: "170px" }}>
              <option value="all">All Layers</option>
              <option value="session">Session</option>
              <option value="event">Event</option>
              <option value="long_term">Long Term</option>
              <option value="failure">Failure</option>
              <option value="resolution">Resolution</option>
              <option value="retrieval_hint">Retrieval Hint</option>
            </select>
          </div>
          <div style={{ border: "1px solid var(--border-subtle)", borderRadius: "18px", overflow: "hidden", background: "#fff" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "190px 130px minmax(0, 1fr)",
                gap: "1rem",
                padding: "0.95rem 1.1rem",
                background: "var(--bg-surface-alt)",
                borderBottom: "1px solid var(--border-subtle)",
                fontSize: "0.75rem",
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--text-secondary)",
              }}
            >
              <div>Date</div>
              <div>Layer</div>
              <div>Summary</div>
            </div>
            <div style={{ maxHeight: "460px", overflowY: "auto" }}>
              {loading ? (
                <div className="flex items-center justify-center text-secondary" style={{ minHeight: "240px" }}>
                  Loading timeline...
                </div>
              ) : filteredTimeline.length > 0 ? (
                filteredTimeline.map((item) => (
                  <div
                    key={item.item_id}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "190px 130px minmax(0, 1fr)",
                      gap: "1rem",
                      padding: "0.95rem 1.1rem",
                      borderBottom: "1px solid var(--border-subtle)",
                      alignItems: "start",
                    }}
                  >
                    <div className="text-sm">{formatTimelineDate(item.created_at)}</div>
                    <div>
                      <span className={`badge ${layerBadgeClass(item.layer)}`}>{item.layer}</span>
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{truncateText(item.content, 140)}</div>
                      <div className="flex gap-2" style={{ flexWrap: "wrap", marginBottom: "0.25rem" }}>
                        <span className="text-xs text-secondary">
                          {typeof item.metadata?.kind === "string" ? `Kind: ${item.metadata.kind}` : item.item_type}
                        </span>
                        {item.metadata?.graph_linked ? <span className="badge badge-warning">Linked to graph</span> : null}
                      </div>
                      {item.metadata?.graph_linked ? (
                        <div className="text-xs text-secondary">
                          {(typeof item.metadata.graph_node_count === "number" ? item.metadata.graph_node_count : 0)} nodes,{" "}
                          {(typeof item.metadata.graph_edge_count === "number" ? item.metadata.graph_edge_count : 0)} relations in the current {graphScope} graph.
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex items-center justify-center text-secondary" style={{ minHeight: "220px" }}>
                  No items match the selected layer filter.
                </div>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gap: "1rem" }}>
          <div className="glass-panel" style={{ padding: "1rem" }}>
            <div className="flex items-center gap-2 mb-3">
              <FileUp size={18} className="text-brand" />
              <div>
                <h3 style={{ fontSize: "1.05rem" }}>Ingestion</h3>
                <p className="text-sm text-secondary">Feed the graph with new documents or pasted text.</p>
              </div>
            </div>
            <form onSubmit={(event) => void handleIngestSubmit(event)} style={{ display: "grid", gap: "0.85rem" }}>
              <input className="input-base" value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="Source name" />
              <input className="input-base" value={documentTags} onChange={(event) => setDocumentTags(event.target.value)} placeholder="ops,runbook,internal" />
              <textarea
                className="input-base"
                value={documentText}
                onChange={(event) => setDocumentText(event.target.value)}
                placeholder="Paste document text here, or select a file below."
                style={{ minHeight: "160px", resize: "vertical" }}
              />
              <label className="btn btn-ghost" style={{ cursor: "pointer" }}>
                <FileUp size={16} />
                Select Document
                <input
                  type="file"
                  accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.rtf,.txt,.text,.md,.markdown,.json,.csv,.html,.htm,.xml,.yml,.yaml,.log,.py,.js,.ts,.tsx,.jsx,.css,.sql,.sh,text/*,application/*"
                  onChange={handleFileSelected}
                  style={{ display: "none" }}
                />
              </label>
              {selectedFile ? (
                <div className="text-sm text-secondary">
                  {selectedFile.name} | {formatBytes(selectedFile.size)}
                  <button type="button" className="btn btn-ghost" onClick={clearSelectedFile} style={{ marginTop: "0.6rem", width: "100%" }}>
                    Clear Selection
                  </button>
                </div>
              ) : null}
              <button className="btn btn-primary" type="submit" disabled={isIngesting || !token || !scope}>
                <Database size={16} />
                {isIngesting ? "Ingesting..." : selectedFile ? "Upload & Ingest" : "Ingest Text"}
              </button>
            </form>
          </div>

          <div className="glass-panel" style={{ padding: "1rem" }}>
            <div className="flex items-center gap-2 mb-3">
              <Settings2 size={18} className="text-brand" />
              <div>
                <h3 style={{ fontSize: "1.05rem" }}>MCP Config</h3>
                <p className="text-sm text-secondary">Real SSE client block for the current app scope. Generate an app API key in Admin and this snippet becomes copy-paste ready.</p>
              </div>
            </div>
            <div className="trace-chip-row" style={{ marginBottom: "0.75rem" }}>
              <span className="badge badge-info">{scope?.org_id ?? "org"}</span>
              <span className="badge badge-info">{scope?.app_id ?? "app"}</span>
              <span className="badge badge-warning">{truncateText(scope?.session_id ?? "session", 28)}</span>
              <span className={`badge ${activeMcpApiKey ? "badge-success" : "badge-warning"}`}>
                {activeMcpApiKey ? "API key loaded" : "API key missing"}
              </span>
            </div>
            <div className="flex justify-between items-center" style={{ gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
              <div className="text-sm text-secondary">
                Endpoint: <strong style={{ color: "var(--text-primary)" }}>{mcpSseEndpoint}</strong>
              </div>
              <button className="btn btn-ghost" type="button" onClick={() => void handleCopyMcpBlock()}>
                <Copy size={14} />
                Copy block
              </button>
            </div>
            {!activeMcpApiKey ? (
              <div className="text-sm text-secondary" style={{ marginBottom: "0.75rem" }}>
                No app API key is stored locally for this app yet. Open <strong style={{ color: "var(--text-primary)" }}>Admin &gt; API Access</strong>, generate one, and the dashboard will render the real block automatically.
              </div>
            ) : null}
            <pre
              style={{
                padding: "0.95rem",
                borderRadius: "16px",
                background: "#0f172a",
                color: "#dbeafe",
                fontSize: "0.8rem",
                overflowX: "auto",
              }}
            >
              {mcpSseConfig}
            </pre>
            <div style={{ marginTop: "0.9rem", display: "grid", gap: "0.7rem" }}>
              <div>
                <div className="section-label" style={{ marginBottom: "0.35rem" }}>Current Scope Headers</div>
                <div className="trace-chip-row">
                  <span className="badge badge-info">X-MemoryOS-Org-Id={scope?.org_id ?? "org"}</span>
                  <span className="badge badge-info">X-MemoryOS-App-Id={scope?.app_id ?? "app"}</span>
                  <span className="badge badge-info">X-MemoryOS-User-Id={truncateText(scope?.user_id ?? "user", 18)}</span>
                  <span className="badge badge-warning">X-MemoryOS-Session-Id={truncateText(mcpSessionId, 20)}</span>
                </div>
              </div>
              <div>
                <div className="section-label" style={{ marginBottom: "0.35rem" }}>Available MCP Tools</div>
                {visibleMcpTools.length > 0 ? (
                  <div style={{ display: "grid", gap: "0.55rem", maxHeight: "280px", overflowY: "auto", paddingRight: "0.15rem" }}>
                    {visibleMcpTools.map((tool) => (
                      <div
                        key={tool.name}
                        style={{
                          padding: "0.8rem",
                          borderRadius: "14px",
                          border: "1px solid var(--border-subtle)",
                          background: "var(--bg-surface-alt)",
                          display: "grid",
                          gap: "0.35rem",
                        }}
                      >
                        <div className="flex justify-between gap-2" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
                          <strong style={{ fontSize: "0.92rem" }}>{tool.name}</strong>
                          {tool.category ? <span className="badge badge-info">{tool.category}</span> : null}
                        </div>
                        <p className="text-sm text-secondary">{tool.description}</p>
                        {tool.required_fields && tool.required_fields.length > 0 ? (
                          <div className="text-xs text-secondary">
                            Required: <strong style={{ color: "var(--text-primary)" }}>{tool.required_fields.join(", ")}</strong>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-secondary">MCP tool metadata will appear here once the dashboard can reach the backend control plane.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
