from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.domain import MemoryCandidateStatus, MemoryLayer, MemoryScope


class AgentResponse(BaseModel):
    agent_id: str
    org_id: str
    app_id: str
    name: str
    description: str


class StartConversationRequest(BaseModel):
    app_id: str | None = None
    user_id: str | None = None
    title: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SendMessageRequest(BaseModel):
    content: str
    top_k: int = 5
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationLabelResponse(BaseModel):
    conversation_type: str
    topic: str
    outcome: str
    escalation_state: str
    satisfaction: str
    hallucination_suspected: bool
    risk_level: str
    memory_impact_score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationMessageResponse(BaseModel):
    message_id: str
    role: str
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ConversationTurnResponse(BaseModel):
    turn_id: str
    turn_index: int
    status: str
    summary: str
    messages: list[ConversationMessageResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConversationResponse(BaseModel):
    conversation_id: str
    org_id: str
    app_id: str
    user_id: str
    agent_id: str
    title: str
    status: str
    summary: str
    message_count: int
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    label: ConversationLabelResponse
    turns: list[ConversationTurnResponse] = Field(default_factory=list)


class ConversationSummaryResponse(BaseModel):
    conversation_id: str
    app_id: str
    user_id: str
    agent_id: str
    title: str
    status: str
    summary: str
    message_count: int
    last_message_at: datetime | None = None
    created_at: datetime
    label: ConversationLabelResponse


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]


class CitationResponse(BaseModel):
    memory_id: str
    layer: str
    content: str
    score: float


class SendMessageResponse(BaseModel):
    conversation: ConversationSummaryResponse
    user_message: ConversationMessageResponse
    assistant_message: ConversationMessageResponse
    citations: list[CitationResponse]
    supported: bool
    abstained: bool
    trace_id: str
    audit_id: str


class ExplainAnswerResponse(BaseModel):
    trace_id: str
    query: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)


class MemoryCandidateResponse(BaseModel):
    candidate_id: str
    org_id: str
    app_id: str
    user_id: str
    conversation_id: str
    memory_scope: MemoryScope
    layer: MemoryLayer
    content: str
    status: MemoryCandidateStatus
    confidence: float
    source_memory_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MemoryCandidateListResponse(BaseModel):
    items: list[MemoryCandidateResponse]


class ReviewMemoryCandidateRequest(BaseModel):
    reason: str | None = None


class CloseConversationRequest(BaseModel):
    reason: str | None = None


class MergeEntitiesRequest(BaseModel):
    app_id: str
    canonical_label: str
    alias_label: str


class RebuildGraphRequest(BaseModel):
    conversation_id: str


class ClassifyConversationRequest(BaseModel):
    conversation_id: str


class ConversationTraceResponse(BaseModel):
    conversation: ConversationResponse
    traces: list[dict[str, Any]] = Field(default_factory=list)
    audits: list[dict[str, Any]] = Field(default_factory=list)
    tool_invocations: list[dict[str, Any]] = Field(default_factory=list)
