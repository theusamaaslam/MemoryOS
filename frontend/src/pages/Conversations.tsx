import { useDeferredValue, useEffect, useMemo, useState, type FormEvent } from "react";
import { Compass, MessageSquareText, Plus, RefreshCw, Search, Sparkles, WandSparkles } from "lucide-react";
import { AnswerTraceDrawer } from "../components/AnswerTraceDrawer";
import { ConversationThread } from "../components/ConversationThread";
import { useToast } from "../components/ToastProvider";
import {
  classifyConversation,
  closeConversation,
  explainConversation,
  getConversation,
  listConversations,
  sendConversationMessage,
  startConversation,
  type Conversation,
  type CurrentUser,
  type ExplainAnswerResult,
  type Scope,
  type ConversationSummary,
} from "../lib/api";

type ConversationsProps = {
  scope: Scope | null;
  token: string | null;
  currentUser: CurrentUser | null;
  onSessionChange: (sessionId: string) => void;
};

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

function truncateText(value: string, limit: number) {
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit - 3)}...`;
}

function citationCount(conversation: Conversation | null) {
  if (!conversation) {
    return 0;
  }
  return conversation.turns.reduce((total, turn) => (
    total + turn.messages.reduce((messageTotal, message) => (
      messageTotal + (message.role === "assistant" ? message.citations.length : 0)
    ), 0)
  ), 0);
}

export function Conversations({ scope, token, currentUser, onSessionChange }: ConversationsProps) {
  const { showToast } = useToast();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string>("");
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);
  const [searchValue, setSearchValue] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState("all");
  const [agentId, setAgentId] = useState("memory-assistant");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [draftMessage, setDraftMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isClassifying, setIsClassifying] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [explanation, setExplanation] = useState<ExplainAnswerResult | null>(null);
  const deferredSearch = useDeferredValue(searchValue);

  async function loadConversation(conversationId: string) {
    if (!token) {
      return;
    }
    const detail = await getConversation(token, conversationId);
    setSelectedConversation(detail);
    setSelectedConversationId(detail.conversation_id);
    onSessionChange(detail.conversation_id);
  }

  async function refreshConversations(preferredConversationId?: string) {
    if (!token || !scope) {
      return;
    }

    const response = await listConversations(token, { app_id: scope.app_id, limit: 120 });
    setConversations(response.items);

    const nextConversationId =
      preferredConversationId
      || (response.items.some((item) => item.conversation_id === selectedConversationId) ? selectedConversationId : response.items[0]?.conversation_id)
      || "";

    if (nextConversationId) {
      await loadConversation(nextConversationId);
    } else {
      setSelectedConversation(null);
      setSelectedConversationId("");
    }
  }

  useEffect(() => {
    if (!token || !scope) {
      return;
    }

    let cancelled = false;

    async function bootstrap() {
      setIsLoading(true);
      try {
        await refreshConversations();
      } catch (error) {
        if (!cancelled) {
          showToast(error instanceof Error ? error.message : "Failed to load conversations.", "error");
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
  }, [token, scope?.app_id, scope?.user_id]);

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
        conversation.label.topic,
        conversation.label.conversation_type,
      ].join(" ").toLowerCase();
      return haystack.includes(normalizedSearch);
    });
  }, [conversations, deferredSearch, riskFilter, statusFilter, typeFilter]);

  async function handleCreateConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !scope) {
      return;
    }
    if (!agentId.trim()) {
      showToast("Agent id is required to start a conversation.", "error");
      return;
    }

    setIsCreating(true);
    try {
      const created = await startConversation(token, agentId.trim(), {
        app_id: scope.app_id,
        user_id: currentUser?.user_id ?? scope.user_id,
        title: title.trim() || undefined,
        description: description.trim() || undefined,
        metadata: { created_from: "dashboard_conversations" },
      });
      setTitle("");
      setDescription("");
      setSelectedConversation(created);
      setSelectedConversationId(created.conversation_id);
      onSessionChange(created.conversation_id);
      await refreshConversations(created.conversation_id);
      showToast(`Conversation ${created.conversation_id} is ready.`, "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to start conversation.", "error");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleSendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedConversationId) {
      return;
    }
    if (!draftMessage.trim()) {
      showToast("Type a message before sending.", "error");
      return;
    }

    setIsSending(true);
    try {
      const result = await sendConversationMessage(token, selectedConversationId, {
        content: draftMessage.trim(),
        top_k: 6,
        metadata: { sent_from: "dashboard_conversations" },
      });
      setDraftMessage("");
      await refreshConversations(selectedConversationId);
      if (traceOpen) {
        const tracePayload = await explainConversation(token, selectedConversationId);
        setExplanation(tracePayload);
      } else {
        setExplanation(null);
      }
      showToast(
        result.supported
          ? "Answer recorded with supporting evidence."
          : result.abstained
            ? "The agent abstained because support was weak."
            : "Answer recorded, but the audit marked it as needing review.",
        result.supported ? "success" : "info",
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to send message.", "error");
    } finally {
      setIsSending(false);
    }
  }

  async function handleRefresh() {
    setIsRefreshing(true);
    try {
      await refreshConversations();
      showToast("Conversation list synchronized.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to refresh conversations.", "error");
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleClassify() {
    if (!token || !selectedConversationId) {
      return;
    }
    setIsClassifying(true);
    try {
      await classifyConversation(token, selectedConversationId);
      await refreshConversations(selectedConversationId);
      showToast("Conversation labels refreshed.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to classify conversation.", "error");
    } finally {
      setIsClassifying(false);
    }
  }

  async function handleCloseConversation() {
    if (!token || !selectedConversationId) {
      return;
    }
    setIsRefreshing(true);
    try {
      const closed = await closeConversation(token, selectedConversationId, "Closed from dashboard runtime");
      setSelectedConversation(closed);
      await refreshConversations(closed.conversation_id);
      showToast("Conversation archived and removed from the open runtime queue.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to close conversation.", "error");
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleOpenTrace() {
    if (!token || !selectedConversationId) {
      return;
    }
    setTraceOpen(true);
    setTraceLoading(true);
    try {
      const payload = await explainConversation(token, selectedConversationId);
      setExplanation(payload);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to load answer trace.", "error");
    } finally {
      setTraceLoading(false);
    }
  }

  return (
    <div className="page-stack animate-fade-in">
      <section className="glass-panel page-hero-card">
        <div>
          <p className="section-label" style={{ marginBottom: "0.35rem" }}>Conversations</p>
          <h2 style={{ fontSize: "1.8rem", marginBottom: "0.3rem" }}>Operational conversation runtime</h2>
          <p className="text-sm text-secondary">
            Start agent conversations, inspect the full thread, and open the evidence-backed answer trace behind each response.
          </p>
        </div>
        <div className="hero-metrics">
          <div className="hero-metric-card">
            <span className="trace-metric-label">Visible conversations</span>
            <strong>{conversations.length}</strong>
          </div>
          <div className="hero-metric-card">
            <span className="trace-metric-label">Selected citations</span>
            <strong>{citationCount(selectedConversation)}</strong>
          </div>
          <div className="hero-metric-card">
            <span className="trace-metric-label">Current app</span>
            <strong>{scope?.app_id ?? "n/a"}</strong>
          </div>
        </div>
      </section>

      <section className="glass-panel" style={{ padding: "1.1rem" }}>
        <div className="flex justify-between items-center gap-4" style={{ flexWrap: "wrap", marginBottom: "1rem" }}>
          <div>
            <p className="section-label" style={{ marginBottom: "0.25rem" }}>New Conversation</p>
            <h3 style={{ fontSize: "1.1rem" }}>Start a server-owned conversation thread</h3>
          </div>
          <button className="btn btn-ghost" type="button" onClick={() => void handleRefresh()} disabled={isRefreshing || isLoading}>
            <RefreshCw size={16} />
            {isRefreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
        <form onSubmit={(event) => void handleCreateConversation(event)} className="conversation-create-grid">
          <input
            className="input-base"
            value={agentId}
            onChange={(event) => setAgentId(event.target.value)}
            placeholder="Agent id"
          />
          <input
            className="input-base"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Conversation title"
          />
          <input
            className="input-base"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Optional description for this conversation"
          />
          <button className="btn btn-primary" type="submit" disabled={isCreating || !scope || !token}>
            <Plus size={16} />
            {isCreating ? "Starting..." : "Start conversation"}
          </button>
        </form>
      </section>

      <div className="conversation-layout">
        <aside className="glass-panel conversation-list-panel">
          <div className="conversation-list-header">
            <div>
              <p className="section-label" style={{ marginBottom: "0.25rem" }}>Thread Explorer</p>
              <h3 style={{ fontSize: "1.15rem" }}>Your conversations</h3>
            </div>
            <span className="badge badge-info">{filteredConversations.length} visible</span>
          </div>

          <div className="conversation-filter-grid">
            <div className="conversation-search-input">
              <Search size={16} className="text-secondary" />
              <input
                value={searchValue}
                onChange={(event) => setSearchValue(event.target.value)}
                placeholder="Search title, topic, or summary"
              />
            </div>
            <select className="input-base" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="resolved">Resolved</option>
              <option value="archived">Archived</option>
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
              <option value="all">All risk levels</option>
              <option value="normal">Normal</option>
              <option value="elevated">Elevated</option>
              <option value="high">High</option>
            </select>
          </div>

          <div className="conversation-card-list">
            {isLoading ? (
              <div className="trace-empty">Loading conversations...</div>
            ) : filteredConversations.length > 0 ? (
              filteredConversations.map((conversation) => {
                const isActive = conversation.conversation_id === selectedConversationId;
                return (
                  <button
                    key={conversation.conversation_id}
                    type="button"
                    className={`conversation-card-button ${isActive ? "active" : ""}`}
                    onClick={() => void loadConversation(conversation.conversation_id)}
                  >
                    <div className="flex justify-between gap-2" style={{ alignItems: "flex-start" }}>
                      <div>
                        <strong style={{ display: "block", marginBottom: "0.2rem" }}>{truncateText(conversation.title, 48)}</strong>
                        <span className="text-xs text-secondary">{conversation.agent_id}</span>
                      </div>
                      <span className={`badge ${statusBadge(conversation.status)}`}>{conversation.status}</span>
                    </div>
                    <p className="text-sm text-secondary">{truncateText(conversation.summary || "No summary yet.", 112)}</p>
                    <div className="trace-chip-row">
                      <span className="badge badge-info">{conversation.label.conversation_type}</span>
                      <span className={`badge ${riskBadge(conversation.label.risk_level)}`}>{conversation.label.risk_level}</span>
                      <span className="badge badge-warning">{conversation.message_count} msgs</span>
                    </div>
                    <div className="text-xs text-secondary">{formatDate(conversation.last_message_at ?? conversation.created_at)}</div>
                  </button>
                );
              })
            ) : (
              <div className="thread-empty-state" style={{ minHeight: "260px" }}>
                <Compass size={42} className="text-brand" />
                <h3>No conversations yet</h3>
                <p>Create the first server-owned conversation to start capturing traces, audits, and reflection-ready history.</p>
              </div>
            )}
          </div>
        </aside>

        <section className="glass-panel conversation-detail-panel">
          <div className="conversation-detail-header">
            <div>
              <p className="section-label" style={{ marginBottom: "0.25rem" }}>Selected Conversation</p>
              <h2 style={{ fontSize: "1.45rem", marginBottom: "0.25rem" }}>
                {selectedConversation?.title ?? "Choose a conversation"}
              </h2>
              <p className="text-sm text-secondary">
                {selectedConversation
                  ? `${selectedConversation.agent_id} | ${selectedConversation.app_id} | last activity ${formatDate(selectedConversation.last_message_at ?? selectedConversation.created_at)}`
                  : "Once you select a thread, you can inspect the full history and open its answer trace."}
              </p>
            </div>
            <div className="conversation-action-row">
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => void handleCloseConversation()}
                disabled={!selectedConversationId || selectedConversation?.status === "archived" || isRefreshing}
              >
                {selectedConversation?.status === "archived" ? "Closed" : isRefreshing ? "Closing..." : "Close thread"}
              </button>
              <button className="btn btn-ghost" type="button" onClick={() => void handleClassify()} disabled={!selectedConversationId || isClassifying}>
                <WandSparkles size={16} />
                {isClassifying ? "Classifying..." : "Refresh labels"}
              </button>
              <button className="btn btn-primary" type="button" onClick={() => void handleOpenTrace()} disabled={!selectedConversationId || traceLoading}>
                <Sparkles size={16} />
                {traceLoading ? "Loading trace..." : "Open answer trace"}
              </button>
            </div>
          </div>

          {selectedConversation ? (
            <>
              <div className="conversation-label-strip">
                <span className={`badge ${statusBadge(selectedConversation.status)}`}>{selectedConversation.status}</span>
                <span className="badge badge-info">{selectedConversation.label.conversation_type}</span>
                <span className={`badge ${riskBadge(selectedConversation.label.risk_level)}`}>{selectedConversation.label.risk_level}</span>
                <span className="badge badge-warning">{selectedConversation.label.outcome}</span>
                <span className="badge badge-info">{selectedConversation.label.topic}</span>
                {selectedConversation.label.hallucination_suspected ? <span className="badge badge-danger">hallucination suspected</span> : null}
              </div>

              <div className="conversation-detail-metrics">
                <div className="hero-metric-card">
                  <span className="trace-metric-label">Messages</span>
                  <strong>{selectedConversation.message_count}</strong>
                </div>
                <div className="hero-metric-card">
                  <span className="trace-metric-label">Turns</span>
                  <strong>{selectedConversation.turns.length}</strong>
                </div>
                <div className="hero-metric-card">
                  <span className="trace-metric-label">Memory impact</span>
                  <strong>{selectedConversation.label.memory_impact_score.toFixed(2)}</strong>
                </div>
              </div>
            </>
          ) : null}

          <div className="conversation-thread-shell">
            <ConversationThread conversation={selectedConversation} />
          </div>

          <form onSubmit={(event) => void handleSendMessage(event)} className="conversation-compose-bar">
            <div className="conversation-search-input" style={{ flex: 1 }}>
              <MessageSquareText size={16} className="text-secondary" />
              <input
                value={draftMessage}
                onChange={(event) => setDraftMessage(event.target.value)}
                placeholder={
                  selectedConversation
                    ? selectedConversation.status === "archived"
                      ? "This conversation is closed. Start a new thread to continue."
                      : "Send a message through the conversation runtime"
                    : "Select or create a conversation first"
                }
                disabled={!selectedConversationId || isSending || selectedConversation?.status === "archived"}
              />
            </div>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={!selectedConversationId || isSending || selectedConversation?.status === "archived"}
            >
              {isSending ? "Sending..." : "Send"}
            </button>
          </form>
        </section>
      </div>

      <AnswerTraceDrawer
        open={traceOpen}
        title={selectedConversation?.title ?? "Conversation trace"}
        explanation={explanation}
        onClose={() => setTraceOpen(false)}
      />
    </div>
  );
}
