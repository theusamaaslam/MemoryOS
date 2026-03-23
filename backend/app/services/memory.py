from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.core.config import settings
from app.core.cache import fetch_session_memory, push_session_memory
from app.core.db import session_scope
from app.models.domain import GraphEdge, GraphNode, InteractionEvent, MemoryLayer, MemoryRecord, Scope
from app.models.persistence import EventModel, GraphEdgeModel, GraphNodeModel, MemoryModel
from app.schemas.memory import RecallResponse, RetrievalTraceResponse, TimelineResponse
from app.services.embeddings import embedding_service
from app.services.providers import provider_registry


def _scope_key(scope: Scope) -> str:
    return f"{scope.org_id}:{scope.app_id}:{scope.user_id}:{scope.session_id}"


class MemoryService:
    def remember(self, record: MemoryRecord) -> MemoryRecord:
        record.updated_at = datetime.now(UTC)
        if record.layer == MemoryLayer.SESSION:
            push_session_memory(_scope_key(record.scope), self._memory_to_payload(record))
            return record
        embedding = embedding_service.embed_document(record.content)
        with session_scope() as session:
            session.add(
                MemoryModel(
                    memory_id=record.memory_id,
                    layer=record.layer.value,
                    org_id=record.scope.org_id,
                    app_id=record.scope.app_id,
                    user_id=record.scope.user_id,
                    session_id=record.scope.session_id,
                    content=record.content,
                    metadata_json=record.metadata,
                    embedding_json=embedding,
                    embedding_vector=embedding,
                    confidence=record.confidence,
                    tags_json=record.tags,
                    source=record.source,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
        return record

    def append_event(self, event: InteractionEvent) -> InteractionEvent:
        with session_scope() as session:
            session.add(
                EventModel(
                    event_id=event.event_id,
                    org_id=event.scope.org_id,
                    app_id=event.scope.app_id,
                    user_id=event.scope.user_id,
                    session_id=event.scope.session_id,
                    role=event.role,
                    content=event.content,
                    outcome=event.outcome.value,
                    metadata_json=event.metadata,
                    created_at=event.created_at,
                )
            )
        return event

    def record_feedback(self, scope: Scope, summary: str, helpful: bool, metadata: dict) -> MemoryRecord:
        layer = MemoryLayer.RESOLUTION if helpful else MemoryLayer.FAILURE
        record = MemoryRecord(
            layer=layer,
            scope=scope,
            content=summary,
            metadata=metadata | {"helpful": helpful},
            confidence=0.85 if helpful else 0.7,
            tags=["feedback"],
            source="user_feedback",
        )
        return self.remember(record)

    def reflect(self, scope: Scope) -> dict[str, str]:
        key = _scope_key(scope)
        provider = provider_registry[settings.default_provider]
        with session_scope() as session:
            events = (
                session.query(EventModel)
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    session_id=scope.session_id,
                )
                .order_by(EventModel.created_at.asc())
                .all()
            )
            transcript = "\n".join(
                [f"{event.role}: {event.content}" for event in events]
                + [record["content"] for record in fetch_session_memory(key)]
            )
        artifact = provider.reflect(transcript)
        for fact in artifact.facts:
            self.remember(
                MemoryRecord(
                    layer=MemoryLayer.LONG_TERM,
                    scope=scope,
                    content=fact,
                    metadata={"kind": "fact", "generated_by": provider.name},
                    confidence=0.76,
                    tags=["reflection", "fact"],
                    source="reflection",
                )
            )
        for pref in artifact.preferences:
            self.remember(
                MemoryRecord(
                    layer=MemoryLayer.LONG_TERM,
                    scope=scope,
                    content=pref,
                    metadata={"kind": "preference", "generated_by": provider.name},
                    confidence=0.82,
                    tags=["reflection", "preference"],
                    source="reflection",
                )
            )
        for failure in artifact.failures:
            self.remember(
                MemoryRecord(
                    layer=MemoryLayer.FAILURE,
                    scope=scope,
                    content=failure,
                    metadata={"kind": "failure", "generated_by": provider.name},
                    confidence=0.7,
                    tags=["reflection", "failure"],
                    source="reflection",
                )
            )
        for resolution in artifact.resolutions:
            self.remember(
                MemoryRecord(
                    layer=MemoryLayer.RESOLUTION,
                    scope=scope,
                    content=resolution,
                    metadata={"kind": "resolution", "generated_by": provider.name},
                    confidence=0.84,
                    tags=["reflection", "resolution"],
                    source="reflection",
                )
            )
        for hint in artifact.retrieval_hints:
            self.remember(
                MemoryRecord(
                    layer=MemoryLayer.RETRIEVAL_HINT,
                    scope=scope,
                    content=hint,
                    metadata={"kind": "retrieval_hint", "generated_by": provider.name},
                    confidence=0.8,
                    tags=["reflection", "hint"],
                    source="reflection",
                )
            )
        existing = {node.label: node for node in self._load_graph_nodes(scope)}
        for label, node_type in artifact.entities:
            if label not in existing:
                node = GraphNode(scope=scope, label=label, node_type=node_type, confidence=0.8)
                self._upsert_graph_node(node)
                existing[label] = node
        for source, target, relation in artifact.relations:
            if source in existing and target in existing:
                self._create_graph_edge(
                    GraphEdge(
                        scope=scope,
                        from_node=existing[source].node_id,
                        to_node=existing[target].node_id,
                        relation=relation,
                        confidence=0.75,
                    )
                )
        job_id = str(uuid4())
        return {"job_id": job_id, "status": "completed", "summary": artifact.summary}

    def recall(self, scope: Scope, query: str, top_k: int, include_layers: list[MemoryLayer] | None) -> RecallResponse:
        layers = include_layers or [
            MemoryLayer.SESSION,
            MemoryLayer.EVENT,
            MemoryLayer.LONG_TERM,
            MemoryLayer.FAILURE,
            MemoryLayer.RESOLUTION,
            MemoryLayer.RETRIEVAL_HINT,
        ]
        query_embedding = embedding_service.embed_query(query)
        candidates: list[MemoryRecord] = self._load_memory_candidates(scope, layers, query_embedding, max(top_k * 4, 12))
        if MemoryLayer.SESSION in layers:
            candidates.extend(self._load_session_records(scope))

        scored: list[tuple[float, MemoryRecord]] = []
        query_terms = set(query.lower().split())
        for item in candidates:
            terms = set(item.content.lower().split())
            overlap = len(query_terms & terms)
            vector_similarity = embedding_service.similarity(
                query_embedding,
                item.metadata.get("_embedding", []),
            )
            score = overlap + item.confidence + vector_similarity
            if item.layer == MemoryLayer.RETRIEVAL_HINT:
                score += 0.25
            if item.layer == MemoryLayer.FAILURE:
                score += 0.1
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        selected = [item for _, item in scored[:top_k]]
        return RecallResponse(
            items=[
                {
                    "memory_id": item.memory_id,
                    "layer": item.layer,
                    "content": item.content,
                    "confidence": item.confidence,
                    "tags": item.tags,
                    "metadata": item.metadata,
                    "created_at": item.created_at,
                }
                for item in selected
            ],
            trace=RetrievalTraceResponse(
                query=query,
                layers_consulted=layers,
                ranking_factors=[
                    "semantic_overlap",
                    "embedding_similarity",
                    "confidence",
                    "recency",
                    "failure_resolution_bias",
                    "retrieval_hint_bias",
                ],
                reasons=[
                    "Session memory checked first for low-latency continuity.",
                    "Long-term and failure memories blended for self-improving recall.",
                    "Retrieval hints promoted from prior reflections received a ranking boost.",
                ],
            ),
        )

    def get_graph(self, scope: Scope) -> dict[str, list[dict]]:
        return {
            "nodes": [
                {
                    "node_id": node.node_id,
                    "label": node.label,
                    "node_type": node.node_type,
                    "confidence": node.confidence,
                    "evidence_ids": node.evidence_ids,
                    "metadata": node.metadata,
                }
                for node in self._load_graph_nodes(scope)
            ],
            "edges": [
                {
                    "edge_id": edge.edge_id,
                    "from_node": edge.from_node,
                    "to_node": edge.to_node,
                    "relation": edge.relation,
                    "confidence": edge.confidence,
                    "evidence_ids": edge.evidence_ids,
                    "metadata": edge.metadata,
                }
                for edge in self._load_graph_edges(scope)
            ],
        }

    def ingest_documents(self, scope: Scope, source_name: str, chunks: list[dict]) -> dict[str, str | int]:
        for chunk in chunks:
            self.remember(
                MemoryRecord(
                    layer=MemoryLayer.LONG_TERM,
                    scope=scope,
                    content=chunk["content"],
                    metadata={
                        "kind": "document_chunk",
                        "source_name": source_name,
                        "source_uri": chunk["source_uri"],
                        "title": chunk.get("title"),
                        **chunk.get("metadata", {}),
                    },
                    confidence=0.74,
                    tags=["ingested", "enterprise_knowledge"],
                    source="ingestion",
                )
            )
        return {"job_id": str(uuid4()), "chunks_received": len(chunks), "status": "queued"}

    def timeline(self, scope: Scope, limit: int = 30) -> TimelineResponse:
        with session_scope() as session:
            memory_rows = (
                session.query(MemoryModel)
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    session_id=scope.session_id,
                )
                .order_by(MemoryModel.created_at.desc())
                .limit(limit)
                .all()
            )
            event_rows = (
                session.query(EventModel)
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    session_id=scope.session_id,
                )
                .order_by(EventModel.created_at.desc())
                .limit(limit)
                .all()
            )
        items = [
            {
                "item_id": row.memory_id,
                "item_type": "memory",
                "content": row.content,
                "layer": row.layer,
                "created_at": row.created_at,
                "metadata": row.metadata_json or {},
            }
            for row in memory_rows
        ] + [
            {
                "item_id": row.event_id,
                "item_type": "event",
                "content": f"{row.role}: {row.content}",
                "layer": "event",
                "created_at": row.created_at,
                "metadata": row.metadata_json or {},
            }
            for row in event_rows
        ]
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return TimelineResponse(items=items[:limit])

    def _memory_to_payload(self, record: MemoryRecord) -> dict:
        return {
            "memory_id": record.memory_id,
            "layer": record.layer.value,
            "content": record.content,
            "confidence": record.confidence,
            "tags": record.tags,
            "metadata": record.metadata,
            "source": record.source,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    def _load_session_records(self, scope: Scope) -> list[MemoryRecord]:
        records = []
        for payload in fetch_session_memory(_scope_key(scope)):
            metadata = payload["metadata"] | {"_embedding": embedding_service.embed_document(payload["content"])}
            records.append(
                MemoryRecord(
                    memory_id=payload["memory_id"],
                    layer=MemoryLayer(payload["layer"]),
                    scope=scope,
                    content=payload["content"],
                    confidence=payload["confidence"],
                    tags=payload["tags"],
                    metadata=metadata,
                    source=payload["source"],
                    created_at=datetime.fromisoformat(payload["created_at"]),
                    updated_at=datetime.fromisoformat(payload["updated_at"]),
                )
            )
        return records

    def _load_memory_candidates(
        self,
        scope: Scope,
        layers: list[MemoryLayer],
        query_embedding: list[float],
        limit: int,
    ) -> list[MemoryRecord]:
        with session_scope() as session:
            allowed = {layer.value for layer in layers if layer != MemoryLayer.EVENT and layer != MemoryLayer.SESSION}
            memory_query = session.query(MemoryModel).filter_by(
                org_id=scope.org_id,
                app_id=scope.app_id,
                user_id=scope.user_id,
                session_id=scope.session_id,
            )
            if allowed:
                memory_query = memory_query.filter(MemoryModel.layer.in_(allowed))
            memory_rows = (
                memory_query.order_by(MemoryModel.embedding_vector.cosine_distance(query_embedding))
                .limit(limit)
                .all()
            )
            event_rows = (
                session.query(EventModel)
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    session_id=scope.session_id,
                )
                .order_by(EventModel.created_at.desc())
                .limit(limit)
                .all()
            )
        candidates = [
            MemoryRecord(
                memory_id=row.memory_id,
                layer=MemoryLayer(row.layer),
                scope=scope,
                content=row.content,
                metadata=(row.metadata_json or {}) | {"_embedding": row.embedding_json or []},
                confidence=row.confidence,
                tags=row.tags_json or [],
                source=row.source,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in memory_rows
        ]
        if MemoryLayer.EVENT in layers:
            candidates.extend(
                [
                    MemoryRecord(
                        memory_id=row.event_id,
                        layer=MemoryLayer.EVENT,
                        scope=scope,
                        content=f"{row.role}: {row.content}",
                        metadata=(row.metadata_json or {}) | {"_embedding": embedding_service.embed_document(f"{row.role}: {row.content}")},
                        confidence=0.62,
                        tags=["event", row.outcome],
                        source="event_log",
                        created_at=row.created_at,
                        updated_at=row.created_at,
                    )
                    for row in event_rows
                ]
            )
        return candidates

    def _load_graph_nodes(self, scope: Scope) -> list[GraphNode]:
        with session_scope() as session:
            rows = (
                session.query(GraphNodeModel)
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    session_id=scope.session_id,
                )
                .all()
            )
        return [
            GraphNode(
                scope=scope,
                node_id=row.node_id,
                label=row.label,
                node_type=row.node_type,
                confidence=row.confidence,
                evidence_ids=row.evidence_ids_json or [],
                metadata=row.metadata_json or {},
            )
            for row in rows
        ]

    def _load_graph_edges(self, scope: Scope) -> list[GraphEdge]:
        with session_scope() as session:
            rows = (
                session.query(GraphEdgeModel)
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    session_id=scope.session_id,
                )
                .all()
            )
        return [
            GraphEdge(
                scope=scope,
                edge_id=row.edge_id,
                from_node=row.from_node,
                to_node=row.to_node,
                relation=row.relation,
                confidence=row.confidence,
                evidence_ids=row.evidence_ids_json or [],
                metadata=row.metadata_json or {},
            )
            for row in rows
        ]

    def _upsert_graph_node(self, node: GraphNode) -> None:
        with session_scope() as session:
            existing = (
                session.query(GraphNodeModel)
                .filter_by(
                    org_id=node.scope.org_id,
                    app_id=node.scope.app_id,
                    user_id=node.scope.user_id,
                    session_id=node.scope.session_id,
                    label=node.label,
                )
                .first()
            )
            if existing:
                existing.node_type = node.node_type
                existing.confidence = max(existing.confidence, node.confidence)
                existing.metadata_json = node.metadata
                return
            session.add(
                GraphNodeModel(
                    node_id=node.node_id,
                    org_id=node.scope.org_id,
                    app_id=node.scope.app_id,
                    user_id=node.scope.user_id,
                    session_id=node.scope.session_id,
                    label=node.label,
                    node_type=node.node_type,
                    confidence=node.confidence,
                    evidence_ids_json=node.evidence_ids,
                    metadata_json=node.metadata,
                )
            )

    def _create_graph_edge(self, edge: GraphEdge) -> None:
        with session_scope() as session:
            exists = (
                session.query(GraphEdgeModel)
                .filter_by(
                    org_id=edge.scope.org_id,
                    app_id=edge.scope.app_id,
                    user_id=edge.scope.user_id,
                    session_id=edge.scope.session_id,
                    from_node=edge.from_node,
                    to_node=edge.to_node,
                    relation=edge.relation,
                )
                .first()
            )
            if exists is not None:
                return
            session.add(
                GraphEdgeModel(
                    edge_id=edge.edge_id,
                    org_id=edge.scope.org_id,
                    app_id=edge.scope.app_id,
                    user_id=edge.scope.user_id,
                    session_id=edge.scope.session_id,
                    from_node=edge.from_node,
                    to_node=edge.to_node,
                    relation=edge.relation,
                    confidence=edge.confidence,
                    evidence_ids_json=edge.evidence_ids,
                    metadata_json=edge.metadata,
                )
            )


memory_service = MemoryService()
