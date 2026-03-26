from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.db import Base


class UserModel(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrganizationModel(Base):
    __tablename__ = "organizations"

    org_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppModel(Base):
    __tablename__ = "apps"

    app_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), ForeignKey("organizations.org_id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApiKeyModel(Base):
    __tablename__ = "api_keys"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    hashed_key: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    token_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.user_id"), index=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    token_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryModel(Base):
    __tablename__ = "memories"

    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    layer: Mapped[str] = mapped_column(String(32), index=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    memory_scope: Mapped[str] = mapped_column(String(32), index=True, default="conversation")
    scope_ref: Mapped[str] = mapped_column(String(128), index=True, default="")
    conversation_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    promotion_status: Mapped[str] = mapped_column(String(32), index=True, default="direct")
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding_json: Mapped[list] = mapped_column(JSON, default=list)
    embedding_vector: Mapped[list] = mapped_column(Vector(settings.embedding_dimensions))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(64), default="interaction")
    document_source_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    chunk_key: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventModel(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    role: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(32), default="unknown")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GraphNodeModel(Base):
    __tablename__ = "graph_nodes"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    graph_scope: Mapped[str] = mapped_column(String(32), index=True, default="conversation")
    scope_ref: Mapped[str] = mapped_column(String(128), index=True, default="")
    conversation_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    label: Mapped[str] = mapped_column(String(255), index=True)
    node_type: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class GraphEdgeModel(Base):
    __tablename__ = "graph_edges"

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    graph_scope: Mapped[str] = mapped_column(String(32), index=True, default="conversation")
    scope_ref: Mapped[str] = mapped_column(String(128), index=True, default="")
    conversation_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    from_node: Mapped[str] = mapped_column(String(64), ForeignKey("graph_nodes.node_id"))
    to_node: Mapped[str] = mapped_column(String(64), ForeignKey("graph_nodes.node_id"))
    relation: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class JobModel(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentSourceModel(Base):
    __tablename__ = "document_sources"

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    memory_scope: Mapped[str] = mapped_column(String(32), index=True, default="app")
    scope_ref: Mapped[str] = mapped_column(String(128), index=True, default="")
    conversation_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    source_name: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str] = mapped_column(String(512), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    parser_name: Mapped[str] = mapped_column(String(128), default="")
    chunking_strategy: Mapped[str] = mapped_column(String(64), default="")
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    block_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True, default="indexed_pending_reflection")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reflected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentModel(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    public_agent_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationModel(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[str] = mapped_column(String(128), ForeignKey("agents.agent_id"), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="active")
    summary: Mapped[str] = mapped_column(Text, default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationLabelModel(Base):
    __tablename__ = "conversation_labels"

    conversation_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversations.conversation_id"), primary_key=True)
    conversation_type: Mapped[str] = mapped_column(String(64), index=True, default="general")
    topic: Mapped[str] = mapped_column(String(128), index=True, default="general")
    outcome: Mapped[str] = mapped_column(String(64), index=True, default="open")
    escalation_state: Mapped[str] = mapped_column(String(64), index=True, default="none")
    satisfaction: Mapped[str] = mapped_column(String(64), default="unknown")
    hallucination_suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_level: Mapped[str] = mapped_column(String(64), index=True, default="normal")
    memory_impact_score: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationTurnModel(Base):
    __tablename__ = "conversation_turns"

    turn_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversations.conversation_id"), index=True)
    turn_index: Mapped[int] = mapped_column(Integer, index=True)
    user_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assistant_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationMessageModel(Base):
    __tablename__ = "conversation_messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversations.conversation_id"), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("conversation_turns.turn_id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RetrievalTraceModel(Base):
    __tablename__ = "retrieval_traces"

    trace_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversations.conversation_id"), index=True)
    message_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversation_messages.message_id"), index=True)
    query: Mapped[str] = mapped_column(Text)
    items_json: Mapped[list] = mapped_column(JSON, default=list)
    trace_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnswerAuditModel(Base):
    __tablename__ = "answer_audits"

    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversations.conversation_id"), index=True)
    turn_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversation_turns.turn_id"), index=True)
    user_message_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversation_messages.message_id"), index=True)
    assistant_message_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversation_messages.message_id"), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="heuristic")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    supported: Mapped[bool] = mapped_column(Boolean, default=False)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ToolInvocationModel(Base):
    __tablename__ = "tool_invocations"

    invocation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversations.conversation_id"), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("conversation_turns.turn_id"), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryCandidateModel(Base):
    __tablename__ = "memory_candidates"

    candidate_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    memory_scope: Mapped[str] = mapped_column(String(32), index=True, default="conversation")
    layer: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source_memory_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EntityAliasModel(Base):
    __tablename__ = "entity_aliases"

    alias_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(128), index=True)
    app_id: Mapped[str] = mapped_column(String(128), index=True)
    canonical_label: Mapped[str] = mapped_column(String(255), index=True)
    alias_label: Mapped[str] = mapped_column(String(255), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
