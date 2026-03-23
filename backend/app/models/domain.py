from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class MemoryLayer(str, Enum):
    SESSION = "session"
    EVENT = "event"
    GRAPH = "graph"
    LONG_TERM = "long_term"
    FAILURE = "failure"
    RESOLUTION = "resolution"
    RETRIEVAL_HINT = "retrieval_hint"


class Outcome(str, Enum):
    UNKNOWN = "unknown"
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


@dataclass(slots=True)
class Scope:
    org_id: str
    app_id: str
    user_id: str
    session_id: str


@dataclass(slots=True)
class MemoryRecord:
    layer: MemoryLayer
    scope: Scope
    content: str
    memory_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    source: str = "interaction"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class InteractionEvent:
    scope: Scope
    role: str
    content: str
    event_id: str = field(default_factory=lambda: str(uuid4()))
    outcome: Outcome = Outcome.UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class GraphNode:
    scope: Scope
    label: str
    node_type: str
    node_id: str = field(default_factory=lambda: str(uuid4()))
    confidence: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    scope: Scope
    from_node: str
    to_node: str
    relation: str
    edge_id: str = field(default_factory=lambda: str(uuid4()))
    confidence: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
