import { Activity, Bot, Braces, CheckCircle2, Clock3, Search, ShieldAlert, X } from "lucide-react";
import type { ConversationTraceResult, ExplainAnswerResult } from "../lib/api";

type AnswerTraceDrawerProps = {
  open: boolean;
  title: string;
  onClose: () => void;
  explanation?: ExplainAnswerResult | null;
  traceBundle?: ConversationTraceResult | null;
};

function formatDate(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function prettyValue(value: unknown) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  return String(value);
}

export function AnswerTraceDrawer({ open, title, onClose, explanation, traceBundle }: AnswerTraceDrawerProps) {
  if (!open) {
    return null;
  }

  const primaryTrace = traceBundle?.traces?.[0];
  const primaryAudit = traceBundle?.audits?.[0];
  const query = explanation?.query ?? primaryTrace?.query ?? "";
  const items = explanation?.items ?? primaryTrace?.items ?? [];
  const trace = explanation?.trace ?? primaryTrace?.trace ?? {};
  const audit = explanation?.audit ?? (primaryAudit ? {
    audit_id: primaryAudit.audit_id,
    provider: primaryAudit.provider,
    model_name: primaryAudit.model_name,
    latency_ms: primaryAudit.latency_ms,
    confidence: primaryAudit.confidence,
    supported: primaryAudit.supported,
    abstained: primaryAudit.abstained,
    metadata: primaryAudit.metadata,
  } : {});
  const traceRecord = trace as Record<string, unknown>;
  const auditRecord = audit as Record<string, unknown>;
  const rankingFactors = Array.isArray(traceRecord.ranking_factors) ? traceRecord.ranking_factors.map((factor) => String(factor)) : [];
  const reasons = Array.isArray(traceRecord.reasons) ? traceRecord.reasons.map((reason) => String(reason)) : [];
  const toolInvocations = traceBundle?.tool_invocations ?? [];
  const historicalTraces = traceBundle?.traces?.slice(1) ?? [];
  const historicalAudits = traceBundle?.audits?.slice(1) ?? [];
  const auditSupported = Boolean(auditRecord.supported);
  const auditAbstained = Boolean(auditRecord.abstained);
  const auditMetadata = typeof auditRecord.metadata === "object" && auditRecord.metadata ? auditRecord.metadata : null;

  return (
    <div className="trace-drawer-overlay animate-fade-in" role="dialog" aria-modal="true">
      <button className="trace-drawer-backdrop" type="button" onClick={onClose} aria-label="Close trace drawer" />
      <aside className="trace-drawer-panel">
        <div className="trace-drawer-header">
          <div>
            <p className="section-label" style={{ marginBottom: "0.25rem" }}>Answer Trace</p>
            <h2 style={{ fontSize: "1.45rem", marginBottom: "0.2rem" }}>{title}</h2>
            <p className="text-sm text-secondary">
              Inspect retrieved evidence, ranking signals, audits, and tool activity behind the latest answer.
            </p>
          </div>
          <button className="btn btn-ghost" type="button" onClick={onClose}>
            <X size={16} />
            Close
          </button>
        </div>

        <div className="trace-drawer-body">
          <section className="trace-card">
            <div className="trace-card-header">
              <Search size={16} className="text-brand" />
              <span>Latest query</span>
            </div>
            <div className="trace-query-block">{query || "No query was recorded for this conversation yet."}</div>
          </section>

          <section className="trace-grid">
            <div className="trace-card">
              <div className="trace-card-header">
                <Activity size={16} className="text-brand" />
                <span>Retrieval summary</span>
              </div>
              <div className="trace-metric-grid">
                <div>
                  <span className="trace-metric-label">Mode</span>
                  <strong>{prettyValue(traceRecord.query_mode)}</strong>
                </div>
                <div>
                  <span className="trace-metric-label">Graph matches</span>
                  <strong>{prettyValue(traceRecord.graph_matches)}</strong>
                </div>
                <div>
                  <span className="trace-metric-label">Expansions</span>
                  <strong>{prettyValue(traceRecord.graph_expansions)}</strong>
                </div>
                <div>
                  <span className="trace-metric-label">Hint matches</span>
                  <strong>{prettyValue(traceRecord.retrieval_hint_matches)}</strong>
                </div>
              </div>
              {rankingFactors.length > 0 ? (
                <div className="trace-chip-row">
                  {rankingFactors.map((factor) => (
                    <span key={factor} className="badge badge-info">{factor}</span>
                  ))}
                </div>
              ) : null}
              {reasons.length > 0 ? (
                <div className="trace-list">
                  {reasons.map((reason) => (
                    <div key={reason} className="trace-list-item">{reason}</div>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="trace-card">
              <div className="trace-card-header">
                <ShieldAlert size={16} className="text-brand" />
                <span>Answer audit</span>
              </div>
              <div className="trace-metric-grid">
                <div>
                  <span className="trace-metric-label">Provider</span>
                  <strong>{prettyValue(auditRecord.provider)}</strong>
                </div>
                <div>
                  <span className="trace-metric-label">Model</span>
                  <strong>{prettyValue(auditRecord.model_name)}</strong>
                </div>
                <div>
                  <span className="trace-metric-label">Latency</span>
                  <strong>{prettyValue(auditRecord.latency_ms)} ms</strong>
                </div>
                <div>
                  <span className="trace-metric-label">Confidence</span>
                  <strong>{prettyValue(auditRecord.confidence)}</strong>
                </div>
              </div>
              <div className="trace-chip-row">
                <span className={`badge ${auditSupported ? "badge-success" : "badge-warning"}`}>
                  {auditSupported ? "Supported" : "Needs review"}
                </span>
                <span className={`badge ${auditAbstained ? "badge-danger" : "badge-info"}`}>
                  {auditAbstained ? "Abstained" : "Answered"}
                </span>
              </div>
            </div>
          </section>

          <section className="trace-card">
            <div className="trace-card-header">
              <Bot size={16} className="text-brand" />
              <span>Retrieved evidence</span>
            </div>
            {items.length > 0 ? (
              <div className="trace-evidence-list">
                {items.map((item, index) => {
                  const key = String(item.memory_id ?? item.item_id ?? `${index}`);
                  const metadata = typeof item.metadata === "object" && item.metadata ? item.metadata as Record<string, unknown> : {};
                  return (
                    <article key={key} className="trace-evidence-card">
                      <div className="trace-evidence-header">
                        <div className="trace-chip-row">
                          <span className="badge badge-info">{prettyValue(item.layer)}</span>
                          {metadata.graph_reason ? <span className="badge badge-warning">{prettyValue(metadata.graph_reason)}</span> : null}
                        </div>
                        <div className="text-xs text-secondary">
                          score {prettyValue((item.score ?? metadata.retrieval_score) as unknown)}
                        </div>
                      </div>
                      <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>{prettyValue(item.content)}</div>
                      <div className="text-xs text-secondary">
                        {metadata.source_name ? `source ${prettyValue(metadata.source_name)}` : "No source metadata"}
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="trace-empty">No retrieval items were returned for this answer yet.</div>
            )}
          </section>

          {toolInvocations.length > 0 ? (
            <section className="trace-card">
              <div className="trace-card-header">
                <Braces size={16} className="text-brand" />
                <span>Tool activity</span>
              </div>
              <div className="trace-list">
                {toolInvocations.map((tool) => (
                  <div key={tool.invocation_id} className="trace-list-item">
                    <div className="flex justify-between items-center gap-2">
                      <strong>{tool.tool_name}</strong>
                      <span className="text-xs text-secondary">{formatDate(tool.created_at)}</span>
                    </div>
                    <div className="text-xs text-secondary" style={{ marginTop: "0.25rem" }}>
                      payload keys: {Object.keys(tool.payload ?? {}).join(", ") || "none"} | result keys: {Object.keys(tool.result ?? {}).join(", ") || "none"}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {(historicalTraces.length > 0 || historicalAudits.length > 0) ? (
            <section className="trace-card">
              <div className="trace-card-header">
                <Clock3 size={16} className="text-brand" />
                <span>History</span>
              </div>
              <div className="trace-grid">
                <div className="trace-list">
                  {historicalTraces.slice(0, 6).map((item) => (
                    <div key={item.trace_id} className="trace-list-item">
                      <div className="flex justify-between items-center gap-2">
                        <strong>{item.query}</strong>
                        <span className="text-xs text-secondary">{formatDate(item.created_at)}</span>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="trace-list">
                  {historicalAudits.slice(0, 6).map((item) => (
                    <div key={item.audit_id} className="trace-list-item">
                      <div className="flex justify-between items-center gap-2">
                        <strong>{item.model_name || item.provider}</strong>
                        <span className="text-xs text-secondary">{formatDate(item.created_at)}</span>
                      </div>
                      <div className="trace-chip-row" style={{ marginTop: "0.45rem" }}>
                        <span className={`badge ${item.supported ? "badge-success" : "badge-warning"}`}>
                          {item.supported ? "Supported" : "Weak"}
                        </span>
                        <span className={`badge ${item.abstained ? "badge-danger" : "badge-info"}`}>
                          {item.abstained ? "Abstained" : "Answered"}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          ) : null}

          {auditMetadata ? (
            <section className="trace-card">
              <div className="trace-card-header">
                <CheckCircle2 size={16} className="text-brand" />
                <span>Audit metadata</span>
              </div>
              <pre className="trace-json-block">{JSON.stringify(auditMetadata, null, 2)}</pre>
            </section>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
