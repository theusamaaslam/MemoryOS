from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.domain import MemoryLayer, MemoryScope, Outcome


class ScopeModel(BaseModel):
    org_id: str
    app_id: str
    user_id: str
    session_id: str


class RememberRequest(BaseModel):
    scope: ScopeModel
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = "interaction"
    layer: MemoryLayer = MemoryLayer.SESSION
    memory_scope: MemoryScope = MemoryScope.CONVERSATION


class EventRequest(BaseModel):
    scope: ScopeModel
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    outcome: Outcome = Outcome.UNKNOWN


class FeedbackRequest(BaseModel):
    scope: ScopeModel
    event_id: str | None = None
    summary: str
    helpful: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallRequest(BaseModel):
    scope: ScopeModel
    query: str
    top_k: int = 5
    include_layers: list[MemoryLayer] | None = None


class ScopeRequest(BaseModel):
    scope: ScopeModel
    memory_scope: MemoryScope = MemoryScope.APP


class ReflectionEnqueueRequest(BaseModel):
    scope: ScopeModel
    reason: str = "manual"
    memory_scope: MemoryScope = MemoryScope.APP


class MemoryResponse(BaseModel):
    memory_id: str
    layer: MemoryLayer
    content: str
    confidence: float
    tags: list[str]
    metadata: dict[str, Any]
    created_at: datetime


class RetrievalTraceResponse(BaseModel):
    query: str
    rewritten_query: str | None = None
    query_rewrite_applied: bool = False
    query_rewrite_reason: str | None = None
    layers_consulted: list[MemoryLayer]
    query_mode: str = "hybrid"
    query_intent: str = "general"
    scope_bias: str = "balanced"
    graph_strategy: str = "focused"
    grounding_policy: str = "balanced"
    freshness_bias: str = "normal"
    preferred_layers: list[MemoryLayer] = Field(default_factory=list)
    expansion_terms: list[str] = Field(default_factory=list)
    ranking_factors: list[str]
    reasons: list[str]
    graph_matches: int = 0
    graph_expansions: int = 0
    retrieval_hint_matches: int = 0


class RecallResponse(BaseModel):
    items: list[MemoryResponse]
    trace: RetrievalTraceResponse


class GraphNodeResponse(BaseModel):
    node_id: str
    label: str
    node_type: str
    confidence: float
    evidence_ids: list[str]
    metadata: dict[str, Any]
    memory_scope: MemoryScope = MemoryScope.CONVERSATION
    scope_ref: str | None = None
    conversation_id: str | None = None
    evidence_preview: list[dict[str, Any]] = Field(default_factory=list)


class GraphEdgeResponse(BaseModel):
    edge_id: str
    from_node: str
    to_node: str
    relation: str
    confidence: float
    evidence_ids: list[str]
    metadata: dict[str, Any]
    memory_scope: MemoryScope = MemoryScope.CONVERSATION
    scope_ref: str | None = None
    conversation_id: str | None = None
    evidence_preview: list[dict[str, Any]] = Field(default_factory=list)


class GraphSummaryResponse(BaseModel):
    node_count: int = 0
    edge_count: int = 0
    evidence_count: int = 0
    source_count: int = 0
    orphan_node_count: int = 0
    duplicate_label_count: int = 0
    ungrounded_node_count: int = 0
    ungrounded_edge_count: int = 0
    source_names: list[str] = Field(default_factory=list)


class GraphResponse(BaseModel):
    memory_scope: MemoryScope = MemoryScope.APP
    scope_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    summary: GraphSummaryResponse = Field(default_factory=GraphSummaryResponse)
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class ReflectionJobResponse(BaseModel):
    job_id: str
    status: str
    summary: str
    provider: str | None = None


class TimelineItemResponse(BaseModel):
    item_id: str
    item_type: str
    content: str
    layer: str
    created_at: datetime
    metadata: dict[str, Any]


class TimelineResponse(BaseModel):
    items: list[TimelineItemResponse]


class SessionSummaryResponse(BaseModel):
    session_id: str
    last_activity_at: datetime | None = None
    memory_count: int = 0
    event_count: int = 0
    title: str | None = None
    status: str | None = None
    agent_id: str | None = None


class SessionListResponse(BaseModel):
    items: list[SessionSummaryResponse]
