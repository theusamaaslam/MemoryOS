import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Activity, AppWindow, Copy, Key, RefreshCw, Search, ShieldAlert, Sparkles, Users } from "lucide-react";
import { AnswerTraceDrawer } from "../components/AnswerTraceDrawer";
import { ConversationThread } from "../components/ConversationThread";
import { useToast } from "../components/ToastProvider";
import {
  classifyConversation,
  createApiKey,
  getConversationTrace,
  listApps,
  listMemoryCandidates,
  listOrgUsers,
  listTenantConversations,
  rebuildConversationGraph,
  type ApiKeyResult,
  type AppRecord,
  type ConversationSummary,
  type ConversationTraceResult,
  type CurrentUser,
  type MemoryCandidateListResult,
  type OrgUser,
  type Scope,
} from "../lib/api";

type AdminProps = {
  token: string | null;
  scope: Scope | null;
  currentUser: CurrentUser | null;
};

type AdminTab = "overview" | "conversations" | "users" | "apps" | "keys";

const MCP_API_KEY_STORAGE_KEY = "memoryos_mcp_api_key";
const MCP_API_KEY_APP_STORAGE_KEY = "memoryos_mcp_api_key_app_id";
const MCP_API_KEY_NAME_STORAGE_KEY = "memoryos_mcp_api_key_name";

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

