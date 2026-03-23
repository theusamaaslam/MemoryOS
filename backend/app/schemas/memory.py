from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.domain import MemoryLayer, Outcome


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


class ReflectionEnqueueRequest(BaseModel):
    scope: ScopeModel
    reason: str = "manual"


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
    layers_consulted: list[MemoryLayer]
    ranking_factors: list[str]
    reasons: list[str]


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


class GraphEdgeResponse(BaseModel):
    edge_id: str
    from_node: str
    to_node: str
    relation: str
    confidence: float
    evidence_ids: list[str]
    metadata: dict[str, Any]


class GraphResponse(BaseModel):
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class ReflectionJobResponse(BaseModel):
    job_id: str
    status: str
    summary: str


class TimelineItemResponse(BaseModel):
    item_id: str
    item_type: str
    content: str
    layer: str
    created_at: datetime
    metadata: dict[str, Any]


class TimelineResponse(BaseModel):
    items: list[TimelineItemResponse]
