from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, func, or_

from app.core.config import settings
from app.core.cache import fetch_session_memory, push_session_memory
from app.core.db import session_scope
from app.models.domain import GraphEdge, GraphNode, InteractionEvent, MemoryLayer, MemoryRecord, MemoryScope, Scope
from app.models.persistence import AgentModel, ConversationModel, DocumentSourceModel, EventModel, GraphEdgeModel, GraphNodeModel, MemoryModel
from app.schemas.memory import RecallResponse, RetrievalTraceResponse, TimelineResponse
from app.services.document_ingestion import document_ingestion_service
from app.services.embeddings import embedding_service
from app.services.jobs import job_service
from app.services.providers import provider_registry, resolve_provider


def _scope_key(scope: Scope) -> str:
    return f"{scope.org_id}:{scope.app_id}:{scope.user_id}:{scope.session_id}"


def _normalize_memory_scope(value: MemoryScope | str | None) -> str:
    if isinstance(value, MemoryScope):
        return value.value
    cleaned = str(value or MemoryScope.CONVERSATION.value).strip().lower()
    return cleaned if cleaned in {scope.value for scope in MemoryScope} else MemoryScope.CONVERSATION.value


def _truncate(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


class MemoryService:
    def _hydrate_memory_scope(self, record: MemoryRecord) -> MemoryRecord:
        normalized_scope = _normalize_memory_scope(record.memory_scope)
        record.memory_scope = MemoryScope(normalized_scope)
        if not record.conversation_id:
            record.conversation_id = record.scope.session_id
        if not record.scope_ref:
            if record.memory_scope == MemoryScope.USER:
                record.scope_ref = record.scope.user_id
            elif record.memory_scope == MemoryScope.APP:
                record.scope_ref = record.scope.app_id
            else:
                record.scope_ref = record.conversation_id
        return record

    def _hydrate_graph_scope(self, item: GraphNode | GraphEdge) -> GraphNode | GraphEdge:
        normalized_scope = _normalize_memory_scope(item.memory_scope)
        item.memory_scope = MemoryScope(normalized_scope)
        if not item.conversation_id:
            item.conversation_id = item.scope.session_id
        if not item.scope_ref:
            if item.memory_scope == MemoryScope.USER:
                item.scope_ref = item.scope.user_id
            elif item.memory_scope == MemoryScope.APP:
                item.scope_ref = item.scope.app_id
            else:
                item.scope_ref = item.conversation_id
        return item

    def _resolve_memory_scope(self, value: MemoryScope | str | None, *, default: MemoryScope | None = None) -> MemoryScope | None:
        if value is None:
            return default
        return MemoryScope(_normalize_memory_scope(value))

    def _memory_scope_filter(self, scope: Scope):
        return or_(
            and_(
                MemoryModel.memory_scope == MemoryScope.CONVERSATION.value,
                MemoryModel.user_id == scope.user_id,
                MemoryModel.conversation_id == scope.session_id,
            ),
            and_(
                MemoryModel.memory_scope == MemoryScope.USER.value,
                MemoryModel.user_id == scope.user_id,
                MemoryModel.scope_ref == scope.user_id,
            ),
            and_(
                MemoryModel.memory_scope == MemoryScope.APP.value,
                MemoryModel.scope_ref == scope.app_id,
            ),
            and_(
                MemoryModel.memory_scope.is_(None),
                MemoryModel.user_id == scope.user_id,
                MemoryModel.session_id == scope.session_id,
            ),
        )

    def _graph_scope_filter(self, scope: Scope):
        return or_(
            and_(
                GraphNodeModel.graph_scope == MemoryScope.CONVERSATION.value,
                GraphNodeModel.user_id == scope.user_id,
                GraphNodeModel.conversation_id == scope.session_id,
            ),
            and_(
                GraphNodeModel.graph_scope == MemoryScope.USER.value,
                GraphNodeModel.user_id == scope.user_id,
                GraphNodeModel.scope_ref == scope.user_id,
            ),
            and_(
                GraphNodeModel.graph_scope == MemoryScope.APP.value,
                GraphNodeModel.scope_ref == scope.app_id,
            ),
            and_(
                GraphNodeModel.graph_scope.is_(None),
                GraphNodeModel.user_id == scope.user_id,
                GraphNodeModel.session_id == scope.session_id,
            ),
        )

    def _graph_edge_scope_filter(self, scope: Scope):
        return or_(
            and_(
                GraphEdgeModel.graph_scope == MemoryScope.CONVERSATION.value,
                GraphEdgeModel.user_id == scope.user_id,
                GraphEdgeModel.conversation_id == scope.session_id,
            ),
            and_(
                GraphEdgeModel.graph_scope == MemoryScope.USER.value,
                GraphEdgeModel.user_id == scope.user_id,
                GraphEdgeModel.scope_ref == scope.user_id,
            ),
            and_(
                GraphEdgeModel.graph_scope == MemoryScope.APP.value,
                GraphEdgeModel.scope_ref == scope.app_id,
            ),
            and_(
                GraphEdgeModel.graph_scope.is_(None),
                GraphEdgeModel.user_id == scope.user_id,
                GraphEdgeModel.session_id == scope.session_id,
            ),
        )

    def _graph_scope_identity(
        self,
        scope: Scope,
        memory_scope: MemoryScope | str,
        *,
        scope_ref: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, str]:
        normalized_scope = MemoryScope(_normalize_memory_scope(memory_scope))
        target_conversation_id = conversation_id or scope.session_id
        if normalized_scope == MemoryScope.USER:
            target_scope_ref = scope_ref or scope.user_id
        elif normalized_scope == MemoryScope.APP:
            target_scope_ref = scope_ref or scope.app_id
        else:
            target_scope_ref = scope_ref or target_conversation_id
        return {
            "graph_scope": normalized_scope.value,
            "scope_ref": target_scope_ref,
            "conversation_id": target_conversation_id,
            "user_id": scope.user_id,
        }

    def _graph_node_target_filter(
        self,
        scope: Scope,
        memory_scope: MemoryScope | str,
        *,
        scope_ref: str | None = None,
        conversation_id: str | None = None,
    ):
        identity = self._graph_scope_identity(
            scope,
            memory_scope,
            scope_ref=scope_ref,
            conversation_id=conversation_id,
        )
        if identity["graph_scope"] == MemoryScope.USER.value:
            return and_(
                GraphNodeModel.graph_scope == identity["graph_scope"],
                GraphNodeModel.user_id == identity["user_id"],
                GraphNodeModel.scope_ref == identity["scope_ref"],
            )
        if identity["graph_scope"] == MemoryScope.APP.value:
            return and_(
                GraphNodeModel.graph_scope == identity["graph_scope"],
                GraphNodeModel.scope_ref == identity["scope_ref"],
            )
        return and_(
            GraphNodeModel.graph_scope == identity["graph_scope"],
            GraphNodeModel.user_id == identity["user_id"],
            GraphNodeModel.conversation_id == identity["conversation_id"],
        )

    def _graph_edge_target_filter(
        self,
        scope: Scope,
        memory_scope: MemoryScope | str,
        *,
        scope_ref: str | None = None,
        conversation_id: str | None = None,
    ):
        identity = self._graph_scope_identity(
            scope,
            memory_scope,
            scope_ref=scope_ref,
            conversation_id=conversation_id,
        )
        if identity["graph_scope"] == MemoryScope.USER.value:
            return and_(
                GraphEdgeModel.graph_scope == identity["graph_scope"],
                GraphEdgeModel.user_id == identity["user_id"],
                GraphEdgeModel.scope_ref == identity["scope_ref"],
            )
        if identity["graph_scope"] == MemoryScope.APP.value:
            return and_(
                GraphEdgeModel.graph_scope == identity["graph_scope"],
                GraphEdgeModel.scope_ref == identity["scope_ref"],
            )
        return and_(
            GraphEdgeModel.graph_scope == identity["graph_scope"],
            GraphEdgeModel.user_id == identity["user_id"],
            GraphEdgeModel.conversation_id == identity["conversation_id"],
        )

    def _document_source_scope_filter(self, scope: Scope):
        return or_(
            and_(
                DocumentSourceModel.memory_scope == MemoryScope.CONVERSATION.value,
                DocumentSourceModel.user_id == scope.user_id,
                DocumentSourceModel.conversation_id == scope.session_id,
            ),
            and_(
                DocumentSourceModel.memory_scope == MemoryScope.USER.value,
                DocumentSourceModel.user_id == scope.user_id,
                DocumentSourceModel.scope_ref == scope.user_id,
            ),
            and_(
                DocumentSourceModel.memory_scope == MemoryScope.APP.value,
                DocumentSourceModel.scope_ref == scope.app_id,
            ),
        )

    def _document_source_scope_identity(
        self,
        scope: Scope,
        memory_scope: MemoryScope | str,
        *,
        scope_ref: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, str]:
        normalized_scope = MemoryScope(_normalize_memory_scope(memory_scope))
        target_conversation_id = conversation_id or scope.session_id
        if normalized_scope == MemoryScope.USER:
            target_scope_ref = scope_ref or scope.user_id
        elif normalized_scope == MemoryScope.APP:
            target_scope_ref = scope_ref or scope.app_id
        else:
            target_scope_ref = scope_ref or target_conversation_id
        return {
            "memory_scope": normalized_scope.value,
            "scope_ref": target_scope_ref,
            "conversation_id": target_conversation_id,
            "user_id": scope.user_id,
        }

    def _document_source_target_filter(
        self,
        scope: Scope,
        memory_scope: MemoryScope | str,
        *,
        scope_ref: str | None = None,
        conversation_id: str | None = None,
    ):
        identity = self._document_source_scope_identity(
            scope,
            memory_scope,
            scope_ref=scope_ref,
            conversation_id=conversation_id,
        )
        if identity["memory_scope"] == MemoryScope.USER.value:
            return and_(
                DocumentSourceModel.memory_scope == identity["memory_scope"],
                DocumentSourceModel.user_id == identity["user_id"],
                DocumentSourceModel.scope_ref == identity["scope_ref"],
            )
        if identity["memory_scope"] == MemoryScope.APP.value:
            return and_(
                DocumentSourceModel.memory_scope == identity["memory_scope"],
                DocumentSourceModel.scope_ref == identity["scope_ref"],
            )
        return and_(
            DocumentSourceModel.memory_scope == identity["memory_scope"],
            DocumentSourceModel.user_id == identity["user_id"],
            DocumentSourceModel.conversation_id == identity["conversation_id"],
        )

    def _resolve_source_uri(self, source_name: str, chunks: list[dict], explicit_source_uri: str | None = None) -> str:
        if explicit_source_uri and explicit_source_uri.strip():
            return explicit_source_uri.strip()
        first_chunk_uri = str(chunks[0].get("source_uri") or "").strip() if chunks else ""
        if first_chunk_uri:
            return first_chunk_uri.split("#", 1)[0]
        normalized_name = re.sub(r"[^a-z0-9]+", "-", str(source_name or "").strip().lower()).strip("-") or "document"
        return f"memory://{normalized_name}"

    def _document_source_id(
        self,
        scope: Scope,
        source_uri: str,
        *,
        memory_scope: MemoryScope,
        scope_ref: str,
    ) -> str:
        digest = hashlib.sha1(
            f"{scope.org_id}|{scope.app_id}|{memory_scope.value}|{scope_ref}|{source_uri.strip()}".encode("utf-8")
        ).hexdigest()
        return f"src-{digest[:40]}"

    def _build_source_registry_metadata(
        self,
        *,
        chunks: list[dict],
        parser: str | None,
        chunking_strategy: str | None,
        request_metadata: dict | None,
    ) -> dict:
        headings: list[str] = []
        block_types: list[str] = []
        sample_titles: list[str] = []
        for chunk in chunks[:24]:
            metadata = chunk.get("metadata", {}) or {}
            for key, bucket in (("section_headings", headings), ("block_types", block_types)):
                value = metadata.get(key)
                if isinstance(value, list):
                    for part in value:
                        text = str(part).strip()
                        if text and text not in bucket:
                            bucket.append(text)
                elif isinstance(value, str):
                    text = value.strip()
                    if text and text not in bucket:
                        bucket.append(text)
            title = str(chunk.get("title") or "").strip()
            if title and title not in sample_titles:
                sample_titles.append(title)
        return {
            **(request_metadata or {}),
            "parser": parser or "unknown",
            "chunking_strategy": chunking_strategy or "dynamic_v1",
            "section_headings": headings[:10],
            "block_types": block_types[:8],
            "titles": sample_titles[:4],
        }

    def _upsert_document_source(
        self,
        scope: Scope,
        *,
        source_name: str,
        source_type: str,
        source_uri: str,
        parser: str | None,
        chunking_strategy: str | None,
        chunks: list[dict],
        memory_scope: MemoryScope,
        request_metadata: dict | None,
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        identity = self._document_source_scope_identity(scope, memory_scope)
        source_id = self._document_source_id(
            scope,
            source_uri,
            memory_scope=memory_scope,
            scope_ref=identity["scope_ref"],
        )
        source_hash = document_ingestion_service.build_document_fingerprint(
            source_name,
            source_uri,
            source_type,
            chunks,
            metadata=request_metadata or {},
        )
        registry_metadata = self._build_source_registry_metadata(
            chunks=chunks,
            parser=parser,
            chunking_strategy=chunking_strategy,
            request_metadata=request_metadata,
        )
        with session_scope() as session:
            row = session.get(DocumentSourceModel, source_id)
            unchanged = False
            if row is None:
                row = DocumentSourceModel(
                    source_id=source_id,
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                    memory_scope=memory_scope.value,
                    scope_ref=identity["scope_ref"],
                    conversation_id=identity["conversation_id"],
                    source_name=source_name,
                    source_uri=source_uri,
                    source_type=source_type,
                    parser_name=parser or "",
                    chunking_strategy=chunking_strategy or "",
                    content_hash=source_hash,
                    block_count=sum(int(chunk.get("metadata", {}).get("segment_count", 1) or 1) for chunk in chunks),
                    chunk_count=len(chunks),
                    status="indexed_pending_reflection",
                    metadata_json=registry_metadata,
                    created_at=now,
                    updated_at=now,
                    last_ingested_at=now,
                )
                session.add(row)
            else:
                unchanged = row.content_hash == source_hash and int(row.chunk_count or 0) == len(chunks)
                row.user_id = scope.user_id
                row.memory_scope = memory_scope.value
                row.scope_ref = identity["scope_ref"]
                row.conversation_id = identity["conversation_id"]
                row.source_name = source_name
                row.source_uri = source_uri
                row.source_type = source_type
                row.parser_name = parser or row.parser_name or ""
                row.chunking_strategy = chunking_strategy or row.chunking_strategy or ""
                row.content_hash = source_hash
                row.block_count = sum(int(chunk.get("metadata", {}).get("segment_count", 1) or 1) for chunk in chunks)
                row.chunk_count = len(chunks)
                row.metadata_json = registry_metadata
                row.status = "ready" if unchanged else "indexed_pending_reflection"
                row.updated_at = now
                row.last_ingested_at = now
        return {
            "source_id": source_id,
            "source_hash": source_hash,
            "scope_ref": identity["scope_ref"],
            "conversation_id": identity["conversation_id"],
            "source_status": "ready" if unchanged else "indexed_pending_reflection",
            "unchanged": unchanged,
        }

    def _upsert_ingestion_chunks(
        self,
        scope: Scope,
        *,
        source_id: str,
        source_name: str,
        source_type: str,
        source_uri: str,
        chunks: list[dict],
        stored_tags: list[str],
        parser: str | None,
        chunking_strategy: str | None,
        memory_scope: MemoryScope,
        scope_ref: str,
        conversation_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        created = 0
        updated = 0
        removed = 0
        unchanged = 0
        touched_ids: list[str] = []
        removed_ids: list[str] = []
        with session_scope() as session:
            existing_rows = (
                session.query(MemoryModel)
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    layer=MemoryLayer.LONG_TERM.value,
                    source="ingestion",
                    document_source_id=source_id,
                )
                .all()
            )
            existing_by_chunk_key = {str(row.chunk_key or ""): row for row in existing_rows if row.chunk_key}
            seen_chunk_keys: set[str] = set()
            for chunk in chunks:
                chunk_key = document_ingestion_service.build_chunk_key(
                    source_id=source_id,
                    source_uri=str(chunk.get("source_uri") or source_uri),
                    content=str(chunk.get("content") or ""),
                    metadata=chunk.get("metadata", {}) or {},
                )
                seen_chunk_keys.add(chunk_key)
                metadata = {
                    "kind": "document_chunk",
                    "source_id": source_id,
                    "source_name": source_name,
                    "source_uri": str(chunk.get("source_uri") or source_uri),
                    "source_type": source_type,
                    "title": chunk.get("title"),
                    "chunk_key": chunk_key,
                    **(chunk.get("metadata", {}) or {}),
                }
                if parser and "parser" not in metadata:
                    metadata["parser"] = parser
                if chunking_strategy and "chunking_strategy" not in metadata:
                    metadata["chunking_strategy"] = chunking_strategy
                embedding = embedding_service.embed_document(str(chunk.get("content") or ""))
                existing = existing_by_chunk_key.get(chunk_key)
                if existing is None:
                    session.add(
                        MemoryModel(
                            memory_id=str(uuid4()),
                            layer=MemoryLayer.LONG_TERM.value,
                            org_id=scope.org_id,
                            app_id=scope.app_id,
                            user_id=scope.user_id,
                            session_id=scope.session_id,
                            memory_scope=memory_scope.value,
                            scope_ref=scope_ref,
                            conversation_id=conversation_id,
                            promotion_status="direct",
                            content=str(chunk.get("content") or ""),
                            metadata_json=metadata,
                            embedding_json=embedding,
                            embedding_vector=embedding,
                            confidence=0.74,
                            tags_json=stored_tags,
                            source="ingestion",
                            document_source_id=source_id,
                            chunk_key=chunk_key,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    created += 1
                    continue
                existing_scope = MemoryScope(_normalize_memory_scope(existing.memory_scope))
                metadata_changed = self._sanitize_metadata(existing.metadata_json or {}) != self._sanitize_metadata(metadata)
                content_changed = existing.content != str(chunk.get("content") or "")
                tags_changed = list(existing.tags_json or []) != stored_tags
                scope_changed = existing_scope != memory_scope or (existing.scope_ref or "") != scope_ref or (existing.conversation_id or "") != conversation_id
                if not any((metadata_changed, content_changed, tags_changed, scope_changed)):
                    unchanged += 1
                    touched_ids.append(existing.memory_id)
                    continue
                existing.user_id = scope.user_id
                existing.session_id = scope.session_id
                existing.memory_scope = memory_scope.value
                existing.scope_ref = scope_ref
                existing.conversation_id = conversation_id
                existing.content = str(chunk.get("content") or "")
                existing.metadata_json = metadata
                existing.embedding_json = embedding
                existing.embedding_vector = embedding
                existing.confidence = max(float(existing.confidence or 0.0), 0.74)
                existing.tags_json = stored_tags
                existing.document_source_id = source_id
                existing.chunk_key = chunk_key
                existing.updated_at = now
                touched_ids.append(existing.memory_id)
                updated += 1
            for chunk_key, row in existing_by_chunk_key.items():
                if chunk_key in seen_chunk_keys:
                    continue
                removed_ids.append(row.memory_id)
                session.delete(row)
                removed += 1
        return {
            "created": created,
            "updated": updated,
            "removed": removed,
            "unchanged": unchanged,
            "touched_memory_ids": touched_ids,
            "removed_memory_ids": removed_ids,
        }

    def _prune_graph_evidence(
        self,
        scope: Scope,
        evidence_ids: list[str],
        *,
        memory_scope: MemoryScope,
        scope_ref: str,
        conversation_id: str,
    ) -> None:
        removed_ids = {evidence_id for evidence_id in evidence_ids if evidence_id}
        if not removed_ids:
            return
        with session_scope() as session:
            node_query = (
                session.query(GraphNodeModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id)
                .filter(
                    self._graph_node_target_filter(
                        scope,
                        memory_scope,
                        scope_ref=scope_ref,
                        conversation_id=conversation_id,
                    )
                )
            )
            deleted_node_ids: set[str] = set()
            for node in node_query.all():
                retained = [item for item in (node.evidence_ids_json or []) if item not in removed_ids]
                if len(retained) == len(node.evidence_ids_json or []):
                    continue
                if retained:
                    node.evidence_ids_json = retained
                    continue
                deleted_node_ids.add(node.node_id)
                session.delete(node)

            edge_query = (
                session.query(GraphEdgeModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id)
                .filter(
                    self._graph_edge_target_filter(
                        scope,
                        memory_scope,
                        scope_ref=scope_ref,
                        conversation_id=conversation_id,
                    )
                )
            )
            for edge in edge_query.all():
                retained = [item for item in (edge.evidence_ids_json or []) if item not in removed_ids]
                if edge.from_node in deleted_node_ids or edge.to_node in deleted_node_ids or not retained:
                    session.delete(edge)
                    continue
                if len(retained) != len(edge.evidence_ids_json or []):
                    edge.evidence_ids_json = retained

    def _mark_document_sources_reflected(self, evidence_items: list[dict]) -> None:
        source_ids = {
            str((item.get("metadata") or {}).get("source_id") or "").strip()
            for item in evidence_items
            if isinstance(item, dict)
        }
        source_ids = {source_id for source_id in source_ids if source_id}
        if not source_ids:
            return
        now = datetime.now(UTC)
        with session_scope() as session:
            rows = session.query(DocumentSourceModel).filter(DocumentSourceModel.source_id.in_(source_ids)).all()
            for row in rows:
                row.status = "ready"
                row.last_reflected_at = now
                row.updated_at = now

    def _set_document_source_status(self, source_id: str, status: str) -> None:
        if not source_id.strip():
            return
        now = datetime.now(UTC)
        with session_scope() as session:
            row = session.get(DocumentSourceModel, source_id)
            if row is None:
                return
            row.status = status
            row.updated_at = now

    def remember(self, record: MemoryRecord, *, schedule_graph_refresh: bool = True) -> MemoryRecord:
        record = self._hydrate_memory_scope(record)
        record.updated_at = datetime.now(UTC)
        if record.layer == MemoryLayer.SESSION:
            push_session_memory(_scope_key(record.scope), self._memory_to_payload(record))
            if schedule_graph_refresh:
                job_service.enqueue_reflection_if_due(record.scope, "session_memory_update", memory_scope=MemoryScope.CONVERSATION)
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
                    memory_scope=record.memory_scope.value,
                    scope_ref=record.scope_ref or "",
                    conversation_id=record.conversation_id or record.scope.session_id,
                    promotion_status=str(record.metadata.get("promotion_status", "direct")),
                    content=record.content,
                    metadata_json=record.metadata,
                    embedding_json=embedding,
                    embedding_vector=embedding,
                    confidence=record.confidence,
                    tags_json=record.tags,
                    source=record.source,
                    document_source_id=str(record.metadata.get("source_id") or "") or None,
                    chunk_key=str(record.metadata.get("chunk_key") or "") or None,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
        if schedule_graph_refresh and record.layer != MemoryLayer.RETRIEVAL_HINT:
            job_service.enqueue_reflection_if_due(record.scope, f"memory_update:{record.layer.value}", memory_scope=record.memory_scope)
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
                    conversation_id=event.scope.session_id,
                    role=event.role,
                    content=event.content,
                    outcome=event.outcome.value,
                    metadata_json=event.metadata,
                    created_at=event.created_at,
                )
            )
        job_service.enqueue_reflection_if_due(event.scope, "event_update", memory_scope=MemoryScope.CONVERSATION)
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

    def generate_reflection_artifact(
        self,
        scope: Scope,
        *,
        include_session_context: bool = True,
        include_event_context: bool = True,
    ):
        provider = resolve_provider(settings.default_provider)
        evidence_items = self._collect_reflection_evidence(
            scope,
            include_session_context=include_session_context,
            include_event_context=include_event_context,
        )
        transcript = self._build_reflection_context(scope, evidence_items=evidence_items)
        try:
            artifact = provider.reflect(transcript)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("memoryos").warning(
                "Reflection provider '%s' failed, falling back to heuristic: %s",
                provider.name,
                exc,
            )
            provider = provider_registry["heuristic"]
            artifact = provider.reflect(transcript)
        return provider, artifact, evidence_items

    def reflect(self, scope: Scope, *, memory_scope: MemoryScope = MemoryScope.APP) -> dict[str, str]:
        include_conversation_context = memory_scope == MemoryScope.CONVERSATION
        provider, artifact, evidence_items = self.generate_reflection_artifact(
            scope,
            include_session_context=include_conversation_context,
            include_event_context=include_conversation_context,
        )
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
                    memory_scope=memory_scope,
                ),
                schedule_graph_refresh=False,
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
                    memory_scope=memory_scope,
                ),
                schedule_graph_refresh=False,
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
                    memory_scope=memory_scope,
                ),
                schedule_graph_refresh=False,
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
                    memory_scope=memory_scope,
                ),
                schedule_graph_refresh=False,
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
                    memory_scope=memory_scope,
                ),
                schedule_graph_refresh=False,
            )
        graph_nodes, graph_edges = self.apply_reflection_graph(
            scope,
            artifact.entities,
            artifact.relations,
            evidence_items,
            graph_memory_scope=memory_scope,
        )
        job_id = str(uuid4())
        summary = artifact.summary or "Reflection completed."
        summary = f"{summary} Grounded {len(graph_nodes)} node{'s' if len(graph_nodes) != 1 else ''} and {len(graph_edges)} relation{'s' if len(graph_edges) != 1 else ''}."
        return {"job_id": job_id, "status": "completed", "summary": summary, "provider": provider.name}

    def apply_reflection_graph(
        self,
        scope: Scope,
        entities: list[tuple[str, str]],
        relations: list[tuple[str, str, str]],
        evidence_items: list[dict],
        *,
        graph_memory_scope: MemoryScope = MemoryScope.CONVERSATION,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        graph_nodes, graph_edges = self._build_grounded_graph_snapshot(
            scope,
            entities,
            relations,
            evidence_items,
            graph_memory_scope=graph_memory_scope,
        )
        self._merge_graph(graph_nodes, graph_edges)
        self._mark_document_sources_reflected(evidence_items)
        return graph_nodes, graph_edges

    def recall(self, scope: Scope, query: str, top_k: int, include_layers: list[MemoryLayer] | None) -> RecallResponse:
        original_query = re.sub(r"\s+", " ", query).strip()
        query_terms = self._tokenize_search_text(original_query)
        retrieval_plan = self._plan_retrieval(original_query, query_terms, include_layers)
        effective_query, rewrite_trace = self._rewrite_query_if_needed(scope, original_query, query_terms, retrieval_plan)
        if effective_query != original_query:
            query_terms = self._tokenize_search_text(effective_query)
            retrieval_plan = self._plan_retrieval(effective_query, query_terms, include_layers)
        layers = list(retrieval_plan["preferred_layers"])
        query_embedding = embedding_service.embed_query(effective_query)
        query_mode = str(retrieval_plan["query_mode"])
        candidates = self._load_memory_candidates(
            scope,
            layers,
            query_embedding,
            max(top_k * 12, 48),
            recent_limit=max(top_k * 10, 40),
        )
        if MemoryLayer.SESSION in layers:
            candidates.extend(self._load_session_records(scope))
        hint_signal = self._match_retrieval_hints(effective_query, query_terms, query_embedding, candidates, retrieval_plan)
        graph_signal = self._match_graph_context(scope, effective_query, query_terms, query_mode, retrieval_plan)
        if graph_signal["evidence_ids"]:
            candidates.extend(self._load_graph_evidence_candidates(scope, graph_signal["evidence_ids"], query_mode, retrieval_plan))

        candidates = self._deduplicate_candidates(candidates)
        query_term_weights = self._build_query_term_weights(query_terms, candidates)
        expansion_terms = self._merge_query_expansion_terms(
            query_terms,
            graph_signal["expansion_terms"],
            hint_signal["expansion_terms"],
        )
        expansion_term_weights = self._build_expansion_term_weights(expansion_terms, query_terms, candidates)

        scored: list[tuple[float, MemoryRecord]] = []
        now = datetime.now(UTC)
        for item in candidates:
            score = self._score_recall_candidate(
                item,
                effective_query,
                query_terms,
                query_term_weights,
                expansion_term_weights,
                query_embedding,
                query_mode,
                retrieval_plan,
                now,
            )
            scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        scored = self._rerank_recall_candidates(effective_query, scored)

        selected = self._select_recall_results(scored, top_k, query_terms, query_mode)
        selected = self._enforce_grounding_requirements(selected, retrieval_plan)

        return RecallResponse(
            items=[
                {
                    "memory_id": item.memory_id,
                    "layer": item.layer,
                    "content": item.content,
                    "confidence": item.confidence,
                    "tags": item.tags,
                    "metadata": self._build_recall_metadata(scope, item, score),
                    "created_at": item.created_at,
                }
                for score, item in selected
            ],
            trace=RetrievalTraceResponse(
                query=original_query,
                rewritten_query=rewrite_trace["rewritten_query"],
                query_rewrite_applied=bool(rewrite_trace["query_rewrite_applied"]),
                query_rewrite_reason=rewrite_trace["query_rewrite_reason"],
                layers_consulted=layers,
                query_mode=query_mode,
                query_intent=str(retrieval_plan["intent"]),
                scope_bias=str(retrieval_plan["scope_bias"]),
                graph_strategy=str(retrieval_plan["graph_strategy"]),
                grounding_policy=str(retrieval_plan["grounding_policy"]),
                freshness_bias=str(retrieval_plan["freshness_bias"]),
                preferred_layers=layers,
                expansion_terms=expansion_terms,
                ranking_factors=[
                    "query_plan",
                    "query_mode",
                    "document_chunk_bias",
                    "graph_neighborhood",
                    "embedding_similarity",
                    "keyword_coverage",
                    "metadata_match",
                    "phrase_match",
                    "retrieval_hints",
                    "cross_encoder_reranker",
                    "source_diversity",
                    "recency",
                    "confidence",
                ],
                reasons=[
                    f"Query planning classified this request as {retrieval_plan['intent']} with a {query_mode} retrieval mode, so memory layers and ranking signals are routed differently before retrieval begins.",
                    "Document chunks receive extra weight when query terms match content, titles, or section headings.",
                    "Embedding recall widens the candidate pool first, then grounded graph matches expand the evidence pool with connected memories so retrieval can follow relations instead of relying on isolated chunks.",
                    "Reflection-generated retrieval hints are treated as weak expansion signals instead of primary truth, so they help recall without dominating grounded evidence.",
                    "A cross-encoder reranker re-scores the strongest candidates as actual query-passage pairs before final selection, and source diversity prevents a single document from crowding out the rest.",
                    "Internal embedding vectors are removed from the response, and nearby chunk context is attached for document hits.",
                ],
                graph_matches=graph_signal["match_count"],
                graph_expansions=len(graph_signal["evidence_ids"]),
                retrieval_hint_matches=hint_signal["match_count"],
            ),
        )

    def _build_graph_evidence_preview(self, records: list[MemoryRecord], limit: int = 2) -> list[dict]:
        preview: list[dict] = []
        for record in records[: max(limit, 0)]:
            metadata = self._sanitize_metadata(record.metadata or {})
            title = (
                metadata.get("title")
                or metadata.get("source_name")
                or metadata.get("kind")
                or record.source
                or record.layer.value
            )
            preview.append(
                {
                    "evidence_id": record.memory_id,
                    "layer": record.layer.value,
                    "kind": str(metadata.get("kind", record.layer.value)),
                    "title": str(title),
                    "excerpt": _truncate(record.content, 220),
                    "source": record.source,
                    "memory_scope": record.memory_scope.value,
                    "created_at": record.created_at.isoformat(),
                }
            )
        return preview

    def _build_graph_scope_counts(self, scope: Scope) -> dict[str, dict[str, int]]:
        nodes = self._load_graph_nodes(scope)
        edges = self._load_graph_edges(scope)
        counts = {
            memory_scope.value: {"nodes": 0, "edges": 0}
            for memory_scope in MemoryScope
        }
        for node in nodes:
            counts[node.memory_scope.value]["nodes"] += 1
        for edge in edges:
            counts[edge.memory_scope.value]["edges"] += 1
        return counts

    def _build_graph_summary(self, nodes: list[GraphNode], edges: list[GraphEdge], evidence_records: list[MemoryRecord]) -> dict:
        connected_node_ids = {edge.from_node for edge in edges} | {edge.to_node for edge in edges}
        duplicate_labels = defaultdict(int)
        source_names: list[str] = []
        seen_sources: set[str] = set()

        for node in nodes:
            normalized_label = self._normalize_search_text(node.label)
            if normalized_label:
                duplicate_labels[normalized_label] += 1

        for record in evidence_records:
            metadata = self._sanitize_metadata(record.metadata or {})
            source_name = str(
                metadata.get("source_name")
                or metadata.get("title")
                or metadata.get("kind")
                or record.source
                or ""
            ).strip()
            if source_name and source_name not in seen_sources:
                seen_sources.add(source_name)
                source_names.append(source_name)

        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "evidence_count": len(evidence_records),
            "source_count": len(source_names),
            "orphan_node_count": sum(1 for node in nodes if node.node_id not in connected_node_ids),
            "duplicate_label_count": sum(1 for count in duplicate_labels.values() if count > 1),
            "ungrounded_node_count": sum(1 for node in nodes if not node.evidence_ids),
            "ungrounded_edge_count": sum(1 for edge in edges if not edge.evidence_ids),
            "source_names": source_names[:8],
        }

    def _build_graph_evidence_index(
        self,
        scope: Scope,
        *,
        memory_scope: MemoryScope | str | None,
    ) -> dict[str, dict[str, list[str]]]:
        nodes = self._load_graph_nodes(scope, memory_scope=memory_scope)
        edges = self._load_graph_edges(scope, memory_scope=memory_scope)
        node_by_id = {node.node_id: node for node in nodes}
        evidence_index: dict[str, dict[str, list[str]]] = {}

        def ensure_entry(evidence_id: str) -> dict[str, list[str]]:
            return evidence_index.setdefault(evidence_id, {"nodes": [], "relations": []})

        for node in nodes:
            for evidence_id in node.evidence_ids:
                if not evidence_id:
                    continue
                entry = ensure_entry(evidence_id)
                if node.label not in entry["nodes"]:
                    entry["nodes"].append(node.label)

        for edge in edges:
            from_node = node_by_id.get(edge.from_node)
            to_node = node_by_id.get(edge.to_node)
            relation_label = edge.relation.replace("_", " ")
            if from_node and to_node:
                relation_label = f"{from_node.label} {relation_label} {to_node.label}"
            for evidence_id in edge.evidence_ids:
                if not evidence_id:
                    continue
                entry = ensure_entry(evidence_id)
                if relation_label not in entry["relations"]:
                    entry["relations"].append(relation_label)

        return evidence_index

    def get_graph(
        self,
        scope: Scope,
        *,
        memory_scope: MemoryScope | str | None = MemoryScope.APP,
    ) -> dict[str, list[dict] | dict | str]:
        selected_scope = self._resolve_memory_scope(memory_scope, default=MemoryScope.APP) or MemoryScope.APP
        nodes = self._load_graph_nodes(scope, memory_scope=selected_scope)
        edges = self._load_graph_edges(scope, memory_scope=selected_scope)
        evidence_ids: list[str] = []
        for node in nodes:
            evidence_ids.extend(node.evidence_ids or [])
        for edge in edges:
            evidence_ids.extend(edge.evidence_ids or [])
        evidence_records = self._load_evidence_records(scope, evidence_ids)
        evidence_map = {record.memory_id: record for record in evidence_records}

        return {
            "memory_scope": selected_scope.value,
            "scope_counts": self._build_graph_scope_counts(scope),
            "summary": self._build_graph_summary(nodes, edges, evidence_records),
            "nodes": [
                {
                    "node_id": node.node_id,
                    "label": node.label,
                    "node_type": node.node_type,
                    "confidence": node.confidence,
                    "evidence_ids": node.evidence_ids,
                    "metadata": node.metadata,
                    "memory_scope": node.memory_scope.value,
                    "scope_ref": node.scope_ref,
                    "conversation_id": node.conversation_id,
                    "evidence_preview": self._build_graph_evidence_preview(
                        [evidence_map[evidence_id] for evidence_id in node.evidence_ids if evidence_id in evidence_map]
                    ),
                }
                for node in nodes
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
                    "memory_scope": edge.memory_scope.value,
                    "scope_ref": edge.scope_ref,
                    "conversation_id": edge.conversation_id,
                    "evidence_preview": self._build_graph_evidence_preview(
                        [evidence_map[evidence_id] for evidence_id in edge.evidence_ids if evidence_id in evidence_map]
                    ),
                }
                for edge in edges
            ],
        }

    def ingest_documents(
        self,
        scope: Scope,
        source_name: str,
        chunks: list[dict],
        *,
        tags: list[str] | None = None,
        source_type: str = "manual_text",
        source_uri: str | None = None,
        source_metadata: dict | None = None,
        parser: str | None = None,
        chunking_strategy: str | None = None,
        memory_scope: MemoryScope = MemoryScope.APP,
    ) -> dict[str, str | int]:
        normalized_tags = [tag.strip() for tag in (tags or []) if isinstance(tag, str) and tag.strip()]
        stored_tags = list(dict.fromkeys(["ingested", "enterprise_knowledge", *normalized_tags]))
        resolved_source_uri = self._resolve_source_uri(source_name, chunks, explicit_source_uri=source_uri)
        source_state = self._upsert_document_source(
            scope,
            source_name=source_name,
            source_type=source_type,
            source_uri=resolved_source_uri,
            parser=parser,
            chunking_strategy=chunking_strategy,
            chunks=chunks,
            memory_scope=memory_scope,
            request_metadata=source_metadata,
        )
        if bool(source_state["unchanged"]):
            return {
                "job_id": str(uuid4()),
                "chunks_received": len(chunks),
                "status": "skipped",
                "parser": parser or "unknown",
                "source_type": source_type,
                "chunking_strategy": chunking_strategy or "dynamic_v1",
                "source_id": str(source_state["source_id"]),
                "source_status": str(source_state["source_status"]),
                "skipped": True,
                "chunks_created": 0,
                "chunks_updated": 0,
                "chunks_removed": 0,
            }
        chunk_state = self._upsert_ingestion_chunks(
            scope,
            source_id=str(source_state["source_id"]),
            source_name=source_name,
            source_type=source_type,
            source_uri=resolved_source_uri,
            chunks=chunks,
            stored_tags=stored_tags,
            parser=parser,
            chunking_strategy=chunking_strategy,
            memory_scope=memory_scope,
            scope_ref=str(source_state["scope_ref"]),
            conversation_id=str(source_state["conversation_id"]),
        )
        if chunk_state["removed_memory_ids"]:
            self._prune_graph_evidence(
                scope,
                chunk_state["removed_memory_ids"],
                memory_scope=memory_scope,
                scope_ref=str(source_state["scope_ref"]),
                conversation_id=str(source_state["conversation_id"]),
            )
        if chunk_state["created"] or chunk_state["updated"] or chunk_state["removed"]:
            job_service.enqueue_reflection_if_due(scope, f"ingestion:{source_type}", memory_scope=memory_scope)
        else:
            self._set_document_source_status(str(source_state["source_id"]), "ready")
            source_state["source_status"] = "ready"
        return {
            "job_id": str(uuid4()),
            "chunks_received": len(chunks),
            "status": "queued",
            "parser": parser or "unknown",
            "source_type": source_type,
            "chunking_strategy": chunking_strategy or "dynamic_v1",
            "source_id": str(source_state["source_id"]),
            "source_status": str(source_state["source_status"]),
            "skipped": False,
            "chunks_created": int(chunk_state["created"]),
            "chunks_updated": int(chunk_state["updated"]),
            "chunks_removed": int(chunk_state["removed"]),
        }

    def timeline(
        self,
        scope: Scope,
        limit: int = 30,
        *,
        graph_memory_scope: MemoryScope | str | None = MemoryScope.APP,
    ) -> TimelineResponse:
        with session_scope() as session:
            memory_rows = (
                session.query(MemoryModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id, user_id=scope.user_id)
                .filter(MemoryModel.conversation_id == scope.session_id)
                .order_by(MemoryModel.created_at.desc())
                .limit(limit)
                .all()
            )
            event_rows = (
                session.query(EventModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id, user_id=scope.user_id)
                .filter(EventModel.conversation_id == scope.session_id)
                .order_by(EventModel.created_at.desc())
                .limit(limit)
                .all()
            )
        session_rows = self._load_session_records(scope)[:limit]
        graph_evidence_index = self._build_graph_evidence_index(scope, memory_scope=graph_memory_scope)

        def decorate_timeline_metadata(item_id: str, metadata: dict) -> dict:
            graph_refs = graph_evidence_index.get(item_id)
            if not graph_refs:
                return metadata
            return metadata | {
                "graph_linked": True,
                "graph_node_count": len(graph_refs["nodes"]),
                "graph_edge_count": len(graph_refs["relations"]),
                "graph_nodes": graph_refs["nodes"][:4],
                "graph_relations": graph_refs["relations"][:4],
                "graph_memory_scope": (self._resolve_memory_scope(graph_memory_scope, default=MemoryScope.APP) or MemoryScope.APP).value,
            }

        items = [
            {
                "item_id": row.memory_id,
                "item_type": "memory",
                "content": row.content,
                "layer": row.layer,
                "created_at": row.created_at,
                "metadata": decorate_timeline_metadata(row.memory_id, row.metadata_json or {}),
            }
            for row in memory_rows
        ] + [
            {
                "item_id": row.memory_id,
                "item_type": "session_memory",
                "content": row.content,
                "layer": row.layer.value,
                "created_at": row.created_at,
                "metadata": decorate_timeline_metadata(
                    row.memory_id,
                    {key: value for key, value in row.metadata.items() if not key.startswith("_")},
                ),
            }
            for row in session_rows
        ] + [
            {
                "item_id": row.event_id,
                "item_type": "event",
                "content": f"{row.role}: {row.content}",
                "layer": "event",
                "created_at": row.created_at,
                "metadata": decorate_timeline_metadata(row.event_id, row.metadata_json or {}),
            }
            for row in event_rows
        ]
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return TimelineResponse(items=items[:limit])

    def list_sessions(self, scope: Scope, limit: int = 50) -> list[dict]:
        with session_scope() as session:
            memory_rows = (
                session.query(
                    MemoryModel.conversation_id.label("session_id"),
                    func.count(MemoryModel.memory_id).label("memory_count"),
                    func.max(MemoryModel.updated_at).label("last_activity_at"),
                )
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                )
                .filter(MemoryModel.memory_scope == MemoryScope.CONVERSATION.value)
                .group_by(MemoryModel.conversation_id)
                .all()
            )
            event_rows = (
                session.query(
                    EventModel.conversation_id.label("session_id"),
                    func.count(EventModel.event_id).label("event_count"),
                    func.max(EventModel.created_at).label("last_activity_at"),
                )
                .filter_by(
                    org_id=scope.org_id,
                    app_id=scope.app_id,
                    user_id=scope.user_id,
                )
                .group_by(EventModel.conversation_id)
                .all()
            )
            conversation_rows = (
                session.query(ConversationModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id, user_id=scope.user_id)
                .order_by(ConversationModel.updated_at.desc())
                .limit(max(limit * 3, 60))
                .all()
            )
            agent_ids = [row.agent_id for row in conversation_rows if row.agent_id]
            agents = {
                row.agent_id: row
                for row in session.query(AgentModel)
                .filter(AgentModel.agent_id.in_(agent_ids or [""]))
                .all()
            }

        session_index: dict[str, dict] = defaultdict(
            lambda: {
                "session_id": "",
                "memory_count": 0,
                "event_count": 0,
                "last_activity_at": None,
                "title": None,
                "status": None,
                "agent_id": None,
            }
        )
        for row in memory_rows:
            entry = session_index[row.session_id]
            entry["session_id"] = row.session_id
            entry["memory_count"] = int(row.memory_count or 0)
            entry["last_activity_at"] = row.last_activity_at

        for row in event_rows:
            entry = session_index[row.session_id]
            entry["session_id"] = row.session_id
            entry["event_count"] = int(row.event_count or 0)
            if entry["last_activity_at"] is None or (row.last_activity_at and row.last_activity_at > entry["last_activity_at"]):
                entry["last_activity_at"] = row.last_activity_at

        for row in conversation_rows:
            entry = session_index[row.conversation_id]
            entry["session_id"] = row.conversation_id
            entry["title"] = row.title
            entry["status"] = row.status
            agent = agents.get(row.agent_id)
            entry["agent_id"] = (agent.public_agent_id or row.agent_id) if agent is not None else row.agent_id
            if entry["last_activity_at"] is None or (row.updated_at and row.updated_at > entry["last_activity_at"]):
                entry["last_activity_at"] = row.updated_at

        if scope.session_id and scope.session_id not in session_index:
            session_index[scope.session_id] = {
                "session_id": scope.session_id,
                "memory_count": 0,
                "event_count": 0,
                "last_activity_at": None,
                "title": None,
                "status": None,
                "agent_id": None,
            }

        sessions = sorted(
            session_index.values(),
            key=lambda item: (
                item["last_activity_at"] is not None,
                item["last_activity_at"] or datetime.min.replace(tzinfo=UTC),
                item["session_id"],
            ),
            reverse=True,
        )
        return sessions[: max(limit, 1)]

    def _memory_to_payload(self, record: MemoryRecord) -> dict:
        return {
            "memory_id": record.memory_id,
            "layer": record.layer.value,
            "content": record.content,
            "confidence": record.confidence,
            "tags": record.tags,
            "metadata": record.metadata,
            "source": record.source,
            "memory_scope": record.memory_scope.value,
            "scope_ref": record.scope_ref,
            "conversation_id": record.conversation_id,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    def _collect_reflection_evidence(
        self,
        scope: Scope,
        *,
        include_session_context: bool = True,
        include_event_context: bool = True,
    ) -> list[dict]:
        evidence_limit = max(settings.graph_evidence_limit, 12)
        durable_limit = max(evidence_limit * 2, 36)
        if not include_session_context and not include_event_context:
            durable_limit = max(evidence_limit * 6, 72)
        session_records = (
            sorted(self._load_session_records(scope), key=lambda record: record.created_at)[-12:]
            if include_session_context
            else []
        )

        with session_scope() as session:
            event_rows = []
            if include_event_context:
                event_rows = (
                    session.query(EventModel)
                    .filter_by(org_id=scope.org_id, app_id=scope.app_id, user_id=scope.user_id)
                    .filter(EventModel.conversation_id == scope.session_id)
                    .order_by(EventModel.created_at.desc())
                    .limit(18)
                    .all()
                )
            durable_rows = (
                session.query(MemoryModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id)
                .filter(self._memory_scope_filter(scope))
                .filter(MemoryModel.layer.in_([MemoryLayer.LONG_TERM.value, MemoryLayer.FAILURE.value, MemoryLayer.RESOLUTION.value]))
                .order_by(MemoryModel.updated_at.desc())
                .limit(durable_limit)
                .all()
            )

        evidence_items: list[dict] = []
        for row in reversed(event_rows):
            evidence_items.append(
                {
                    "evidence_id": row.event_id,
                    "kind": "event",
                    "title": row.role,
                    "text": f"{row.role}: {row.content}",
                    "created_at": row.created_at,
                }
            )

        for record in session_records:
            evidence_items.append(
                {
                    "evidence_id": record.memory_id,
                    "kind": "session",
                    "title": record.source,
                    "text": record.content,
                    "created_at": record.created_at,
                }
            )

        for row in durable_rows:
            metadata = row.metadata_json or {}
            if metadata.get("generated_by") or row.source == "reflection":
                continue
            title = metadata.get("title") or metadata.get("source_name") or row.source or "memory"
            sections = metadata.get("section_headings") or metadata.get("sheet_names") or metadata.get("page_numbers")
            section_text = f" sections={sections}" if sections else ""
            evidence_items.append(
                {
                    "evidence_id": row.memory_id,
                    "kind": metadata.get("kind", row.layer),
                    "title": f"{title}{section_text}",
                    "text": row.content,
                    "created_at": row.created_at,
                }
            )

        evidence_items.sort(key=lambda item: item["created_at"])
        return evidence_items[-evidence_limit:]

    def _build_reflection_context(
        self,
        scope: Scope,
        *,
        evidence_items: list[dict] | None = None,
        character_limit: int = 18_000,
    ) -> str:
        evidence = evidence_items or self._collect_reflection_evidence(scope)
        parts: list[str] = []
        remaining = character_limit

        def append_entry(entry: str) -> None:
            nonlocal remaining
            if remaining <= 0:
                return
            cleaned = entry.strip()
            if not cleaned:
                return
            if len(cleaned) > remaining:
                if remaining <= 3:
                    return
                cleaned = cleaned[: remaining - 3].rstrip() + "..."
            parts.append(cleaned)
            remaining -= len(cleaned) + 2

        append_entry(
            "Reflection scope: "
            f"org={scope.org_id}, app={scope.app_id}, user={scope.user_id}, session={scope.session_id}"
        )
        append_entry("Ground the graph only on the evidence below.")
        for item in evidence:
            append_entry(self._format_reflection_evidence(item))

        if len(parts) <= 2:
            append_entry("No meaningful memories were available for reflection.")
        return "\n".join(parts)

    def _format_reflection_evidence(self, item: dict) -> str:
        kind = item.get("kind", "memory")
        title = item.get("title") or "memory"
        return f"[evidence:{item['evidence_id']}:{kind}:{title}] {item['text']}"

    def _build_grounded_graph_snapshot(
        self,
        scope: Scope,
        entities: list[tuple[str, str]],
        relations: list[tuple[str, str, str]],
        evidence_items: list[dict],
        *,
        graph_memory_scope: MemoryScope = MemoryScope.CONVERSATION,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        node_candidates: dict[str, dict] = {}
        for raw_label, raw_node_type in entities:
            label = self._clean_graph_label(raw_label)
            if not label:
                continue
            support = self._find_entity_support(label, evidence_items)
            if not support:
                continue

            key = self._normalize_search_text(label)
            support_ids = [item["evidence_id"] for item in support[:4]]
            confidence = min(0.96, 0.62 + len(support_ids) * 0.08)
            entry = node_candidates.get(key)
            metadata = {
                "grounded": True,
                "support_count": len(support_ids),
                "supporting_excerpt": support[0]["excerpt"],
            }
            node_type = self._normalize_graph_node_type(raw_node_type, label)
            if entry is None or confidence > entry["confidence"]:
                node_candidates[key] = {
                    "label": label,
                    "node_type": node_type,
                    "confidence": confidence,
                    "evidence_ids": support_ids,
                    "metadata": metadata,
                }

        edge_candidates: dict[tuple[str, str, str], dict] = {}
        for raw_source, raw_target, raw_relation in relations:
            source_key = self._normalize_search_text(self._clean_graph_label(raw_source))
            target_key = self._normalize_search_text(self._clean_graph_label(raw_target))
            if not source_key or not target_key or source_key == target_key:
                continue
            if source_key not in node_candidates or target_key not in node_candidates:
                continue

            source_label = node_candidates[source_key]["label"]
            target_label = node_candidates[target_key]["label"]
            support = self._find_relation_support(source_label, target_label, evidence_items)
            if not support:
                continue

            relation_name = self._ground_relation_name(raw_relation, support[0]["search_text"])
            edge_key = (source_key, target_key, relation_name)
            support_ids = [item["evidence_id"] for item in support[:4]]
            confidence = min(0.94, 0.6 + len(support_ids) * 0.1)
            edge_candidates[edge_key] = {
                "from_key": source_key,
                "to_key": target_key,
                "relation": relation_name,
                "confidence": confidence,
                "evidence_ids": support_ids,
                "metadata": {
                    "grounded": True,
                    "support_count": len(support_ids),
                    "supporting_excerpt": support[0]["excerpt"],
                },
            }

        ranked_edges = sorted(
            edge_candidates.values(),
            key=lambda edge: (edge["metadata"]["support_count"], edge["confidence"]),
            reverse=True,
        )[: settings.graph_max_edges]

        referenced_keys = {edge["from_key"] for edge in ranked_edges} | {edge["to_key"] for edge in ranked_edges}
        ranked_nodes = sorted(
            node_candidates.items(),
            key=lambda pair: (pair[1]["metadata"]["support_count"], pair[1]["confidence"]),
            reverse=True,
        )

        selected_nodes: dict[str, GraphNode] = {}
        for key, candidate in ranked_nodes:
            if key in referenced_keys or len(selected_nodes) < min(settings.graph_max_nodes, 6):
                selected_nodes[key] = GraphNode(
                    scope=scope,
                    label=candidate["label"],
                    node_type=candidate["node_type"],
                    confidence=candidate["confidence"],
                    evidence_ids=candidate["evidence_ids"],
                    metadata=candidate["metadata"],
                    memory_scope=graph_memory_scope,
                )
            if len(selected_nodes) >= settings.graph_max_nodes:
                break

        graph_edges: list[GraphEdge] = []
        for candidate in ranked_edges:
            if candidate["from_key"] not in selected_nodes or candidate["to_key"] not in selected_nodes:
                continue
            graph_edges.append(
                GraphEdge(
                    scope=scope,
                    from_node=selected_nodes[candidate["from_key"]].node_id,
                    to_node=selected_nodes[candidate["to_key"]].node_id,
                    relation=candidate["relation"],
                    confidence=candidate["confidence"],
                    evidence_ids=candidate["evidence_ids"],
                    metadata=candidate["metadata"],
                    memory_scope=graph_memory_scope,
                )
            )

        connected_node_ids = {edge.from_node for edge in graph_edges} | {edge.to_node for edge in graph_edges}
        graph_nodes = [node for node in selected_nodes.values() if node.node_id in connected_node_ids]
        if not graph_nodes:
            graph_nodes = list(selected_nodes.values())[: min(settings.graph_max_nodes, 8)]
        return graph_nodes, graph_edges

    def _find_entity_support(self, label: str, evidence_items: list[dict]) -> list[dict]:
        normalized_label = self._normalize_search_text(label)
        label_terms = [term for term in self._tokenize_search_text(label) if len(term) > 2]
        support: list[dict] = []
        for item in evidence_items:
            search_text = self._normalize_search_text(f"{item.get('title', '')} {item.get('text', '')}")
            if not search_text:
                continue
            matched = normalized_label in search_text
            if not matched and label_terms:
                matched = all(term in search_text for term in label_terms[: min(len(label_terms), 3)])
            if not matched:
                continue
            support.append(
                {
                    "evidence_id": item["evidence_id"],
                    "excerpt": self._extract_support_excerpt(item.get("text", ""), label_terms or [normalized_label]),
                    "search_text": search_text,
                }
            )
        return support

    def _find_relation_support(self, source_label: str, target_label: str, evidence_items: list[dict]) -> list[dict]:
        source_terms = [term for term in self._tokenize_search_text(source_label) if len(term) > 2]
        target_terms = [term for term in self._tokenize_search_text(target_label) if len(term) > 2]
        support: list[dict] = []
        for item in evidence_items:
            search_text = self._normalize_search_text(f"{item.get('title', '')} {item.get('text', '')}")
            if not search_text:
                continue
            source_present = source_label.lower() in search_text or (
                bool(source_terms) and all(term in search_text for term in source_terms[: min(len(source_terms), 3)])
            )
            target_present = target_label.lower() in search_text or (
                bool(target_terms) and all(term in search_text for term in target_terms[: min(len(target_terms), 3)])
            )
            if not (source_present and target_present):
                continue
            support.append(
                {
                    "evidence_id": item["evidence_id"],
                    "excerpt": self._extract_support_excerpt(item.get("text", ""), source_terms + target_terms),
                    "search_text": search_text,
                }
            )
        return support

    def _extract_support_excerpt(self, text: str, terms: list[str], window: int = 220) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        lowered = cleaned.lower()
        for term in terms:
            if not term:
                continue
            position = lowered.find(term.lower())
            if position < 0:
                continue
            start = max(position - window // 3, 0)
            end = min(position + window, len(cleaned))
            excerpt = cleaned[start:end].strip()
            if start > 0:
                excerpt = "..." + excerpt
            if end < len(cleaned):
                excerpt = excerpt + "..."
            return excerpt
        return cleaned[:window] + ("..." if len(cleaned) > window else "")

    def _clean_graph_label(self, label: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(label or "").strip(" \t\r\n.,:;()[]{}"))
        if len(cleaned) < 2 or len(cleaned) > 96:
            return ""
        if cleaned.lower() in {"user", "assistant", "memory", "event", "session"}:
            return ""
        if sum(character.isalpha() for character in cleaned) < 2:
            return ""
        return cleaned

    def _normalize_graph_node_type(self, node_type: str, label: str) -> str:
        cleaned = re.sub(r"[^a-z0-9_ -]+", "", str(node_type or "").strip().lower()).replace(" ", "_")
        if cleaned in {"person", "organization", "system", "document", "concept", "policy", "team"}:
            return cleaned
        lower_label = label.lower()
        if any(keyword in lower_label for keyword in ("policy", "handbook", "document", "guide", "manual")):
            return "document"
        if any(keyword in lower_label for keyword in ("department", "company", "team", "organization", "committee")):
            return "organization"
        if any(keyword in lower_label for keyword in ("api", "mcp", "memoryos", "dashboard", "service", "system")):
            return "system"
        return "concept"

    def _ground_relation_name(self, relation: str, evidence_text: str) -> str:
        raw = re.sub(r"[^a-z0-9_ -]+", "", str(relation or "").strip().lower()).replace(" ", "_")
        normalized = raw or "related_to"
        if normalized in {"reports_to", "reporting_to"}:
            return "reports_to" if "reports to" in evidence_text else "related_to"
        if normalized in {"uses", "use", "depends_on", "connected_to"}:
            if normalized.startswith("use") and "use" in evidence_text:
                return "uses"
            if normalized == "depends_on" and ("depend" in evidence_text or "requires" in evidence_text):
                return "depends_on"
            if normalized == "connected_to" and ("connected" in evidence_text or "link" in evidence_text):
                return "connected_to"
            return "related_to"
        if normalized in {"belongs_to", "part_of"}:
            if "part of" in evidence_text or "belongs to" in evidence_text:
                return "part_of" if "part of" in evidence_text else "belongs_to"
            return "related_to"
        if normalized in {"mentions", "describes"}:
            return normalized
        return "related_to"

    def _infer_query_mode(self, query: str, query_terms: list[str]) -> str:
        normalized_query = self._normalize_search_text(query)
        local_markers = {"who", "when", "where", "which", "exact", "name", "find", "show", "list", "tell", "describe", "explain"}
        local_phrases = {"tell me about", "describe the", "describe this", "explain the", "explain this", "who is", "what is"}
        global_markers = {
            "how",
            "why",
            "overall",
            "across",
            "architecture",
            "workflow",
            "relationship",
            "relationships",
            "compare",
            "summary",
            "strategy",
            "improve",
            "improvement",
        }
        global_phrases = {"root cause", "big picture", "over time", "end to end"}
        local_score = 1 if len(query_terms) <= 4 else 0
        global_score = 1 if len(query_terms) >= 8 else 0

        if any(term in local_markers for term in query_terms):
            local_score += 2
        if any(phrase in normalized_query for phrase in local_phrases):
            local_score += 2
        if any(term in global_markers for term in query_terms):
            global_score += 2
        if any(phrase in normalized_query for phrase in global_phrases):
            global_score += 2
        if "graph" in query_terms or "relation" in query_terms or "relations" in query_terms:
            global_score += 1

        if local_score >= global_score + 2:
            return "local"
        if global_score >= local_score + 1:
            return "global"
        return "hybrid"

    def _default_recall_layers(self, query_mode: str, intent: str) -> list[MemoryLayer]:
        if intent == "troubleshooting":
            return [
                MemoryLayer.RESOLUTION,
                MemoryLayer.FAILURE,
                MemoryLayer.LONG_TERM,
                MemoryLayer.EVENT,
                MemoryLayer.SESSION,
                MemoryLayer.RETRIEVAL_HINT,
            ]
        if intent == "personalization":
            return [
                MemoryLayer.SESSION,
                MemoryLayer.LONG_TERM,
                MemoryLayer.EVENT,
                MemoryLayer.RESOLUTION,
                MemoryLayer.FAILURE,
                MemoryLayer.RETRIEVAL_HINT,
            ]
        if intent in {"policy_lookup", "reference_lookup", "entity_lookup"}:
            return [
                MemoryLayer.LONG_TERM,
                MemoryLayer.RESOLUTION,
                MemoryLayer.FAILURE,
                MemoryLayer.RETRIEVAL_HINT,
            ]
        if query_mode == "global":
            return [
                MemoryLayer.LONG_TERM,
                MemoryLayer.RESOLUTION,
                MemoryLayer.FAILURE,
                MemoryLayer.SESSION,
                MemoryLayer.EVENT,
                MemoryLayer.RETRIEVAL_HINT,
            ]
        return [
            MemoryLayer.SESSION,
            MemoryLayer.EVENT,
            MemoryLayer.LONG_TERM,
            MemoryLayer.FAILURE,
            MemoryLayer.RESOLUTION,
            MemoryLayer.RETRIEVAL_HINT,
        ]

    def _plan_retrieval(
        self,
        query: str,
        query_terms: list[str],
        include_layers: list[MemoryLayer] | None,
    ) -> dict[str, object]:
        query_mode = self._infer_query_mode(query, query_terms)
        normalized_query = self._normalize_search_text(query)

        troubleshooting_markers = {
            "error",
            "failed",
            "failure",
            "incident",
            "broken",
            "issue",
            "bug",
            "fix",
            "debug",
            "outage",
            "root",
            "cause",
            "resolve",
            "resolution",
        }
        policy_markers = {
            "policy",
            "handbook",
            "runbook",
            "playbook",
            "guide",
            "manual",
            "document",
            "docs",
            "api",
            "endpoint",
            "schema",
            "contract",
            "spec",
        }
        personalization_markers = {
            "my",
            "mine",
            "preference",
            "prefer",
            "preferred",
            "personal",
            "custom",
            "setting",
            "settings",
        }
        personalization_phrases = {
            "what do i like",
            "what do i prefer",
            "my preference",
            "my preferences",
            "my setting",
            "my settings",
        }
        lookup_markers = {"who", "what", "where", "when", "which", "find", "show", "list", "name", "tell", "describe", "explain"}
        lookup_phrases = {"tell me about", "describe the", "describe this", "explain the", "explain this", "who is", "what is"}
        freshness_markers = {"latest", "current", "recent", "new", "updated", "today", "now", "currently"}
        workflow_markers = {"workflow", "process", "across", "relationship", "relationships", "architecture", "improve", "strategy"}
        strict_grounding_markers = {"exact", "quote", "quoted", "verbatim", "source", "evidence", "documented"}
        title_markers = {
            "ceo",
            "cto",
            "cfo",
            "coo",
            "cio",
            "ciso",
            "cmo",
            "chro",
            "chairman",
            "director",
            "manager",
            "president",
            "vp",
            "head",
            "hod",
            "hr",
        }

        has_troubleshooting = any(term in troubleshooting_markers for term in query_terms) or "root cause" in normalized_query
        has_policy = any(term in policy_markers for term in query_terms)
        has_personalization = any(term in personalization_markers for term in query_terms) or any(
            phrase in normalized_query for phrase in personalization_phrases
        )
        has_lookup = any(term in lookup_markers for term in query_terms) or any(phrase in normalized_query for phrase in lookup_phrases)
        has_freshness = any(term in freshness_markers for term in query_terms)
        has_workflow = query_mode == "global" or any(term in workflow_markers for term in query_terms)
        has_title_lookup = any(term in title_markers for term in query_terms)
        strict_grounding = (
            has_policy
            or any(term in strict_grounding_markers for term in query_terms)
            or "what is our policy" in normalized_query
            or "according to" in normalized_query
        )

        intent = "general"
        if has_troubleshooting:
            intent = "troubleshooting"
        elif has_personalization:
            intent = "personalization"
        elif has_policy:
            intent = "policy_lookup"
        elif has_title_lookup or (has_lookup and len(query_terms) <= 2 and query_mode != "global"):
            intent = "entity_lookup"
        elif has_lookup and query_mode == "local":
            intent = "reference_lookup"
        elif has_workflow:
            intent = "workflow_reasoning"

        scope_bias = "balanced"
        if intent == "personalization":
            scope_bias = "session"
        elif intent in {"policy_lookup", "reference_lookup", "workflow_reasoning", "entity_lookup"}:
            scope_bias = "shared"

        graph_strategy = "focused"
        if intent in {"workflow_reasoning", "troubleshooting"} and query_mode != "local":
            graph_strategy = "expanded"

        grounding_policy = "strict" if strict_grounding or intent == "entity_lookup" else "balanced"
        freshness_bias = "high" if has_freshness else "normal"
        preferred_layers = include_layers or self._default_recall_layers(query_mode, intent)

        recency_multiplier = 1.0
        if freshness_bias == "high":
            recency_multiplier = 1.8
        elif intent == "troubleshooting":
            recency_multiplier = 1.35

        return {
            "query_mode": query_mode,
            "intent": intent,
            "scope_bias": scope_bias,
            "graph_strategy": graph_strategy,
            "grounding_policy": grounding_policy,
            "freshness_bias": freshness_bias,
            "preferred_layers": preferred_layers,
            "document_bias": 0.54 if intent in {"policy_lookup", "reference_lookup", "entity_lookup"} else 0.24,
            "session_bias": 0.28 if intent == "personalization" else 0.12 if intent == "troubleshooting" else 0.0,
            "shared_bias": 0.18 if scope_bias == "shared" else 0.0,
            "resolution_bias": 0.24 if intent == "troubleshooting" else 0.1 if query_mode == "global" else 0.0,
            "failure_bias": 0.18 if intent == "troubleshooting" else 0.08 if query_mode == "global" else 0.0,
            "exact_phrase_bias": 0.35 if grounding_policy == "strict" else 0.0,
            "hint_policy": "weak" if grounding_policy == "strict" else "normal",
            "recency_multiplier": recency_multiplier,
        }

    def _is_vague_query(self, query: str, query_terms: list[str], retrieval_plan: dict[str, object]) -> bool:
        normalized_query = self._normalize_search_text(query)
        exact_vague_phrases = {
            "help",
            "need help",
            "tell me more",
            "what about this",
            "what about that",
            "what about it",
            "can you help",
            "explain this",
            "explain that",
            "what next",
            "any update",
        }
        generic_terms = {
            "help",
            "more",
            "this",
            "that",
            "it",
            "thing",
            "things",
            "stuff",
            "something",
            "anything",
            "about",
            "tell",
            "explain",
            "show",
            "find",
            "what",
            "which",
            "who",
            "how",
            "why",
            "need",
            "want",
            "can",
            "could",
            "would",
            "should",
            "please",
            "info",
            "information",
            "details",
            "update",
        }
        pronouns = {"this", "that", "it", "they", "them", "these", "those"}

        if normalized_query in exact_vague_phrases:
            return True
        informative_terms = [term for term in query_terms if term not in generic_terms and len(term) >= 4]
        if len(informative_terms) >= 2:
            return False
        if any(term in pronouns for term in query_terms) and len(query_terms) <= 6:
            return True
        if len(query_terms) <= 2 and retrieval_plan.get("intent") in {"general", "reference_lookup"}:
            return True
        return False

    def _build_query_rewrite_context(self, scope: Scope) -> str:
        context_entries: list[str] = []
        seen_entries: set[str] = set()

        for node in sorted(self._load_graph_nodes(scope), key=lambda item: (len(item.evidence_ids), item.confidence), reverse=True)[:8]:
            entry = f"entity: {node.label}"
            if entry not in seen_entries:
                seen_entries.add(entry)
                context_entries.append(entry)

        with session_scope() as session:
            rows = (
                session.query(DocumentSourceModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id)
                .filter(self._document_source_scope_filter(scope))
                .order_by(
                    DocumentSourceModel.last_reflected_at.desc().nullslast(),
                    DocumentSourceModel.updated_at.desc(),
                )
                .limit(12)
                .all()
            )
        for row in rows:
            metadata = row.metadata_json or {}
            source_name = str(row.source_name or "").strip()
            if not source_name:
                continue
            entry = f"source: {source_name}"
            if entry not in seen_entries:
                seen_entries.add(entry)
                context_entries.append(entry)
            headings = metadata.get("section_headings") or []
            if isinstance(headings, list) and headings:
                heading_entry = f"sections: {', '.join(str(part).strip() for part in headings[:3] if str(part).strip())}"
                if heading_entry not in seen_entries and heading_entry != "sections: ":
                    seen_entries.add(heading_entry)
                    context_entries.append(heading_entry)
            if len(context_entries) >= 12:
                break

        return "\n".join(context_entries[:12])

    def _rewrite_query_if_needed(
        self,
        scope: Scope,
        query: str,
        query_terms: list[str],
        retrieval_plan: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        original_query = re.sub(r"\s+", " ", query).strip()
        rewrite_trace: dict[str, object] = {
            "rewritten_query": None,
            "query_rewrite_applied": False,
            "query_rewrite_reason": None,
        }
        if not settings.query_rewrite_enabled:
            return original_query, rewrite_trace
        if not self._is_vague_query(original_query, query_terms, retrieval_plan):
            return original_query, rewrite_trace

        context = self._build_query_rewrite_context(scope)
        if not context.strip():
            rewrite_trace["query_rewrite_reason"] = "Query looked vague, but no domain context was available for a safe rewrite."
            return original_query, rewrite_trace

        try:
            provider = resolve_provider(settings.default_provider)
            result = provider.rewrite_query(original_query, context)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("memoryos").warning("Query rewrite provider failed, falling back to heuristic: %s", exc)
            result = provider_registry["heuristic"].rewrite_query(original_query, context)

        rewrite_trace["query_rewrite_reason"] = result.reason
        if not result.apply:
            return original_query, rewrite_trace
        rewritten_query = re.sub(r"\s+", " ", result.rewritten_query).strip()
        if not rewritten_query or rewritten_query == original_query:
            return original_query, rewrite_trace

        rewrite_trace["rewritten_query"] = rewritten_query
        rewrite_trace["query_rewrite_applied"] = True
        return rewritten_query, rewrite_trace

    def _match_graph_context(
        self,
        scope: Scope,
        query: str,
        query_terms: list[str],
        query_mode: str,
        retrieval_plan: dict[str, object],
    ) -> dict[str, list[str] | int]:
        normalized_query = self._normalize_search_text(query)
        if not normalized_query:
            return {"match_count": 0, "evidence_ids": [], "expansion_terms": []}
        if retrieval_plan.get("graph_strategy") == "minimal":
            return {"match_count": 0, "evidence_ids": [], "expansion_terms": []}

        nodes = self._load_graph_nodes(scope)
        edges = self._load_graph_edges(scope)
        if not nodes and not edges:
            return {"match_count": 0, "evidence_ids": [], "expansion_terms": []}

        node_by_id = {node.node_id: node for node in nodes}
        graph_strategy = str(retrieval_plan.get("graph_strategy", "focused"))
        max_matches = max(settings.retrieval_graph_match_limit, 3)
        max_terms = max(settings.retrieval_expansion_term_limit, 6)
        if graph_strategy == "expanded":
            max_matches += 2
            max_terms += 3
        elif graph_strategy == "focused":
            max_matches = max(3, max_matches - 1)

        matched_nodes: list[tuple[float, GraphNode]] = []
        for node in nodes:
            excerpt = str((node.metadata or {}).get("supporting_excerpt", ""))
            search_text = self._normalize_search_text(f"{node.label} {node.node_type} {excerpt}")
            lexical_hits = sum(1 for term in query_terms if term in search_text)
            exact_match = 1.0 if normalized_query in search_text or self._normalize_search_text(node.label) in normalized_query else 0.0
            if lexical_hits == 0 and exact_match == 0.0:
                continue
            score = lexical_hits * 0.92 + exact_match * 1.25 + node.confidence * 0.45 + min(len(node.evidence_ids), 4) * 0.08
            if query_mode != "local" and node.node_type in {"concept", "organization", "document"}:
                score += 0.12
            matched_nodes.append((score, node))
        matched_nodes.sort(key=lambda pair: pair[0], reverse=True)
        matched_nodes = matched_nodes[:max_matches]

        matched_edges: list[tuple[float, GraphEdge]] = []
        for edge in edges:
            from_node = node_by_id.get(edge.from_node)
            to_node = node_by_id.get(edge.to_node)
            if not from_node or not to_node:
                continue
            excerpt = str((edge.metadata or {}).get("supporting_excerpt", ""))
            search_text = self._normalize_search_text(f"{from_node.label} {edge.relation} {to_node.label} {excerpt}")
            lexical_hits = sum(1 for term in query_terms if term in search_text)
            exact_match = 1.0 if normalized_query in search_text else 0.0
            if lexical_hits == 0 and exact_match == 0.0:
                continue
            score = lexical_hits * 0.84 + exact_match + edge.confidence * 0.42 + min(len(edge.evidence_ids), 4) * 0.1
            matched_edges.append((score, edge))
        matched_edges.sort(key=lambda pair: pair[0], reverse=True)
        matched_edges = matched_edges[:max_matches]

        evidence_ids: list[str] = []
        expansion_terms: list[str] = []
        seen_evidence: set[str] = set()
        seen_terms: set[str] = set(query_terms)

        def add_evidence(items: list[str]) -> None:
            for evidence_id in items:
                if evidence_id and evidence_id not in seen_evidence:
                    seen_evidence.add(evidence_id)
                    evidence_ids.append(evidence_id)

        def add_terms(text: str) -> None:
            for term in self._tokenize_search_text(text):
                if term in seen_terms or len(term) < 3:
                    continue
                seen_terms.add(term)
                expansion_terms.append(term)
                if len(expansion_terms) >= max_terms:
                    return

        matched_node_ids = {node.node_id for _, node in matched_nodes}
        for _, node in matched_nodes:
            add_evidence(node.evidence_ids[:4])
            add_terms(node.label)
        for _, edge in matched_edges:
            add_evidence(edge.evidence_ids[:4])
            add_terms(edge.relation.replace("_", " "))
            from_node = node_by_id.get(edge.from_node)
            to_node = node_by_id.get(edge.to_node)
            if from_node:
                add_terms(from_node.label)
            if to_node:
                add_terms(to_node.label)

        if query_mode != "local" and matched_node_ids and graph_strategy == "expanded":
            for edge in edges:
                if edge.from_node not in matched_node_ids and edge.to_node not in matched_node_ids:
                    continue
                add_evidence(edge.evidence_ids[:3])
                add_terms(edge.relation.replace("_", " "))
                if len(expansion_terms) >= max_terms and len(evidence_ids) >= max_matches * 3:
                    break

        return {
            "match_count": len(matched_nodes) + len(matched_edges),
            "evidence_ids": evidence_ids[: max_matches * 4],
            "expansion_terms": expansion_terms[:max_terms],
        }

    def _match_retrieval_hints(
        self,
        query: str,
        query_terms: list[str],
        query_embedding: list[float],
        candidates: list[MemoryRecord],
        retrieval_plan: dict[str, object],
    ) -> dict[str, list[str] | int]:
        normalized_query = self._normalize_search_text(query)
        max_terms = max(settings.retrieval_expansion_term_limit, 6)
        hint_policy = str(retrieval_plan.get("hint_policy", "normal"))
        minimum_score = 0.6 if hint_policy == "normal" else 0.92
        hint_limit = 3 if hint_policy == "normal" else 1
        matched_hints: list[tuple[float, MemoryRecord]] = []

        for item in candidates:
            if item.layer != MemoryLayer.RETRIEVAL_HINT:
                continue
            search_text = self._normalize_search_text(item.content)
            lexical_hits = sum(1 for term in query_terms if term in search_text)
            phrase_match = 1.0 if normalized_query and normalized_query in search_text else 0.0
            vector_similarity = embedding_service.similarity(query_embedding, (item.metadata or {}).get("_embedding", []))
            score = lexical_hits * 0.7 + phrase_match * 1.2 + vector_similarity * 0.75
            if score < minimum_score:
                continue
            matched_hints.append((score, item))

        matched_hints.sort(key=lambda pair: pair[0], reverse=True)
        expansion_terms: list[str] = []
        seen_terms: set[str] = set(query_terms)
        for _, item in matched_hints[:hint_limit]:
            for term in self._tokenize_search_text(item.content):
                if term in seen_terms or len(term) < 3:
                    continue
                seen_terms.add(term)
                expansion_terms.append(term)
                if len(expansion_terms) >= max_terms:
                    break
            if len(expansion_terms) >= max_terms:
                break

        return {
            "match_count": len(matched_hints[:hint_limit]),
            "expansion_terms": expansion_terms[:max_terms],
        }

    def _load_graph_evidence_candidates(
        self,
        scope: Scope,
        evidence_ids: list[str],
        query_mode: str,
        retrieval_plan: dict[str, object],
    ) -> list[MemoryRecord]:
        records = self._load_evidence_records(scope, evidence_ids)
        if not records:
            return []

        base_boost = 0.36 if query_mode == "global" else 0.3 if query_mode == "hybrid" else 0.24
        if retrieval_plan.get("graph_strategy") == "expanded":
            base_boost += 0.06
        if retrieval_plan.get("grounding_policy") == "strict":
            base_boost += 0.02
        boosted_records: list[MemoryRecord] = []
        for index, record in enumerate(records):
            metadata = dict(record.metadata or {})
            boost = max(base_boost - index * 0.03, 0.08)
            metadata["_graph_boost"] = max(float(metadata.get("_graph_boost", 0.0) or 0.0), boost)
            metadata["_graph_reason"] = "Matched grounded graph neighborhood"
            record.metadata = metadata
            boosted_records.append(record)
        return boosted_records

    def _load_evidence_records(self, scope: Scope, evidence_ids: list[str]) -> list[MemoryRecord]:
        ordered_ids = [item for item in dict.fromkeys(evidence_ids) if item]
        if not ordered_ids:
            return []

        record_map: dict[str, MemoryRecord] = {}
        with session_scope() as session:
            memory_rows = (
                session.query(MemoryModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id)
                .filter(self._memory_scope_filter(scope))
                .filter(MemoryModel.memory_id.in_(ordered_ids))
                .all()
            )
            event_rows = (
                session.query(EventModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id, user_id=scope.user_id)
                .filter(EventModel.conversation_id == scope.session_id)
                .filter(EventModel.event_id.in_(ordered_ids))
                .all()
            )

        for row in memory_rows:
            metadata = (row.metadata_json or {}) | {"_embedding": row.embedding_json or []}
            if row.document_source_id and "source_id" not in metadata:
                metadata["source_id"] = row.document_source_id
            if row.chunk_key and "chunk_key" not in metadata:
                metadata["chunk_key"] = row.chunk_key
            record_map[row.memory_id] = MemoryRecord(
                memory_id=row.memory_id,
                layer=MemoryLayer(row.layer),
                scope=scope,
                content=row.content,
                metadata=metadata,
                confidence=row.confidence,
                tags=row.tags_json or [],
                source=row.source,
                memory_scope=MemoryScope(_normalize_memory_scope(row.memory_scope)),
                scope_ref=row.scope_ref or None,
                conversation_id=row.conversation_id or row.session_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

        session_payloads = {
            payload["memory_id"]: payload
            for payload in fetch_session_memory(_scope_key(scope))
            if payload["memory_id"] in set(ordered_ids)
        }
        for memory_id, payload in session_payloads.items():
            record_map[memory_id] = MemoryRecord(
                memory_id=payload["memory_id"],
                layer=MemoryLayer(payload["layer"]),
                scope=scope,
                content=payload["content"],
                confidence=payload["confidence"],
                tags=payload["tags"],
                metadata=payload["metadata"] | {"_embedding": embedding_service.embed_document(payload["content"])},
                source=payload["source"],
                memory_scope=MemoryScope(_normalize_memory_scope(payload.get("memory_scope"))),
                scope_ref=payload.get("scope_ref"),
                conversation_id=payload.get("conversation_id") or scope.session_id,
                created_at=datetime.fromisoformat(payload["created_at"]),
                updated_at=datetime.fromisoformat(payload["updated_at"]),
            )

        for row in event_rows:
            content = f"{row.role}: {row.content}"
            record_map[row.event_id] = MemoryRecord(
                memory_id=row.event_id,
                layer=MemoryLayer.EVENT,
                scope=scope,
                content=content,
                metadata=(row.metadata_json or {}) | {"_embedding": embedding_service.embed_document(content)},
                confidence=0.62,
                tags=["event", row.outcome],
                source="event_log",
                memory_scope=MemoryScope.CONVERSATION,
                scope_ref=scope.session_id,
                conversation_id=row.conversation_id or row.session_id,
                created_at=row.created_at,
                updated_at=row.created_at,
            )

        return [record_map[evidence_id] for evidence_id in ordered_ids if evidence_id in record_map]

    def _deduplicate_candidates(self, candidates: list[MemoryRecord]) -> list[MemoryRecord]:
        merged: dict[str, MemoryRecord] = {}
        ordered_ids: list[str] = []
        for candidate in candidates:
            existing = merged.get(candidate.memory_id)
            if existing is None:
                merged[candidate.memory_id] = candidate
                ordered_ids.append(candidate.memory_id)
                continue
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.tags = list(dict.fromkeys([*(existing.tags or []), *(candidate.tags or [])]))
            existing.updated_at = max(existing.updated_at, candidate.updated_at)
            existing.metadata = self._merge_candidate_metadata(existing.metadata or {}, candidate.metadata or {})
        return [merged[memory_id] for memory_id in ordered_ids]

    def _merge_candidate_metadata(self, left: dict, right: dict) -> dict:
        merged = dict(left)
        for key, value in right.items():
            if key == "_graph_boost":
                merged[key] = max(float(merged.get(key, 0.0) or 0.0), float(value or 0.0))
            elif key == "_graph_reason":
                merged[key] = value or merged.get(key)
            elif key == "_embedding":
                merged.setdefault(key, value)
            elif key == "_reranker_score":
                merged[key] = max(float(merged.get(key, 0.0) or 0.0), float(value or 0.0))
            else:
                merged[key] = value
        return merged

    def _merge_query_expansion_terms(self, query_terms: list[str], *collections: list[str]) -> list[str]:
        merged: list[str] = []
        seen_terms: set[str] = set(query_terms)
        limit = max(settings.retrieval_expansion_term_limit, 6)
        for collection in collections:
            for term in collection:
                if term in seen_terms or len(term) < 3:
                    continue
                seen_terms.add(term)
                merged.append(term)
                if len(merged) >= limit:
                    return merged
        return merged

    def _build_expansion_term_weights(
        self,
        expansion_terms: list[str],
        query_terms: list[str],
        candidates: list[MemoryRecord],
    ) -> dict[str, float]:
        filtered_terms = [term for term in expansion_terms if term not in set(query_terms)]
        if not filtered_terms:
            return {}
        weights = self._build_query_term_weights(filtered_terms, candidates)
        return {
            term: round(weight * 0.65, 4)
            for term, weight in weights.items()
            if term not in set(query_terms)
        }

    def _score_recall_candidate(
        self,
        item: MemoryRecord,
        query: str,
        query_terms: list[str],
        query_term_weights: dict[str, float],
        expansion_term_weights: dict[str, float],
        query_embedding: list[float],
        query_mode: str,
        retrieval_plan: dict[str, object],
        now: datetime,
    ) -> float:
        metadata = item.metadata or {}
        content_text = self._normalize_search_text(item.content)
        metadata_text = self._normalize_search_text(self._metadata_search_text(item))
        normalized_query = self._normalize_search_text(query)
        title_text = self._normalize_search_text(str(metadata.get("title") or metadata.get("source_name") or ""))
        query_echo = self._is_query_echo_candidate(item, normalized_query)
        content_terms = set(self._tokenize_search_text(item.content))
        term_weight_total = sum(query_term_weights.values()) or max(len(query_terms), 1)
        expansion_weight_total = sum(expansion_term_weights.values()) or 1.0

        content_matches = sum(weight for term, weight in query_term_weights.items() if term in content_terms or term in content_text)
        metadata_matches = sum(weight for term, weight in query_term_weights.items() if term in metadata_text)
        expansion_matches = sum(
            weight
            for term, weight in expansion_term_weights.items()
            if term in content_terms or term in content_text or term in metadata_text
        )
        coverage = content_matches / term_weight_total
        metadata_coverage = metadata_matches / term_weight_total
        expansion_coverage = expansion_matches / expansion_weight_total if expansion_term_weights else 0.0
        phrase_match = 1.0 if normalized_query and normalized_query in content_text else 0.0
        metadata_phrase_match = 1.0 if normalized_query and normalized_query in metadata_text else 0.0
        title_phrase_match = 1.0 if normalized_query and normalized_query in title_text else 0.0
        complete_match = 1.0 if query_terms and all(term in f"{content_text} {metadata_text}" for term in query_terms) else 0.0

        vector_similarity = max(
            0.0,
            embedding_service.similarity(
                query_embedding,
                metadata.get("_embedding", []),
            ),
        )
        age_hours = max((now - item.updated_at).total_seconds() / 3600, 0.0)
        recency_boost = (0.2 * float(retrieval_plan.get("recency_multiplier", 1.0) or 1.0)) / (1.0 + age_hours / 72.0)

        kind = str(metadata.get("kind", "")).lower()
        intent = str(retrieval_plan.get("intent", "general"))
        scope_bias = str(retrieval_plan.get("scope_bias", "balanced"))
        grounding_policy = str(retrieval_plan.get("grounding_policy", "balanced"))
        graph_boost = float(metadata.get("_graph_boost", 0.0) or 0.0)
        entity_aliases = self._entity_aliases_for_query(query) if intent == "entity_lookup" else []
        entity_alias_hits = 0
        entity_alias_strength = 0.0
        entity_longform_hits = 0
        entity_acronym_hits = 0
        for alias in entity_aliases:
            if not alias or (alias not in content_text and alias not in title_text):
                continue
            entity_alias_hits += 1
            if " " in alias:
                entity_longform_hits += 1
                entity_alias_strength += 0.52 + min(len(alias.split()), 4) * 0.08
            else:
                entity_acronym_hits += 1
                entity_alias_strength += 0.24
        entity_heading_hit = any(alias in title_text for alias in entity_aliases) or any(
            alias in content_text[:280] for alias in entity_aliases if len(alias) > 3
        )
        score = (
            vector_similarity * 2.6
            + coverage * 2.8
            + metadata_coverage * 1.3
            + expansion_coverage * 0.95
            + phrase_match * 1.6
            + metadata_phrase_match * 0.8
            + title_phrase_match * (0.65 + float(retrieval_plan.get("exact_phrase_bias", 0.0) or 0.0))
            + complete_match * 0.75
            + graph_boost
            + item.confidence * 0.45
            + recency_boost
        )

        strong_lexical_signal = (
            coverage > 0.12
            or metadata_coverage > 0.12
            or phrase_match > 0
            or metadata_phrase_match > 0
            or title_phrase_match > 0
            or complete_match > 0
        )

        if kind == "document_chunk":
            score += 0.35
            if coverage > 0 or metadata_coverage > 0 or expansion_coverage > 0 or phrase_match > 0:
                score += 0.85
            if metadata_matches:
                score += 0.25
            score += float(retrieval_plan.get("document_bias", 0.0) or 0.0)
        elif kind in {"fact", "preference"} and coverage == 0 and phrase_match == 0 and vector_similarity < 0.45:
            score -= 0.2

        if item.layer == MemoryLayer.RETRIEVAL_HINT:
            score -= 0.55
            if retrieval_plan.get("hint_policy") == "weak":
                score -= 0.18
        if item.layer == MemoryLayer.FAILURE:
            score += 0.08
        if item.layer == MemoryLayer.RESOLUTION:
            score += 0.05
        if item.layer == MemoryLayer.EVENT and coverage == 0 and vector_similarity < 0.35:
            score -= 0.15
        if item.layer == MemoryLayer.SESSION and coverage > 0:
            score += 0.1
        if query_echo:
            score -= 2.8
            if intent in {"entity_lookup", "policy_lookup", "reference_lookup"}:
                score -= 1.4
        if str(metadata.get("role", "")).lower() == "assistant" and "not have enough grounded evidence" in content_text:
            score -= 1.25
        if item.layer == MemoryLayer.EVENT and metadata.get("abstained") is True:
            score -= 0.9

        if scope_bias == "session":
            if item.memory_scope in {MemoryScope.CONVERSATION, MemoryScope.USER}:
                score += float(retrieval_plan.get("session_bias", 0.0) or 0.0)
            elif not strong_lexical_signal:
                score -= 0.12
        elif scope_bias == "shared":
            if item.memory_scope == MemoryScope.APP:
                score += float(retrieval_plan.get("shared_bias", 0.0) or 0.0)
            elif item.layer in {MemoryLayer.SESSION, MemoryLayer.EVENT} and not strong_lexical_signal:
                score -= 0.14

        if intent == "troubleshooting":
            if item.layer == MemoryLayer.RESOLUTION:
                score += float(retrieval_plan.get("resolution_bias", 0.0) or 0.0)
            if item.layer == MemoryLayer.FAILURE:
                score += float(retrieval_plan.get("failure_bias", 0.0) or 0.0)
            if item.layer in {MemoryLayer.EVENT, MemoryLayer.SESSION}:
                score += 0.12
        elif intent == "workflow_reasoning":
            if item.layer in {MemoryLayer.RESOLUTION, MemoryLayer.FAILURE}:
                score += 0.1
            if graph_boost > 0:
                score += 0.12
        elif intent == "entity_lookup":
            entity_match = strong_lexical_signal or graph_boost > 0
            if entity_alias_hits > 0:
                score += entity_alias_strength
                if entity_heading_hit:
                    score += 0.22
                if entity_longform_hits > 0:
                    score += 0.18
                elif entity_acronym_hits > 0:
                    score -= 0.08
            else:
                score -= 1.1
                if graph_boost > 0:
                    score -= 0.45
            if title_phrase_match > 0 or metadata_phrase_match > 0 or complete_match > 0:
                score += 0.22
            if not entity_match:
                score -= 1.45
            if kind == "document_chunk" and coverage == 0 and metadata_coverage == 0 and graph_boost == 0:
                score -= 0.45
        elif intent in {"policy_lookup", "reference_lookup"}:
            if grounding_policy == "strict" and not strong_lexical_signal and graph_boost == 0 and vector_similarity < 0.58:
                score -= 0.28
            if title_phrase_match > 0 or metadata_phrase_match > 0:
                score += 0.18
        elif intent == "personalization":
            if item.layer == MemoryLayer.SESSION:
                score += 0.16
            if item.memory_scope in {MemoryScope.CONVERSATION, MemoryScope.USER}:
                score += 0.12

        if query_mode == "local":
            if kind == "document_chunk":
                score += 0.18
            if item.layer in {MemoryLayer.SESSION, MemoryLayer.EVENT}:
                score += 0.08
            if item.layer in {MemoryLayer.LONG_TERM, MemoryLayer.FAILURE, MemoryLayer.RESOLUTION} and coverage == 0 and graph_boost == 0:
                score -= 0.08
        elif query_mode == "global":
            if kind in {"fact", "preference"} or item.layer in {MemoryLayer.FAILURE, MemoryLayer.RESOLUTION}:
                score += 0.14
            if graph_boost > 0:
                score += 0.08
            if kind == "document_chunk" and coverage == 0 and expansion_coverage == 0 and graph_boost == 0:
                score -= 0.08
        else:
            if graph_boost > 0 and (coverage > 0 or expansion_coverage > 0):
                score += 0.12
        if item.metadata is None:
            item.metadata = {}
        item.metadata["_query_echo"] = query_echo
        item.metadata["_lexical_signal"] = strong_lexical_signal and not query_echo
        item.metadata["_grounding_signal"] = (strong_lexical_signal or graph_boost > 0) and not query_echo
        item.metadata["_entity_match"] = ((strong_lexical_signal or graph_boost > 0) and not query_echo) if intent == "entity_lookup" else False
        item.metadata["_entity_alias_hit"] = entity_alias_hits > 0 if intent == "entity_lookup" else False
        return score

    def _build_recall_metadata(self, scope: Scope, item: MemoryRecord, score: float) -> dict:
        metadata = self._sanitize_metadata(item.metadata)
        metadata["retrieval_score"] = round(score, 4)
        reranker_score = (item.metadata or {}).get("_reranker_score")
        if isinstance(reranker_score, (float, int)):
            metadata["reranker_score"] = round(float(reranker_score), 4)
        graph_boost = (item.metadata or {}).get("_graph_boost")
        if isinstance(graph_boost, (float, int)):
            metadata["graph_boost"] = round(float(graph_boost), 4)
        graph_reason = (item.metadata or {}).get("_graph_reason")
        if isinstance(graph_reason, str) and graph_reason.strip():
            metadata["graph_reason"] = graph_reason
        lexical_signal = (item.metadata or {}).get("_lexical_signal")
        if isinstance(lexical_signal, bool):
            metadata["lexical_signal"] = lexical_signal
        grounding_signal = (item.metadata or {}).get("_grounding_signal")
        if isinstance(grounding_signal, bool):
            metadata["grounding_signal"] = grounding_signal
        entity_match = (item.metadata or {}).get("_entity_match")
        if isinstance(entity_match, bool):
            metadata["entity_match"] = entity_match
        entity_alias_hit = (item.metadata or {}).get("_entity_alias_hit")
        if isinstance(entity_alias_hit, bool):
            metadata["entity_alias_hit"] = entity_alias_hit
        kind = metadata.get("kind")
        if kind == "document_chunk":
            metadata.update(self._load_chunk_context(scope, metadata))
        return metadata

    def _trim_low_relevance_results(
        self,
        selected: list[tuple[float, MemoryRecord]],
        query_terms: list[str],
    ) -> list[tuple[float, MemoryRecord]]:
        if len(selected) <= 1:
            return selected

        best_score, best_item = selected[0]
        best_reranker = float((best_item.metadata or {}).get("_reranker_score", 0.0) or 0.0)
        short_query = len(query_terms) <= 3
        filtered: list[tuple[float, MemoryRecord]] = [selected[0]]

        for score, item in selected[1:]:
            metadata = item.metadata or {}
            reranker_score = float(metadata.get("_reranker_score", 0.0) or 0.0)
            search_text = f"{self._normalize_search_text(item.content)} {self._normalize_search_text(self._metadata_search_text(item))}"
            lexical_hits = sum(1 for term in query_terms if term in search_text)

            minimum_ratio = 0.46 if short_query else 0.34
            minimum_score = 1.9 if short_query else 1.35
            has_enough_score = score >= max(minimum_score, best_score * minimum_ratio)
            has_grounding_signal = reranker_score >= (0.18 if short_query else 0.08) or lexical_hits >= max(1, min(len(query_terms), 2))

            if short_query and best_item.layer in {MemoryLayer.EVENT, MemoryLayer.SESSION} and best_reranker >= 0.9:
                if score >= best_score * 0.72 or reranker_score >= 0.82:
                    filtered.append((score, item))
                continue

            if has_enough_score and has_grounding_signal:
                filtered.append((score, item))

        return filtered or [selected[0]]

    def _select_recall_results(
        self,
        scored_candidates: list[tuple[float, MemoryRecord]],
        top_k: int,
        query_terms: list[str],
        query_mode: str,
    ) -> list[tuple[float, MemoryRecord]]:
        non_hint_candidates: list[tuple[float, MemoryRecord]] = []
        hint_candidates: list[tuple[float, MemoryRecord]] = []
        seen_memory_ids: set[str] = set()

        for score, item in scored_candidates:
            if item.memory_id in seen_memory_ids:
                continue
            seen_memory_ids.add(item.memory_id)
            if item.layer == MemoryLayer.RETRIEVAL_HINT:
                hint_candidates.append((score, item))
            else:
                non_hint_candidates.append((score, item))

            if len(non_hint_candidates) >= max(top_k * 4, 12):
                break

        trimmed = self._trim_low_relevance_results(non_hint_candidates, query_terms)
        selected = self._diversify_recall_results(trimmed, non_hint_candidates, top_k, query_mode)
        if len(selected) >= top_k:
            return selected[:top_k]

        selected_ids = {item.memory_id for _, item in selected}
        for score, item in hint_candidates:
            if item.memory_id in selected_ids:
                continue
            selected.append((score, item))
            if len(selected) >= top_k:
                break
        return selected[:top_k]

    def _enforce_grounding_requirements(
        self,
        selected: list[tuple[float, MemoryRecord]],
        retrieval_plan: dict[str, object],
    ) -> list[tuple[float, MemoryRecord]]:
        if not selected:
            return selected

        strict_lookup = str(retrieval_plan.get("grounding_policy", "balanced")) == "strict" or str(
            retrieval_plan.get("intent", "general")
        ) in {"entity_lookup", "policy_lookup", "reference_lookup"}
        if not strict_lookup:
            return selected

        grounded = [
            (score, item)
            for score, item in selected
            if bool((item.metadata or {}).get("_grounding_signal"))
            or bool((item.metadata or {}).get("_entity_match"))
            or bool((item.metadata or {}).get("_lexical_signal"))
        ]
        return grounded

    def _diversify_recall_results(
        self,
        primary_candidates: list[tuple[float, MemoryRecord]],
        fallback_candidates: list[tuple[float, MemoryRecord]],
        top_k: int,
        query_mode: str,
    ) -> list[tuple[float, MemoryRecord]]:
        selected: list[tuple[float, MemoryRecord]] = []
        selected_ids: set[str] = set()
        source_counts: dict[str, int] = {}
        max_per_source = max(settings.retrieval_source_diversity_limit, 1)
        if query_mode == "local":
            max_per_source += 1

        def try_take(score: float, item: MemoryRecord, *, relaxed: bool = False) -> bool:
            if item.memory_id in selected_ids:
                return False
            source_bucket = self._candidate_source_bucket(item)
            allowed_per_source = max_per_source + (1 if relaxed else 0)
            if source_counts.get(source_bucket, 0) >= allowed_per_source:
                return False
            selected.append((score, item))
            selected_ids.add(item.memory_id)
            source_counts[source_bucket] = source_counts.get(source_bucket, 0) + 1
            return True

        for pool, relaxed in ((primary_candidates, False), (fallback_candidates, False), (fallback_candidates, True)):
            for score, item in pool:
                if try_take(score, item, relaxed=relaxed) and len(selected) >= top_k:
                    return selected[:top_k]
        return selected[:top_k]

    def _candidate_source_bucket(self, item: MemoryRecord) -> str:
        metadata = item.metadata or {}
        source_id = metadata.get("source_id")
        if isinstance(source_id, str) and source_id.strip():
            return source_id.strip().lower()
        for key in ("source_name", "title"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return f"{item.layer.value}:{item.source}"

    def _sanitize_metadata(self, metadata: dict) -> dict:
        return {
            str(key): value
            for key, value in (metadata or {}).items()
            if not str(key).startswith("_")
        }

    def _load_chunk_context(self, scope: Scope, metadata: dict, window: int = 1) -> dict:
        source_id = metadata.get("source_id")
        source_name = metadata.get("source_name")
        current_index = metadata.get("chunk_index")
        if not isinstance(current_index, int) or (not source_id and not source_name):
            return {}

        with session_scope() as session:
            rows = (
                session.query(MemoryModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id, layer=MemoryLayer.LONG_TERM.value, source="ingestion")
                .filter(self._memory_scope_filter(scope))
                .order_by(MemoryModel.created_at.asc())
                .limit(300)
                .all()
            )

        chunk_map: dict[int, str] = {}
        for row in rows:
            row_metadata = row.metadata_json or {}
            row_index = row_metadata.get("chunk_index")
            same_source = False
            if source_id:
                same_source = row.document_source_id == source_id or row_metadata.get("source_id") == source_id
            elif source_name:
                same_source = row_metadata.get("source_name") == source_name
            if same_source and isinstance(row_index, int):
                chunk_map[row_index] = row.content

        context: dict[str, str] = {}
        previous_chunk = chunk_map.get(current_index - window)
        next_chunk = chunk_map.get(current_index + window)
        if previous_chunk:
            context["context_before"] = previous_chunk
        if next_chunk:
            context["context_after"] = next_chunk
        return context

    def _rerank_recall_candidates(
        self,
        query: str,
        scored_candidates: list[tuple[float, MemoryRecord]],
    ) -> list[tuple[float, MemoryRecord]]:
        if not settings.reranker_enabled or not scored_candidates:
            return scored_candidates

        rerank_pool_size = min(len(scored_candidates), max(settings.reranker_candidate_limit, 8))
        rerank_pool = scored_candidates[:rerank_pool_size]
        rerank_inputs = [self._build_reranker_document(item) for _, item in rerank_pool]
        try:
            reranker_scores = embedding_service.rerank(query, rerank_inputs)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("memoryos").warning("Recall reranker failed, falling back to hybrid rank only: %s", exc)
            return scored_candidates

        if len(reranker_scores) != len(rerank_pool):
            return scored_candidates

        reranked_pool: list[tuple[float, MemoryRecord]] = []
        for (base_score, item), raw_score in zip(rerank_pool, reranker_scores, strict=False):
            normalized_score = self._normalize_reranker_score(raw_score)
            if item.metadata is None:
                item.metadata = {}
            item.metadata["_reranker_score"] = normalized_score

            final_score = base_score * 0.72 + normalized_score * 3.1
            if item.metadata.get("kind") == "document_chunk" and normalized_score >= 0.7:
                final_score += 0.3
            reranked_pool.append((final_score, item))

        combined_scores = [*reranked_pool, *scored_candidates[rerank_pool_size:]]
        combined_scores.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        return combined_scores

    def _build_reranker_document(self, item: MemoryRecord) -> str:
        metadata = item.metadata or {}
        fragments: list[str] = []
        title = metadata.get("title") or metadata.get("source_name")
        if isinstance(title, str) and title.strip():
            fragments.append(f"Title: {title.strip()}")

        kind = metadata.get("kind")
        if isinstance(kind, str) and kind.strip():
            fragments.append(f"Kind: {kind.strip()}")

        source_type = metadata.get("source_type")
        if isinstance(source_type, str) and source_type.strip():
            fragments.append(f"Source type: {source_type.strip()}")

        for label, key in (
            ("Section", "section_heading"),
            ("Sections", "section_headings"),
            ("Page", "page_numbers"),
            ("Sheet", "sheet_names"),
            ("Block", "block_types"),
            ("Structure", "structural_path"),
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                fragments.append(f"{label}: {value.strip()}")
            elif isinstance(value, list):
                joined = ", ".join(str(part).strip() for part in value if str(part).strip())
                if joined:
                    fragments.append(f"{label}: {joined}")

        if item.tags:
            fragments.append(f"Tags: {', '.join(item.tags)}")

        fragments.append(f"Layer: {item.layer.value}")
        fragments.append(f"Content: {item.content}")
        return "\n".join(fragments)

    def _normalize_reranker_score(self, raw_score: float) -> float:
        clipped = max(min(float(raw_score), 18.0), -18.0)
        return 1.0 / (1.0 + math.exp(-clipped))

    def _metadata_search_text(self, item: MemoryRecord) -> str:
        metadata = item.metadata or {}
        pieces: list[str] = []
        for key in ("title", "source_name", "source_type", "section_heading", "kind", "structural_path"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                pieces.append(value)
        for key in ("section_headings", "sheet_names", "page_numbers", "block_types"):
            value = metadata.get(key)
            if isinstance(value, list):
                pieces.extend(str(part) for part in value if str(part).strip())
        pieces.extend(item.tags or [])
        return " ".join(pieces)

    def _build_query_term_weights(self, query_terms: list[str], candidates: list[MemoryRecord]) -> dict[str, float]:
        if not query_terms:
            return {}

        searchable_documents = [
            f"{self._normalize_search_text(candidate.content)} {self._normalize_search_text(self._metadata_search_text(candidate))}"
            for candidate in candidates
        ]
        total_documents = max(len(searchable_documents), 1)
        weights: dict[str, float] = {}
        for term in query_terms:
            document_frequency = sum(1 for searchable in searchable_documents if term in searchable)
            weights[term] = math.log((1 + total_documents) / (1 + document_frequency)) + 1.0
        return weights

    def _tokenize_search_text(self, text: str) -> list[str]:
        stopwords = {
            "a",
            "an",
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "what",
            "when",
            "where",
            "have",
            "about",
            "does",
            "into",
            "your",
            "their",
            "them",
            "then",
            "than",
            "were",
            "been",
            "has",
            "had",
            "hi",
            "hello",
            "hey",
            "please",
            "me",
            "you",
            "i",
            "do",
            "did",
            "done",
            "need",
            "want",
            "help",
            "will",
            "would",
            "should",
            "could",
        }
        synonym_map = {
            "non-compete": ["noncompetition", "non-competition", "noncompete"],
            "noncompetition": ["non-compete", "non-competition", "noncompete"],
            "termination": ["terminate", "terminated"],
            "terminated": ["termination", "terminate"],
            "disciplinary": ["discipline"],
            "discipline": ["disciplinary"],
            "employee": ["employees"],
            "employees": ["employee"],
            "ceo": ["chief executive officer", "executive officer"],
            "cto": ["chief technology officer", "technology officer"],
            "cfo": ["chief financial officer", "finance officer"],
            "coo": ["chief operating officer", "operations officer"],
            "cio": ["chief information officer", "information officer"],
            "ciso": ["chief information security officer", "security officer"],
            "cmo": ["chief marketing officer", "marketing officer"],
            "chro": ["chief human resources officer", "human resources officer"],
            "hr": ["human resource", "human resources"],
            "hod": ["head of department", "department head"],
        }
        raw_tokens = re.findall(r"[a-z0-9][a-z0-9_-]+", self._normalize_search_text(text))
        expanded_tokens: list[str] = []
        seen: set[str] = set()
        for token in raw_tokens:
            variants = [token]
            collapsed = token.replace("-", "").replace("_", "")
            if collapsed and collapsed != token:
                variants.append(collapsed)
            variants.extend(part for part in re.split(r"[-_]", token) if part)
            variants.extend(synonym_map.get(token, []))
            for variant in variants:
                if variant in stopwords or not variant or variant in seen:
                    continue
                seen.add(variant)
                expanded_tokens.append(variant)
        return expanded_tokens

    def _normalize_search_text(self, text: str) -> str:
        normalized = re.sub(r"[^a-z0-9\s_-]+", " ", text.lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _is_query_echo_candidate(self, item: MemoryRecord, normalized_query: str) -> bool:
        if not normalized_query:
            return False
        content_text = self._normalize_search_text(item.content)
        if not content_text:
            return False
        without_role_prefix = re.sub(r"^(user|assistant|system|tool)\s+", "", content_text).strip()
        if without_role_prefix == normalized_query:
            return True
        metadata = item.metadata or {}
        if (
            str(metadata.get("kind", "")).lower() == "conversation_turn"
            and str(metadata.get("role", "")).lower() == "user"
            and without_role_prefix.startswith(normalized_query)
            and len(without_role_prefix) <= len(normalized_query) + 8
        ):
            return True
        return False

    def _entity_aliases_for_query(self, query: str) -> list[str]:
        normalized_query = self._normalize_search_text(query)
        if not normalized_query:
            return []
        title_alias_map = {
            "ceo": ["chief executive officer"],
            "cto": ["chief technology officer", "technology officer"],
            "cfo": ["chief financial officer", "finance officer"],
            "coo": ["chief operating officer", "operations officer"],
            "cio": ["chief information officer", "information officer"],
            "ciso": ["chief information security officer", "security officer"],
            "cmo": ["chief marketing officer", "marketing officer"],
            "chro": ["chief human resources officer", "human resources officer"],
            "hr": ["human resource", "human resources"],
            "hod": ["head of department", "department head"],
        }
        aliases: list[str] = []
        for short_title, expanded_titles in title_alias_map.items():
            candidates = [short_title, *expanded_titles]
            if any(re.search(rf"\b{re.escape(candidate)}\b", normalized_query) for candidate in candidates):
                aliases.extend(candidates)
        return list(dict.fromkeys(sorted(aliases, key=len, reverse=True)))

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
                    memory_scope=MemoryScope(_normalize_memory_scope(payload.get("memory_scope"))),
                    scope_ref=payload.get("scope_ref"),
                    conversation_id=payload.get("conversation_id") or scope.session_id,
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
        recent_limit: int,
    ) -> list[MemoryRecord]:
        with session_scope() as session:
            allowed = {layer.value for layer in layers if layer != MemoryLayer.EVENT and layer != MemoryLayer.SESSION}
            memory_query = (
                session.query(MemoryModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id)
                .filter(self._memory_scope_filter(scope))
            )
            if allowed:
                memory_query = memory_query.filter(MemoryModel.layer.in_(allowed))
            memory_rows = (
                memory_query.order_by(MemoryModel.embedding_vector.cosine_distance(query_embedding))
                .limit(limit)
                .all()
            )
            recent_rows = (
                memory_query.order_by(MemoryModel.created_at.desc())
                .limit(recent_limit)
                .all()
            )
            event_rows = (
                session.query(EventModel)
                .filter_by(org_id=scope.org_id, app_id=scope.app_id, user_id=scope.user_id)
                .filter(EventModel.conversation_id == scope.session_id)
                .order_by(EventModel.created_at.desc())
                .limit(limit)
                .all()
            )
        merged_rows: dict[str, MemoryModel] = {}
        for row in [*memory_rows, *recent_rows]:
            merged_rows[row.memory_id] = row
        candidates = [
            MemoryRecord(
                memory_id=row.memory_id,
                layer=MemoryLayer(row.layer),
                scope=scope,
                content=row.content,
                metadata=(
                    (row.metadata_json or {})
                    | {"_embedding": row.embedding_json or []}
                    | (
                        {"source_id": row.document_source_id}
                        if row.document_source_id and "source_id" not in (row.metadata_json or {})
                        else {}
                    )
                    | (
                        {"chunk_key": row.chunk_key}
                        if row.chunk_key and "chunk_key" not in (row.metadata_json or {})
                        else {}
                    )
                ),
                confidence=row.confidence,
                tags=row.tags_json or [],
                source=row.source,
                memory_scope=MemoryScope(_normalize_memory_scope(row.memory_scope)),
                scope_ref=row.scope_ref or None,
                conversation_id=row.conversation_id or row.session_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in merged_rows.values()
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
                        memory_scope=MemoryScope.CONVERSATION,
                        scope_ref=scope.session_id,
                        conversation_id=row.conversation_id or row.session_id,
                        created_at=row.created_at,
                        updated_at=row.created_at,
                    )
                    for row in event_rows
                ]
            )
        return candidates

    def _load_graph_nodes(
        self,
        scope: Scope,
        *,
        memory_scope: MemoryScope | str | None = None,
    ) -> list[GraphNode]:
        selected_scope = self._resolve_memory_scope(memory_scope)
        with session_scope() as session:
            query = session.query(GraphNodeModel).filter_by(org_id=scope.org_id, app_id=scope.app_id)
            if selected_scope is None:
                query = query.filter(self._graph_scope_filter(scope))
            else:
                query = query.filter(self._graph_node_target_filter(scope, selected_scope))
            rows = query.all()
        return [
            GraphNode(
                scope=scope,
                node_id=row.node_id,
                label=row.label,
                node_type=row.node_type,
                confidence=row.confidence,
                evidence_ids=row.evidence_ids_json or [],
                metadata=row.metadata_json or {},
                memory_scope=MemoryScope(_normalize_memory_scope(row.graph_scope)),
                scope_ref=row.scope_ref or None,
                conversation_id=row.conversation_id or row.session_id,
            )
            for row in rows
        ]

    def _load_graph_edges(
        self,
        scope: Scope,
        *,
        memory_scope: MemoryScope | str | None = None,
    ) -> list[GraphEdge]:
        selected_scope = self._resolve_memory_scope(memory_scope)
        with session_scope() as session:
            query = session.query(GraphEdgeModel).filter_by(org_id=scope.org_id, app_id=scope.app_id)
            if selected_scope is None:
                query = query.filter(self._graph_edge_scope_filter(scope))
            else:
                query = query.filter(self._graph_edge_target_filter(scope, selected_scope))
            rows = query.all()
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
                memory_scope=MemoryScope(_normalize_memory_scope(row.graph_scope)),
                scope_ref=row.scope_ref or None,
                conversation_id=row.conversation_id or row.session_id,
            )
            for row in rows
        ]

    def _replace_graph(
        self,
        scope: Scope,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        *,
        target_memory_scope: MemoryScope = MemoryScope.CONVERSATION,
        target_scope_ref: str | None = None,
        target_conversation_id: str | None = None,
    ) -> None:
        with session_scope() as session:
            session.query(GraphEdgeModel).filter_by(
                org_id=scope.org_id,
                app_id=scope.app_id,
            ).filter(
                self._graph_edge_target_filter(
                    scope,
                    target_memory_scope,
                    scope_ref=target_scope_ref,
                    conversation_id=target_conversation_id,
                )
            ).delete()
            session.query(GraphNodeModel).filter_by(
                org_id=scope.org_id,
                app_id=scope.app_id,
            ).filter(
                self._graph_node_target_filter(
                    scope,
                    target_memory_scope,
                    scope_ref=target_scope_ref,
                    conversation_id=target_conversation_id,
                )
            ).delete()

            for node in nodes:
                node = self._hydrate_graph_scope(node)
                session.add(
                    GraphNodeModel(
                        node_id=node.node_id,
                        org_id=node.scope.org_id,
                        app_id=node.scope.app_id,
                        user_id=node.scope.user_id,
                        session_id=node.scope.session_id,
                        graph_scope=node.memory_scope.value,
                        scope_ref=node.scope_ref or "",
                        conversation_id=node.conversation_id or node.scope.session_id,
                        label=node.label,
                        node_type=node.node_type,
                        confidence=node.confidence,
                        evidence_ids_json=node.evidence_ids,
                        metadata_json=node.metadata,
                    )
                )

            for edge in edges:
                edge = self._hydrate_graph_scope(edge)
                session.add(
                    GraphEdgeModel(
                        edge_id=edge.edge_id,
                        org_id=edge.scope.org_id,
                        app_id=edge.scope.app_id,
                        user_id=edge.scope.user_id,
                        session_id=edge.scope.session_id,
                        graph_scope=edge.memory_scope.value,
                        scope_ref=edge.scope_ref or "",
                        conversation_id=edge.conversation_id or edge.scope.session_id,
                        from_node=edge.from_node,
                        to_node=edge.to_node,
                        relation=edge.relation,
                        confidence=edge.confidence,
                        evidence_ids_json=edge.evidence_ids,
                        metadata_json=edge.metadata,
                    )
                )

    def _merge_graph(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        node_id_map: dict[str, str] = {}
        for node in nodes:
            persisted_id = self._upsert_graph_node(node)
            node_id_map[node.node_id] = persisted_id
        for edge in edges:
            edge.from_node = node_id_map.get(edge.from_node, edge.from_node)
            edge.to_node = node_id_map.get(edge.to_node, edge.to_node)
            self._create_graph_edge(edge)

    def _upsert_graph_node(self, node: GraphNode) -> str:
        node = self._hydrate_graph_scope(node)
        with session_scope() as session:
            existing = (
                session.query(GraphNodeModel)
                .filter_by(
                    org_id=node.scope.org_id,
                    app_id=node.scope.app_id,
                )
                .filter(func.lower(GraphNodeModel.label) == node.label.lower())
                .filter(
                    self._graph_node_target_filter(
                        node.scope,
                        node.memory_scope,
                        scope_ref=node.scope_ref,
                        conversation_id=node.conversation_id,
                    )
                )
                .first()
            )
            if existing:
                existing.node_type = node.node_type
                existing.confidence = max(existing.confidence, node.confidence)
                merged_evidence = set(existing.evidence_ids_json or [])
                merged_evidence.update(node.evidence_ids or [])
                existing.evidence_ids_json = sorted(merged_evidence)
                existing.metadata_json = (existing.metadata_json or {}) | node.metadata
                return existing.node_id
            session.add(
                GraphNodeModel(
                    node_id=node.node_id,
                    org_id=node.scope.org_id,
                    app_id=node.scope.app_id,
                    user_id=node.scope.user_id,
                    session_id=node.scope.session_id,
                    graph_scope=node.memory_scope.value,
                    scope_ref=node.scope_ref or "",
                    conversation_id=node.conversation_id or node.scope.session_id,
                    label=node.label,
                    node_type=node.node_type,
                    confidence=node.confidence,
                    evidence_ids_json=node.evidence_ids,
                    metadata_json=node.metadata,
                )
            )
            return node.node_id

    def _create_graph_edge(self, edge: GraphEdge) -> None:
        edge = self._hydrate_graph_scope(edge)
        with session_scope() as session:
            exists = (
                session.query(GraphEdgeModel)
                .filter_by(
                    org_id=edge.scope.org_id,
                    app_id=edge.scope.app_id,
                    from_node=edge.from_node,
                    to_node=edge.to_node,
                    relation=edge.relation,
                )
                .filter(
                    self._graph_edge_target_filter(
                        edge.scope,
                        edge.memory_scope,
                        scope_ref=edge.scope_ref,
                        conversation_id=edge.conversation_id,
                    )
                )
                .first()
            )
            if exists is not None:
                merged_evidence = set(exists.evidence_ids_json or [])
                merged_evidence.update(edge.evidence_ids or [])
                exists.evidence_ids_json = sorted(merged_evidence)
                exists.confidence = max(exists.confidence, edge.confidence)
                exists.metadata_json = (exists.metadata_json or {}) | edge.metadata
                return
            session.add(
                GraphEdgeModel(
                    edge_id=edge.edge_id,
                    org_id=edge.scope.org_id,
                    app_id=edge.scope.app_id,
                    user_id=edge.scope.user_id,
                    session_id=edge.scope.session_id,
                    graph_scope=edge.memory_scope.value,
                    scope_ref=edge.scope_ref or "",
                    conversation_id=edge.conversation_id or edge.scope.session_id,
                    from_node=edge.from_node,
                    to_node=edge.to_node,
                    relation=edge.relation,
                    confidence=edge.confidence,
                    evidence_ids_json=edge.evidence_ids,
                    metadata_json=edge.metadata,
                )
            )


memory_service = MemoryService()