function formatDate(value?: string | null) {
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

function statusBadge(status: string) {
  if (status === "resolved") {
    return "badge-success";
  }
  if (status === "active") {
    return "badge-info";
  }
  return "badge-warning";
}

function riskBadge(risk: string) {
  if (risk === "high") {
    return "badge-danger";
  }
  if (risk === "elevated") {
    return "badge-warning";
  }
  return "badge-info";
}

export function Admin({ token, scope, currentUser }: AdminProps) {
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = useState<AdminTab>("overview");
  const [apps, setApps] = useState<AppRecord[]>([]);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [candidateSnapshot, setCandidateSnapshot] = useState<MemoryCandidateListResult>({ items: [] });
  const [selectedConversationId, setSelectedConversationId] = useState("");
  const [selectedTrace, setSelectedTrace] = useState<ConversationTraceResult | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [appFilter, setAppFilter] = useState("all");
  const [userFilter, setUserFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeAction, setActiveAction] = useState<"classify" | "rebuild" | null>(null);
  const [apiKeyName, setApiKeyName] = useState("MemoryOS MCP SSE");
  const [apiKeyAppId, setApiKeyAppId] = useState("");
  const [generatedApiKey, setGeneratedApiKey] = useState<ApiKeyResult | null>(() => {
    if (typeof window === "undefined") {
      return null;
    }
    const apiKey = localStorage.getItem(MCP_API_KEY_STORAGE_KEY) || "";
    if (!apiKey) {
      return null;
    }
    return {
      key_id: "browser-stored",
      name: localStorage.getItem(MCP_API_KEY_NAME_STORAGE_KEY) || "Browser stored MCP key",
      app_id: localStorage.getItem(MCP_API_KEY_APP_STORAGE_KEY) || "",
      api_key: apiKey,
    };
  });
  const [isCreatingApiKey, setIsCreatingApiKey] = useState(false);
  const deferredSearch = useDeferredValue(searchValue);
  const isAdmin = currentUser?.role === "owner" || currentUser?.role === "admin";

  async function loadTrace(conversationId: string) {
    if (!token) {
      return;
    }
    const trace = await getConversationTrace(token, conversationId);
    setSelectedTrace(trace);
    setSelectedConversationId(conversationId);
  }

  async function refreshAdminData(preferredConversationId?: string) {
    if (!token || !scope) {
      return;
    }

    const [appRows, userRows, conversationRows, candidateRows] = await Promise.all([
      listApps(token),
      listOrgUsers(token),
      listTenantConversations(token, scope.org_id, {
        app_id: appFilter !== "all" ? appFilter : undefined,
        user_id: userFilter !== "all" ? userFilter : undefined,
        limit: 180,
      }),
      listMemoryCandidates(token, {
        org_id: scope.org_id,
        limit: 180,
      }),
    ]);

    setApps(appRows);
    setApiKeyAppId((current) => current || appRows[0]?.app_id || "");
    setUsers(userRows);
    setConversations(conversationRows.items);
    setCandidateSnapshot(candidateRows);

    const nextConversationId =
      preferredConversationId
      || (conversationRows.items.some((item) => item.conversation_id === selectedConversationId) ? selectedConversationId : conversationRows.items[0]?.conversation_id)
      || "";

    if (nextConversationId) {
      await loadTrace(nextConversationId);
    } else {
      setSelectedConversationId("");
      setSelectedTrace(null);
    }
  }

  useEffect(() => {
    if (!token || !scope || !isAdmin) {
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    async function bootstrap() {
      setIsLoading(true);
      try {
        await refreshAdminData();
      } catch (error) {
        if (!cancelled) {
          showToast(error instanceof Error ? error.message : "Failed to load admin control room.", "error");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [token, scope?.org_id, appFilter, userFilter, isAdmin]);

  const filteredConversations = useMemo(() => {
    const normalizedSearch = deferredSearch.trim().toLowerCase();
    return conversations.filter((conversation) => {
      if (statusFilter !== "all" && conversation.status !== statusFilter) {
        return false;
      }
      if (typeFilter !== "all" && conversation.label.conversation_type !== typeFilter) {
        return false;
      }
      if (riskFilter !== "all" && conversation.label.risk_level !== riskFilter) {
        return false;
      }
      if (!normalizedSearch) {
        return true;
      }
      const haystack = [
        conversation.title,
        conversation.summary,
        conversation.agent_id,
        conversation.user_id,
        conversation.label.topic,
      ].join(" ").toLowerCase();
      return haystack.includes(normalizedSearch);
    });
  }, [conversations, deferredSearch, riskFilter, statusFilter, typeFilter]);

  const pendingCandidates = candidateSnapshot.items.filter((item) => item.status === "pending").length;
  const elevatedConversations = conversations.filter((item) => item.label.risk_level !== "normal").length;
  const resolvedConversations = conversations.filter((item) => item.status === "resolved").length;
  const activeKeyAppId = generatedApiKey?.app_id || apiKeyAppId || apps[0]?.app_id || scope?.app_id || "memoryos-dashboard";
  const mcpSseEndpoint = `${resolveDirectBackendBaseUrl()}/sse/`;
  const mcpSseConfig = buildMcpSseServerBlock({
    endpoint: mcpSseEndpoint,
    apiKey: generatedApiKey?.api_key || "<generate API key>",
    orgId: scope?.org_id ?? currentUser?.org_id ?? "<org_id>",
    appId: activeKeyAppId,
    userId: currentUser?.user_id ?? scope?.user_id ?? "<user_id>",
    sessionId: "default-session",
  });

  function persistBrowserMcpKey(result: ApiKeyResult) {
    if (typeof window === "undefined") {
      return;
    }
    localStorage.setItem(MCP_API_KEY_STORAGE_KEY, result.api_key);
    localStorage.setItem(MCP_API_KEY_APP_STORAGE_KEY, result.app_id);
    localStorage.setItem(MCP_API_KEY_NAME_STORAGE_KEY, result.name);
  }

  async function copyText(value: string, successMessage: string) {
    try {
      await navigator.clipboard.writeText(value);
      showToast(successMessage, "success");
    } catch {
      showToast("Clipboard access failed. Copy it manually.", "error");
    }
  }

  async function handleRefresh() {
    setIsRefreshing(true);
    try {
      await refreshAdminData(selectedConversationId);
      showToast("Admin control room synchronized.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to refresh admin data.", "error");
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleClassify() {
    if (!token || !selectedConversationId) {
      return;
    }
    setActiveAction("classify");
    try {
      await classifyConversation(token, selectedConversationId);
      await refreshAdminData(selectedConversationId);
      showToast("Conversation labels refreshed.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to refresh conversation labels.", "error");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleRebuildGraph() {
    if (!token || !selectedConversationId) {
      return;
    }
    setActiveAction("rebuild");
    try {
      const result = await rebuildConversationGraph(token, selectedConversationId);
      await loadTrace(selectedConversationId);
      showToast(result.summary || "Graph update appended.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to append graph update.", "error");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleCreateApiKey() {
    if (!token || !scope || !apiKeyAppId.trim()) {
      showToast("Choose an app before creating an API key.", "error");
      return;
    }
    setIsCreatingApiKey(true);
    try {
      const result = await createApiKey(token, {
        org_id: scope.org_id,
        app_id: apiKeyAppId.trim(),
        name: apiKeyName.trim() || "MemoryOS MCP SSE",
      });
      setGeneratedApiKey(result);
      persistBrowserMcpKey(result);
      showToast("API key created and stored locally for the dashboard MCP block.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to create API key.", "error");
    } finally {
      setIsCreatingApiKey(false);
    }
  }

  function handleClearStoredApiKey() {
    if (typeof window === "undefined") {
      return;
    }
    localStorage.removeItem(MCP_API_KEY_STORAGE_KEY);
    localStorage.removeItem(MCP_API_KEY_APP_STORAGE_KEY);
    localStorage.removeItem(MCP_API_KEY_NAME_STORAGE_KEY);
    setGeneratedApiKey(null);
    showToast("Stored MCP API key removed from this browser.", "success");
  }

  if (!isAdmin) {
    return (
      <div className="page-stack animate-fade-in">
        <section className="glass-panel thread-empty-state" style={{ minHeight: "320px" }}>
          <ShieldAlert size={46} className="text-brand" />
          <h3>Admin role required</h3>
          <p>This control room is available to tenant owners and admins because it exposes tenant-wide conversations, review queues, and access management.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="animate-fade-in w-full h-full flex flex-col">
      <div className="tabs-container mb-6">
        <button className={`tab flex items-center gap-2 ${activeTab === "overview" ? "active" : ""}`} onClick={() => setActiveTab("overview")}>
          <Activity size={16} /> Overview
        </button>
        <button className={`tab flex items-center gap-2 ${activeTab === "conversations" ? "active" : ""}`} onClick={() => setActiveTab("conversations")}>
          <Sparkles size={16} /> Conversations
        </button>
        <button className={`tab flex items-center gap-2 ${activeTab === "users" ? "active" : ""}`} onClick={() => setActiveTab("users")}>
          <Users size={16} /> Directory
        </button>
        <button className={`tab flex items-center gap-2 ${activeTab === "apps" ? "active" : ""}`} onClick={() => setActiveTab("apps")}>
          <AppWindow size={16} /> Applications
        </button>
        <button className={`tab flex items-center gap-2 ${activeTab === "keys" ? "active" : ""}`} onClick={() => setActiveTab("keys")}>
          <Key size={16} /> API Access
        </button>
        <button className="btn btn-ghost" type="button" onClick={() => void handleRefresh()} disabled={isRefreshing || isLoading} style={{ marginLeft: "auto" }}>
          <RefreshCw size={16} />
          {isRefreshing ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {activeTab === "overview" && (
        <div className="page-stack">
          <div className="grid grid-cols-3 gap-6">
            <div className="card glass-panel flex flex-col justify-between p-6">
              <p className="text-secondary text-sm font-medium uppercase tracking-wider">Tenant Conversations</p>
              <h2 className="text-3xl mt-2 text-primary">{conversations.length}</h2>
              <div className="mt-4 text-xs text-secondary">{resolvedConversations} resolved threads currently visible</div>
            </div>
            <div className="card glass-panel flex flex-col justify-between p-6">
              <p className="text-secondary text-sm font-medium uppercase tracking-wider">Pending Memory Review</p>
              <h2 className="text-3xl mt-2 text-brand">{pendingCandidates}</h2>
              <div className="mt-4 text-xs text-secondary">Candidates waiting for an explicit admin decision</div>
            </div>
            <div className="card glass-panel flex flex-col justify-between p-6">
              <p className="text-secondary text-sm font-medium uppercase tracking-wider">Elevated Risk Threads</p>
              <h2 className="text-3xl mt-2" style={{ color: "var(--warning)" }}>{elevatedConversations}</h2>
              <div className="mt-4 text-xs text-secondary">Conversations labeled as elevated or high risk</div>
            </div>
          </div>

          <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(340px, 0.9fr)", gap: "1rem" }}>
            <section className="glass-panel" style={{ padding: "1.1rem" }}>
              <div className="conversation-list-header">
                <div>
                  <p className="section-label" style={{ marginBottom: "0.25rem" }}>Recent Tenant Activity</p>
                  <h3 style={{ fontSize: "1.15rem" }}>Latest conversations</h3>
                </div>
              </div>
              <div className="conversation-card-list">
                {conversations.slice(0, 6).map((conversation) => (
                  <button
                    key={conversation.conversation_id}
                    type="button"
                    className="conversation-card-button"
                    onClick={() => {
                      setActiveTab("conversations");
                      void loadTrace(conversation.conversation_id);
                    }}
                  >
                    <div className="flex justify-between gap-2" style={{ alignItems: "flex-start" }}>
                      <strong>{conversation.title}</strong>
                      <span className={`badge ${statusBadge(conversation.status)}`}>{conversation.status}</span>
                    </div>
                    <p className="text-sm text-secondary">{conversation.summary || "No summary yet."}</p>
                    <div className="trace-chip-row">
                      <span className="badge badge-info">{conversation.label.conversation_type}</span>
                      <span className={`badge ${riskBadge(conversation.label.risk_level)}`}>{conversation.label.risk_level}</span>
                    </div>
                    <div className="text-xs text-secondary">{formatDate(conversation.last_message_at ?? conversation.created_at)}</div>
                  </button>
                ))}
              </div>
            </section>

            <section className="glass-panel" style={{ padding: "1.1rem" }}>
              <div className="conversation-list-header">
                <div>
                  <p className="section-label" style={{ marginBottom: "0.25rem" }}>Operations Snapshot</p>
                  <h3 style={{ fontSize: "1.15rem" }}>Tenant surface area</h3>
                </div>
              </div>
              <div className="trace-list">
                <div className="trace-list-item">
                  <strong>{apps.length} registered applications</strong>
                  <div className="text-xs text-secondary" style={{ marginTop: "0.3rem" }}>Apps share memory boundaries and conversation ownership.</div>
                </div>
                <div className="trace-list-item">
                  <strong>{users.length} organization users</strong>
                  <div className="text-xs text-secondary" style={{ marginTop: "0.3rem" }}>These roles govern who can inspect or approve memory.</div>
                </div>
                <div className="trace-list-item">
                  <strong>{candidateSnapshot.items.length} candidate memories</strong>
                  <div className="text-xs text-secondary" style={{ marginTop: "0.3rem" }}>Reviewable reflection outputs currently tracked for this tenant.</div>
                </div>
              </div>
            </section>
          </div>
        </div>
      )}

      {activeTab === "conversations" && (
        <div className="page-stack">
          <section className="glass-panel" style={{ padding: "1.1rem" }}>
            <div className="conversation-filter-grid">
              <div className="conversation-search-input">
                <Search size={16} className="text-secondary" />
                <input
                  value={searchValue}
                  onChange={(event) => setSearchValue(event.target.value)}
                  placeholder="Search title, user, agent, topic, or summary"
                />
              </div>
              <select className="input-base" value={appFilter} onChange={(event) => setAppFilter(event.target.value)}>
                <option value="all">All apps</option>
                {apps.map((app) => (
                  <option key={app.app_id} value={app.app_id}>{app.name} ({app.app_id})</option>
                ))}
              </select>
              <select className="input-base" value={userFilter} onChange={(event) => setUserFilter(event.target.value)}>
                <option value="all">All users</option>
                {users.map((user) => (
                  <option key={user.user_id} value={user.user_id}>{user.full_name || user.email}</option>
                ))}
              </select>
              <select className="input-base" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                <option value="all">All types</option>
                <option value="general">General</option>
                <option value="billing">Billing</option>
                <option value="support">Support</option>
                <option value="implementation">Implementation</option>
                <option value="research">Research</option>
              </select>
              <select className="input-base" value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}>
                <option value="all">All risk</option>
                <option value="normal">Normal</option>
                <option value="elevated">Elevated</option>
                <option value="high">High</option>
              </select>
              <select className="input-base" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="resolved">Resolved</option>
              </select>
            </div>
          </section>

          <div className="conversation-layout">
            <aside className="glass-panel conversation-list-panel">
              <div className="conversation-list-header">
                <div>
                  <p className="section-label" style={{ marginBottom: "0.25rem" }}>Tenant Conversations</p>
                  <h3 style={{ fontSize: "1.15rem" }}>Filtered threads</h3>
                </div>
                <span className="badge badge-info">{filteredConversations.length} visible</span>
              </div>
              <div className="conversation-card-list">
                {isLoading ? (
                  <div className="trace-empty">Loading tenant conversations...</div>
                ) : filteredConversations.length > 0 ? (
                  filteredConversations.map((conversation) => (
                    <button
                      key={conversation.conversation_id}
                      type="button"
                      className={`conversation-card-button ${conversation.conversation_id === selectedConversationId ? "active" : ""}`}
                      onClick={() => void loadTrace(conversation.conversation_id)}
                    >
                      <div className="flex justify-between gap-2" style={{ alignItems: "flex-start" }}>
                        <div>
                          <strong style={{ display: "block", marginBottom: "0.2rem" }}>{conversation.title}</strong>
                          <span className="text-xs text-secondary">{conversation.user_id}</span>
                        </div>
                        <span className={`badge ${statusBadge(conversation.status)}`}>{conversation.status}</span>
                      </div>
                      <p className="text-sm text-secondary">{conversation.summary || "No summary yet."}</p>
                      <div className="trace-chip-row">
                        <span className="badge badge-info">{conversation.label.conversation_type}</span>
                        <span className={`badge ${riskBadge(conversation.label.risk_level)}`}>{conversation.label.risk_level}</span>
                        <span className="badge badge-warning">{conversation.message_count} msgs</span>
                      </div>
                      <div className="text-xs text-secondary">{formatDate(conversation.last_message_at ?? conversation.created_at)}</div>
                    </button>
                  ))
                ) : (
                  <div className="thread-empty-state" style={{ minHeight: "260px" }}>
                    <ShieldAlert size={42} className="text-brand" />
                    <h3>No matching conversations</h3>
                    <p>Adjust the app, user, type, risk, or status filters to inspect another slice of tenant activity.</p>
                  </div>
                )}
              </div>
            </aside>

            <section className="glass-panel conversation-detail-panel">
              <div className="conversation-detail-header">
                <div>
                  <p className="section-label" style={{ marginBottom: "0.25rem" }}>Conversation Detail</p>
                  <h2 style={{ fontSize: "1.4rem", marginBottom: "0.25rem" }}>
                    {selectedTrace?.conversation.title ?? "Select a tenant conversation"}
                  </h2>
                  <p className="text-sm text-secondary">
                    {selectedTrace?.conversation
                      ? `${selectedTrace.conversation.agent_id} | ${selectedTrace.conversation.user_id} | ${selectedTrace.traces.length} traces | ${selectedTrace.tool_invocations.length} tools`
                      : "Choose a thread from the left to inspect its full messages, audits, and tool activity."}
                  </p>
                </div>
                <div className="conversation-action-row">
                  <button className="btn btn-ghost" type="button" onClick={() => void handleClassify()} disabled={!selectedConversationId || activeAction !== null}>
                    {activeAction === "classify" ? "Classifying..." : "Refresh labels"}
                  </button>
                  <button className="btn btn-ghost" type="button" onClick={() => void handleRebuildGraph()} disabled={!selectedConversationId || activeAction !== null}>
                    {activeAction === "rebuild" ? "Appending..." : "Append graph update"}
                  </button>
                  <button className="btn btn-primary" type="button" onClick={() => setTraceOpen(true)} disabled={!selectedTrace}>
                    Open trace
                  </button>
                </div>
              </div>

              {selectedTrace?.conversation ? (
                <div className="conversation-label-strip">
                  <span className={`badge ${statusBadge(selectedTrace.conversation.status)}`}>{selectedTrace.conversation.status}</span>
                  <span className="badge badge-info">{selectedTrace.conversation.label.conversation_type}</span>
                  <span className={`badge ${riskBadge(selectedTrace.conversation.label.risk_level)}`}>{selectedTrace.conversation.label.risk_level}</span>
                  <span className="badge badge-warning">{selectedTrace.conversation.label.topic}</span>
                  <span className="badge badge-info">{selectedTrace.conversation.label.outcome}</span>
                </div>
              ) : null}

              <div className="conversation-thread-shell">
                <ConversationThread
                  conversation={selectedTrace?.conversation ?? null}
                  emptyBody="Select a conversation from the tenant list to inspect messages, citations, and traceability details."
                />
              </div>
            </section>
          </div>
        </div>
      )}

      {activeTab === "users" && (
        <div className="glass-panel" style={{ padding: "0", overflow: "hidden" }}>
          <div className="flex justify-between items-center p-6" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
            <div>
              <h3 style={{ fontSize: "1.2rem", marginBottom: "0.25rem" }}>Workspace directory</h3>
              <p className="text-sm text-secondary">Users who can inspect, operate, or review tenant memory.</p>
            </div>
          </div>
          <div className="data-table">
            <div className="data-table-head">
              <span>User</span>
              <span>Role</span>
              <span>Email</span>
              <span>Id</span>
            </div>
            {users.map((user) => (
              <div key={user.user_id} className="data-table-row">
                <span>{user.full_name || "Unnamed user"}</span>
                <span><span className="badge badge-info">{user.role}</span></span>
                <span>{user.email}</span>
                <span className="text-secondary">{user.user_id}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === "apps" && (
        <div className="glass-panel" style={{ padding: "0", overflow: "hidden" }}>
          <div className="flex justify-between items-center p-6" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
            <div>
              <h3 style={{ fontSize: "1.2rem", marginBottom: "0.25rem" }}>Applications</h3>
              <p className="text-sm text-secondary">App boundaries determine shared memory scope and MCP/API routing.</p>
            </div>
          </div>
          <div className="data-table">
            <div className="data-table-head" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
              <span>Name</span>
              <span>App Id</span>
              <span>Organization</span>
            </div>
            {apps.map((app) => (
              <div key={app.app_id} className="data-table-row" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
                <span>{app.name}</span>
                <span>{app.app_id}</span>
                <span className="text-secondary">{app.org_id}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === "keys" && (
        <div className="page-stack">
          <div className="grid" style={{ gridTemplateColumns: "minmax(340px, 0.9fr) minmax(0, 1.1fr)", gap: "1rem" }}>
            <section className="glass-panel" style={{ padding: "1.1rem", display: "grid", gap: "1rem" }}>
              <div>
                <p className="section-label" style={{ marginBottom: "0.25rem" }}>API Access</p>
                <h3 style={{ fontSize: "1.2rem", marginBottom: "0.25rem" }}>Generate MCP keys</h3>
                <p className="text-sm text-secondary">
                  API keys are app-scoped and are meant for MCP clients, automations, and server-to-server calls through the <code>X-API-Key</code> header.
                </p>
              </div>

              <div style={{ display: "grid", gap: "0.8rem" }}>
                <label style={{ display: "grid", gap: "0.35rem" }}>
                  <span className="text-sm text-secondary">Application</span>
                  <select className="input-base" value={apiKeyAppId} onChange={(event) => setApiKeyAppId(event.target.value)}>
                    <option value="">Select an app</option>
                    {apps.map((app) => (
                      <option key={app.app_id} value={app.app_id}>
                        {app.name} ({app.app_id})
                      </option>
                    ))}
                  </select>
                </label>

                <label style={{ display: "grid", gap: "0.35rem" }}>
                  <span className="text-sm text-secondary">Key name</span>
                  <input className="input-base" value={apiKeyName} onChange={(event) => setApiKeyName(event.target.value)} placeholder="MemoryOS MCP SSE" />
                </label>

                <button className="btn btn-primary" type="button" onClick={() => void handleCreateApiKey()} disabled={isCreatingApiKey || !apiKeyAppId}>
                  <Key size={16} />
                  {isCreatingApiKey ? "Generating..." : "Generate API key"}
                </button>
              </div>

              <div className="trace-list">
                <div className="trace-list-item">
                  <strong>Visible once</strong>
                  <div className="text-xs text-secondary" style={{ marginTop: "0.3rem" }}>
                    The raw secret only comes back when the key is created, so the dashboard stores the latest generated MCP key in this browser for reuse.
                  </div>
                </div>
                <div className="trace-list-item">
                  <strong>App scoped</strong>
                  <div className="text-xs text-secondary" style={{ marginTop: "0.3rem" }}>
                    A key is limited to one app, which keeps MCP clients and automations inside the correct shared-memory boundary.
                  </div>
                </div>
              </div>
            </section>

            <section className="glass-panel" style={{ padding: "1.1rem", display: "grid", gap: "0.9rem" }}>
              <div className="flex justify-between items-start" style={{ gap: "1rem", flexWrap: "wrap" }}>
                <div>
                  <p className="section-label" style={{ marginBottom: "0.25rem" }}>Ready-to-paste SSE Block</p>
                  <h3 style={{ fontSize: "1.15rem", marginBottom: "0.25rem" }}>{generatedApiKey ? generatedApiKey.name : "Generate a key to unlock the real block"}</h3>
                  <p className="text-sm text-secondary">
                    This is the exact MCP SSE snippet the dashboard home page also uses once a browser-stored API key is available.
                  </p>
                </div>
                {generatedApiKey ? <span className="badge badge-success">{generatedApiKey.app_id}</span> : <span className="badge badge-warning">No key yet</span>}
              </div>

              {generatedApiKey ? (
                <div style={{ display: "grid", gap: "0.75rem" }}>
                  <div className="trace-chip-row">
                    <span className="badge badge-info">key id {generatedApiKey.key_id === "browser-stored" ? "browser-stored" : generatedApiKey.key_id}</span>
                    <span className="badge badge-info">{generatedApiKey.app_id}</span>
                  </div>
                  <div style={{ display: "grid", gap: "0.55rem" }}>
                    <div className="text-sm text-secondary">API key</div>
                    <pre
                      style={{
                        padding: "0.85rem",
                        borderRadius: "16px",
                        background: "#0f172a",
                        color: "#dbeafe",
                        fontSize: "0.8rem",
                        overflowX: "auto",
                      }}
                    >
                      {generatedApiKey.api_key}
                    </pre>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-secondary">
                  Create an app key on the left and the generated secret plus the full SSE block will appear here.
                </p>
              )}

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

              <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
                <button className="btn btn-ghost" type="button" onClick={() => void copyText(mcpSseConfig, "MCP SSE block copied.")}>
                  <Copy size={14} />
                  Copy SSE block
                </button>
                {generatedApiKey ? (
                  <button className="btn btn-ghost" type="button" onClick={() => void copyText(generatedApiKey.api_key, "API key copied.")}>
                    <Copy size={14} />
                    Copy API key
                  </button>
                ) : null}
                {generatedApiKey ? (
                  <button className="btn btn-ghost" type="button" onClick={handleClearStoredApiKey}>
                    Clear stored key
                  </button>
                ) : null}
              </div>
            </section>
          </div>
        </div>
      )}

      <AnswerTraceDrawer
        open={traceOpen}
        title={selectedTrace?.conversation.title ?? "Tenant conversation trace"}
        traceBundle={selectedTrace}
        onClose={() => setTraceOpen(false)}
      />
    </div>
  );
}
