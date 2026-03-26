import { useEffect, useRef } from "react";
import { Bot, MessageSquareText, Quote, ShieldAlert, User2 } from "lucide-react";
import type { Conversation, ConversationMessage } from "../lib/api";

type ConversationThreadProps = {
  conversation: Conversation | null;
  emptyTitle?: string;
  emptyBody?: string;
};

function formatMessageTime(value: string) {
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function roleIcon(role: string) {
  if (role === "assistant") {
    return <Bot size={16} className="text-brand" />;
  }
  return <User2 size={16} className="text-brand" />;
}

function renderMessageMeta(message: ConversationMessage) {
  if (message.role !== "assistant") {
    return null;
  }
  const supported = Boolean(message.metadata?.supported);
  const abstained = Boolean(message.metadata?.abstained);
  const confidence = typeof message.metadata?.confidence === "number" ? Number(message.metadata.confidence) : null;

  return (
    <div className="trace-chip-row" style={{ marginTop: "0.6rem" }}>
      <span className={`badge ${supported ? "badge-success" : "badge-warning"}`}>
        {supported ? "Supported" : "Weak support"}
      </span>
      {abstained ? <span className="badge badge-danger">Abstained</span> : null}
      {confidence !== null ? <span className="badge badge-info">confidence {confidence.toFixed(2)}</span> : null}
    </div>
  );
}

export function ConversationThread({
  conversation,
  emptyTitle = "No conversation selected",
  emptyBody = "Choose a conversation from the list to inspect its messages, labels, and citations.",
}: ConversationThreadProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [conversation?.conversation_id, conversation?.updated_at, conversation?.turns.length]);

  if (!conversation) {
    return (
      <div className="thread-empty-state glass-panel">
        <MessageSquareText size={42} className="text-brand" />
        <h3>{emptyTitle}</h3>
        <p>{emptyBody}</p>
      </div>
    );
  }

  return (
    <div className="thread-stack">
      {conversation.turns.length > 0 ? (
        conversation.turns.map((turn) => (
          <section key={turn.turn_id} className="thread-turn-card">
            <div className="thread-turn-header">
              <div>
                <p className="section-label" style={{ marginBottom: "0.25rem" }}>Turn {turn.turn_index}</p>
                <h3 style={{ fontSize: "1.05rem", marginBottom: "0.2rem" }}>{turn.summary || "Conversation turn"}</h3>
              </div>
              <div className="trace-chip-row">
                <span className="badge badge-info">{turn.status}</span>
                <span className="text-xs text-secondary">{formatMessageTime(turn.updated_at)}</span>
              </div>
            </div>

            <div className="thread-message-list">
              {turn.messages.map((message) => (
                <article key={message.message_id} className={`thread-message-card thread-message-${message.role}`}>
                  <div className="thread-message-topline">
                    <div className="flex items-center gap-2">
                      {roleIcon(message.role)}
                      <strong>{message.role === "assistant" ? "Assistant" : "User"}</strong>
                    </div>
                    <span className="text-xs text-secondary">{formatMessageTime(message.created_at)}</span>
                  </div>
                  <div className="thread-message-content">{message.content}</div>
                  {renderMessageMeta(message)}
                  {message.citations.length > 0 ? (
                    <div className="thread-citation-list">
                      {message.citations.map((citation, index) => (
                        <div key={`${message.message_id}-${index}`} className="thread-citation-item">
                          <div className="flex items-center gap-2">
                            <Quote size={14} className="text-brand" />
                            <span className="badge badge-info">{String(citation.layer ?? "memory")}</span>
                          </div>
                          <div style={{ fontWeight: 600 }}>{String(citation.content ?? "")}</div>
                          <div className="text-xs text-secondary">
                            {citation.memory_id ? `id ${String(citation.memory_id)}` : "Referenced evidence"}
                            {typeof citation.score === "number" ? ` | score ${Number(citation.score).toFixed(2)}` : ""}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </section>
        ))
      ) : (
        <div className="thread-empty-state glass-panel">
          <ShieldAlert size={42} className="text-brand" />
          <h3>No turns yet</h3>
          <p>Send the first message to start building a retrieval trace, audit trail, and evolving memory candidates.</p>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
