from __future__ import annotations

from app.models.domain import InteractionEvent, MemoryRecord, Scope
from app.schemas.memory import EventRequest, RecallRequest, RememberRequest
from app.services.memory import memory_service


class MCPService:
    def describe_tools(self) -> list[dict]:
        return [
            {"name": "remember", "description": "Store memory in the active scope."},
            {"name": "recall", "description": "Retrieve relevant memories with trace metadata."},
            {"name": "append_event", "description": "Append an interaction event to the event store."},
            {"name": "record_feedback", "description": "Store explicit user feedback or outcome signals."},
            {"name": "search_graph", "description": "Return graph nodes and edges for the current scope."},
            {"name": "reflect_session", "description": "Trigger delayed reflection and graph building."},
            {"name": "explain_retrieval", "description": "Return the trace for a retrieval query."},
        ]

    def remember(self, payload: RememberRequest):
        scope = Scope(**payload.scope.model_dump())
        return memory_service.remember(
            MemoryRecord(
                layer=payload.layer,
                scope=scope,
                content=payload.content,
                metadata=payload.metadata,
                tags=payload.tags,
                source=payload.source,
            )
        )

    def append_event(self, payload: EventRequest):
        scope = Scope(**payload.scope.model_dump())
        return memory_service.append_event(
            InteractionEvent(
                scope=scope,
                role=payload.role,
                content=payload.content,
                metadata=payload.metadata,
                outcome=payload.outcome,
            )
        )

    def recall(self, payload: RecallRequest):
        scope = Scope(**payload.scope.model_dump())
        return memory_service.recall(scope, payload.query, payload.top_k, payload.include_layers)


mcp_service = MCPService()
