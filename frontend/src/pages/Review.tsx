import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Eye, GitBranchPlus, RefreshCw, Search, ShieldAlert, Sparkles, XCircle } from "lucide-react";
import { AnswerTraceDrawer } from "../components/AnswerTraceDrawer";
import { useToast } from "../components/ToastProvider";
import {
  approveMemoryCandidate,
  getConversationTrace,
  listApps,
  listMemoryCandidates,
  rebuildConversationGraph,
  rejectMemoryCandidate,
  type AppRecord,
  type ConversationTraceResult,
  type CurrentUser,
  type MemoryCandidate,
  type Scope,
} from "../lib/api";

type ReviewProps = {
  token: string | null;
  scope: Scope | null;
  currentUser: CurrentUser | null;
};

function formatDate(value: string) {
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusBadge(status: string) {
  if (status === "approved" || status === "auto_promoted") {
    return "badge-success";
  }
  if (status === "rejected") {
    return "badge-danger";
  }
  return "badge-warning";
}

function scopeBadge(scope: string) {
  if (scope === "app") {
    return "badge-info";
  }
  if (scope === "user") {
    return "badge-success";
  }
  return "badge-warning";
}

export function Review({ token, scope, currentUser }: ReviewProps) {
  const { showToast } = useToast();
  const [candidates, setCandidates] = useState<MemoryCandidate[]>([]);
  const [apps, setApps] = useState<AppRecord[]>([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [selectedCandidate, setSelectedCandidate] = useState<MemoryCandidate | null>(null);
  const [traceBundle, setTraceBundle] = useState<ConversationTraceResult | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [appFilter, setAppFilter] = useState("all");
  const [searchValue, setSearchValue] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeAction, setActiveAction] = useState<"approve" | "reject" | "rebuild" | null>(null);
  const deferredSearch = useDeferredValue(searchValue);
  const isAdmin = currentUser?.role === "owner" || currentUser?.role === "admin";

  async function loadCandidateTrace(candidate: MemoryCandidate | null) {
    if (!token || !candidate) {
      setTraceBundle(null);
      return;
    }
    try {
      const payload = await getConversationTrace(token, candidate.conversation_id);
      setTraceBundle(payload);
    } catch (error) {
      setTraceBundle(null);
      showToast(error instanceof Error ? error.message : "Failed to load supporting conversation trace.", "error");
    }
  }

  async function refreshCandidates(preferredCandidateId?: string) {
    if (!token || !scope) {
      return;
    }

    const [candidateResponse, appResponse] = await Promise.all([
      listMemoryCandidates(token, {
        org_id: scope.org_id,
        app_id: appFilter !== "all" ? appFilter : undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        limit: 180,
      }),
      isAdmin ? listApps(token).catch(() => []) : Promise.resolve([]),
    ]);

    setCandidates(candidateResponse.items);
    setApps(appResponse);

    const nextCandidate =
      candidateResponse.items.find((item) => item.candidate_id === preferredCandidateId)
      || candidateResponse.items.find((item) => item.candidate_id === selectedCandidateId)
      || candidateResponse.items[0]
      || null;

    setSelectedCandidate(nextCandidate);
    setSelectedCandidateId(nextCandidate?.candidate_id ?? "");
    setReviewReason("");
    await loadCandidateTrace(nextCandidate);
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
        await refreshCandidates();
      } catch (error) {
        if (!cancelled) {
          showToast(error instanceof Error ? error.message : "Failed to load review inbox.", "error");
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
  }, [token, scope?.org_id, appFilter, statusFilter, isAdmin]);

  const filteredCandidates = useMemo(() => {
    const normalizedSearch = deferredSearch.trim().toLowerCase();
    return candidates.filter((candidate) => {
      if (!normalizedSearch) {
        return true;
      }
      const haystack = [
        candidate.content,
        candidate.layer,
        candidate.memory_scope,
        candidate.app_id,
        candidate.metadata?.kind,
      ].join(" ").toLowerCase();
      return haystack.includes(normalizedSearch);
    });
  }, [candidates, deferredSearch]);

  async function handleSelectCandidate(candidate: MemoryCandidate) {
    setSelectedCandidate(candidate);
    setSelectedCandidateId(candidate.candidate_id);
    setReviewReason("");
    await loadCandidateTrace(candidate);
  }

  async function handleRefresh() {
    setIsRefreshing(true);
    try {
      await refreshCandidates(selectedCandidateId);
      showToast("Memory review inbox synchronized.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to refresh memory review inbox.", "error");
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleApprove() {
    if (!token || !selectedCandidate) {
      return;
    }
    setActiveAction("approve");
    try {
      await approveMemoryCandidate(token, selectedCandidate.candidate_id, reviewReason.trim() || undefined);
      await refreshCandidates(selectedCandidate.candidate_id);
      showToast("Memory candidate approved and promoted.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to approve memory candidate.", "error");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleReject() {
    if (!token || !selectedCandidate) {
      return;
    }
    setActiveAction("reject");
    try {
      await rejectMemoryCandidate(token, selectedCandidate.candidate_id, reviewReason.trim() || undefined);
      await refreshCandidates(selectedCandidate.candidate_id);
      showToast("Memory candidate rejected.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to reject memory candidate.", "error");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleRebuildGraph() {
    if (!token || !selectedCandidate) {
      return;
    }
    setActiveAction("rebuild");
    try {
      const result = await rebuildConversationGraph(token, selectedCandidate.conversation_id);
      await loadCandidateTrace(selectedCandidate);
      showToast(result.summary || "Graph update appended.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Failed to append graph update.", "error");
    } finally {
      setActiveAction(null);
    }
  }

  if (!isAdmin) {
    return (
      <div className="page-stack animate-fade-in">
        <section className="glass-panel thread-empty-state" style={{ minHeight: "320px" }}>
          <ShieldAlert size={46} className="text-brand" />
          <h3>Admin role required</h3>
          <p>The memory review inbox is for tenant admins and owners because it changes what the agent learns across users and sessions.</p>
        </section>
      </div>
    );
  }

  const pendingCount = candidates.filter((item) => item.status === "pending").length;
  const autoPromotedCount = candidates.filter((item) => item.status === "auto_promoted").length;

  return (
    <div className="page-stack animate-fade-in">
      <section className="glass-panel page-hero-card">
        <div>
          <p className="section-label" style={{ marginBottom: "0.35rem" }}>Memory Review Inbox</p>
          <h2 style={{ fontSize: "1.8rem", marginBottom: "0.3rem" }}>Control what the agent learns</h2>
          <p className="text-sm text-secondary">
            Review reflection output before it becomes durable truth, inspect the supporting conversation, and repair graph quality from the same workflow.
          </p>
        </div>
        <div className="hero-metrics">
          <div className="hero-metric-card">
            <span className="trace-metric-label">Pending review</span>
            <strong>{pendingCount}</strong>
          </div>
          <div className="hero-metric-card">
            <span className="trace-metric-label">Auto-promoted</span>
            <strong>{autoPromotedCount}</strong>
          </div>
          <div className="hero-metric-card">
            <span className="trace-metric-label">Current org</span>
            <strong>{scope?.org_id ?? "n/a"}</strong>
          </div>
        </div>
      </section>

      <section className="glass-panel" style={{ padding: "1.1rem" }}>
        <div className="conversation-filter-grid">
          <div className="conversation-search-input">
            <Search size={16} className="text-secondary" />
            <input
              value={searchValue}
              onChange={(event) => setSearchValue(event.target.value)}
              placeholder="Search candidate text, kind, or app"
            />
          </div>
          <select className="input-base" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">All statuses</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="auto_promoted">Auto-promoted</option>
          </select>
          <select className="input-base" value={appFilter} onChange={(event) => setAppFilter(event.target.value)}>
            <option value="all">All apps</option>
            {apps.map((app) => (
              <option key={app.app_id} value={app.app_id}>{app.name} ({app.app_id})</option>
            ))}
          </select>
          <button className="btn btn-ghost" type="button" onClick={() => void handleRefresh()} disabled={isRefreshing || isLoading}>
            <RefreshCw size={16} />
            {isRefreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </section>

      <div className="conversation-layout">
        <aside className="glass-panel conversation-list-panel">
          <div className="conversation-list-header">
            <div>
              <p className="section-label" style={{ marginBottom: "0.25rem" }}>Candidate Queue</p>
              <h3 style={{ fontSize: "1.15rem" }}>Review items</h3>
            </div>
            <span className="badge badge-info">{filteredCandidates.length} items</span>
          </div>
          <div className="conversation-card-list">
            {isLoading ? (
              <div className="trace-empty">Loading memory candidates...</div>
            ) : filteredCandidates.length > 0 ? (
              filteredCandidates.map((candidate) => {
                const isActive = candidate.candidate_id === selectedCandidateId;
                return (
                  <button
                    key={candidate.candidate_id}
                    type="button"
                    className={`conversation-card-button ${isActive ? "active" : ""}`}
                    onClick={() => void handleSelectCandidate(candidate)}
                  >
                    <div className="flex justify-between gap-2" style={{ alignItems: "flex-start" }}>
                      <div>
                        <strong style={{ display: "block", marginBottom: "0.2rem" }}>{candidate.metadata?.kind ? String(candidate.metadata.kind) : candidate.layer}</strong>
                        <span className="text-xs text-secondary">{candidate.app_id}</span>
                      </div>
                      <span className={`badge ${statusBadge(candidate.status)}`}>{candidate.status}</span>
                    </div>
                    <p className="text-sm text-secondary">{candidate.content}</p>
                    <div className="trace-chip-row">
                      <span className={`badge ${scopeBadge(candidate.memory_scope)}`}>{candidate.memory_scope}</span>
                      <span className="badge badge-info">{candidate.layer}</span>
                      <span className="badge badge-warning">confidence {candidate.confidence.toFixed(2)}</span>
                    </div>
                    <div className="text-xs text-secondary">{formatDate(candidate.updated_at)}</div>
                  </button>
                );
              })
            ) : (
              <div className="thread-empty-state" style={{ minHeight: "260px" }}>
                <Sparkles size={42} className="text-brand" />
                <h3>No candidates match these filters</h3>
                <p>Run more conversations or reflection jobs to generate fresh reviewable memory proposals.</p>
              </div>
            )}
          </div>
        </aside>

        <section className="glass-panel conversation-detail-panel">
          <div className="conversation-detail-header">
            <div>
              <p className="section-label" style={{ marginBottom: "0.25rem" }}>Candidate Detail</p>
              <h2 style={{ fontSize: "1.4rem", marginBottom: "0.25rem" }}>
                {selectedCandidate ? "Inspect and decide" : "Select a candidate"}
              </h2>
              <p className="text-sm text-secondary">
                {selectedCandidate
                  ? `Conversation ${selectedCandidate.conversation_id} | ${selectedCandidate.app_id} | updated ${formatDate(selectedCandidate.updated_at)}`
                  : "Choose a memory candidate from the inbox to inspect its evidence, scope, and linked trace."}
              </p>
            </div>
            <div className="conversation-action-row">
              <button className="btn btn-ghost" type="button" onClick={() => setTraceOpen(true)} disabled={!traceBundle}>
                <Eye size={16} />
                Open trace
              </button>
              <button className="btn btn-ghost" type="button" onClick={() => void handleRebuildGraph()} disabled={!selectedCandidate || activeAction === "rebuild"}>
                <GitBranchPlus size={16} />
                {activeAction === "rebuild" ? "Appending..." : "Append graph update"}
              </button>
            </div>
          </div>

          {selectedCandidate ? (
            <div className="detail-stack">
              <div className="conversation-label-strip">
                <span className={`badge ${statusBadge(selectedCandidate.status)}`}>{selectedCandidate.status}</span>
                <span className={`badge ${scopeBadge(selectedCandidate.memory_scope)}`}>{selectedCandidate.memory_scope}</span>
                <span className="badge badge-info">{selectedCandidate.layer}</span>
                <span className="badge badge-warning">confidence {selectedCandidate.confidence.toFixed(2)}</span>
              </div>

              <article className="trace-card">
                <div className="trace-card-header">
                  <ShieldAlert size={16} className="text-brand" />
                  <span>Candidate content</span>
                </div>
                <div className="trace-query-block">{selectedCandidate.content}</div>
                <div className="trace-chip-row">
                  <span className="badge badge-info">{String(selectedCandidate.metadata?.kind ?? "candidate")}</span>
                  {selectedCandidate.metadata?.generated_by ? (
                    <span className="badge badge-success">generated by {String(selectedCandidate.metadata.generated_by)}</span>
                  ) : null}
                </div>
              </article>

              <article className="trace-card">
                <div className="trace-card-header">
                  <Sparkles size={16} className="text-brand" />
                  <span>Why this review matters</span>
                </div>
                <div className="trace-metric-grid">
                  <div className="hero-metric-card">
                    <span className="trace-metric-label">Evidence ids</span>
                    <strong>{selectedCandidate.source_memory_ids.length}</strong>
                  </div>
                  <div className="hero-metric-card">
                    <span className="trace-metric-label">Retrieval traces</span>
                    <strong>{traceBundle?.traces.length ?? 0}</strong>
                  </div>
                  <div className="hero-metric-card">
                    <span className="trace-metric-label">Answer audits</span>
                    <strong>{traceBundle?.audits.length ?? 0}</strong>
                  </div>
                  <div className="hero-metric-card">
                    <span className="trace-metric-label">Tool invocations</span>
                    <strong>{traceBundle?.tool_invocations.length ?? 0}</strong>
                  </div>
                </div>
                <p className="text-sm text-secondary">
                  Approving promotes this candidate into durable memory for the chosen scope. Rejecting blocks noisy reflection output. Opening the trace shows the source conversation, retrieval trace, and audit trail behind this proposal.
                </p>
              </article>

              <div className="trace-grid">
                <article className="trace-card">
                  <div className="trace-card-header">
                    <CheckCircle2 size={16} className="text-brand" />
                    <span>Supporting evidence ids</span>
                  </div>
                  {selectedCandidate.source_memory_ids.length > 0 ? (
                    <div className="trace-chip-row">
                      {selectedCandidate.source_memory_ids.map((memoryId) => (
                        <span key={memoryId} className="badge badge-info">{memoryId}</span>
                      ))}
                    </div>
                  ) : (
                    <div className="trace-empty">No evidence ids were attached to this candidate.</div>
                  )}
                </article>

                <article className="trace-card">
                  <div className="trace-card-header">
                    <Sparkles size={16} className="text-brand" />
                    <span>Linked conversation</span>
                  </div>
                  {traceBundle?.conversation ? (
                    <div className="trace-list">
                      <div className="trace-list-item">
                        <strong>{traceBundle.conversation.title}</strong>
                        <div className="text-xs text-secondary" style={{ marginTop: "0.3rem" }}>
                          {traceBundle.conversation.label.conversation_type} | {traceBundle.conversation.label.topic} | {traceBundle.conversation.label.risk_level}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="trace-empty">Conversation trace not loaded yet.</div>
                  )}
                </article>
              </div>

              <article className="trace-card">
                <div className="trace-card-header">
                  <Search size={16} className="text-brand" />
                  <span>Review notes</span>
                </div>
                <textarea
                  className="input-base"
                  style={{ minHeight: "120px", resize: "vertical" }}
                  value={reviewReason}
                  onChange={(event) => setReviewReason(event.target.value)}
                  placeholder="Optional reviewer note explaining why this should be approved, rejected, or re-scoped later."
                />
                <div className="conversation-action-row" style={{ marginTop: "1rem" }}>
                  <button className="btn btn-primary" type="button" onClick={() => void handleApprove()} disabled={activeAction !== null}>
                    <CheckCircle2 size={16} />
                    {activeAction === "approve" ? "Approving..." : "Approve"}
                  </button>
                  <button className="btn btn-ghost" type="button" onClick={() => void handleReject()} disabled={activeAction !== null}>
                    <XCircle size={16} />
                    {activeAction === "reject" ? "Rejecting..." : "Reject"}
                  </button>
                </div>
              </article>
            </div>
          ) : (
            <div className="thread-empty-state" style={{ minHeight: "320px" }}>
              <ShieldAlert size={46} className="text-brand" />
              <h3>No candidate selected</h3>
              <p>Choose a candidate from the queue to review its content, evidence ids, and linked conversation trace.</p>
            </div>
          )}
        </section>
      </div>

      <AnswerTraceDrawer
        open={traceOpen}
        title={traceBundle?.conversation.title ?? selectedCandidate?.content ?? "Memory candidate trace"}
        traceBundle={traceBundle}
        onClose={() => setTraceOpen(false)}
      />
    </div>
  );
}
