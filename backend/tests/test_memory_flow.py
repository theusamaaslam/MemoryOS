from datetime import UTC, datetime

from app.models.domain import GraphEdge, GraphNode, MemoryLayer, MemoryRecord, MemoryScope, Scope
from app.schemas.memory import RememberRequest, ScopeModel
from app.services.mcp import MCPService
from app.services.memory import MemoryService
from app.services.providers import HeuristicProvider


def test_ingest_documents_defaults_to_app_scope(monkeypatch):
    service = MemoryService()
    scope = Scope(org_id="org", app_id="app", user_id="user", session_id="session")
    captured_scopes: list[MemoryScope] = []

    def fake_upsert_source(current_scope, *, memory_scope, **kwargs):
        captured_scopes.append(memory_scope)
        return {
            "source_id": "src-1",
            "source_hash": "hash",
            "scope_ref": "app",
            "conversation_id": "session",
            "source_status": "indexed_pending_reflection",
            "unchanged": False,
        }

    def fake_upsert_chunks(current_scope, *, memory_scope, **kwargs):
        captured_scopes.append(memory_scope)
        return {
            "created": 1,
            "updated": 0,
            "removed": 0,
            "unchanged": 0,
            "touched_memory_ids": ["mem-1"],
            "removed_memory_ids": [],
        }

    monkeypatch.setattr(service, "_upsert_document_source", fake_upsert_source)
    monkeypatch.setattr(service, "_upsert_ingestion_chunks", fake_upsert_chunks)
    monkeypatch.setattr("app.services.memory.job_service.enqueue_reflection_if_due", lambda *args, **kwargs: True)

    service.ingest_documents(
        scope,
        "Policy Handbook",
        [
            {
                "content": "Refunds above $500 require manager approval.",
                "source_uri": "memory://policy-handbook#chunk-1",
                "title": "Refund Policy",
                "metadata": {},
            }
        ],
    )

    assert captured_scopes == [MemoryScope.APP, MemoryScope.APP]


def test_graph_scope_identity_targets_only_requested_slice():
    service = MemoryService()
    scope = Scope(org_id="org", app_id="app", user_id="user", session_id="conversation-a")

    conversation_identity = service._graph_scope_identity(scope, MemoryScope.CONVERSATION)
    app_identity = service._graph_scope_identity(scope, MemoryScope.APP)

    assert conversation_identity == {
        "graph_scope": "conversation",
        "scope_ref": "conversation-a",
        "conversation_id": "conversation-a",
        "user_id": "user",
    }
    assert app_identity == {
        "graph_scope": "app",
        "scope_ref": "app",
        "conversation_id": "conversation-a",
        "user_id": "user",
    }


def test_heuristic_provider_extracts_failures_and_hints():
    provider = HeuristicProvider()
    artifact = provider.reflect(
        "\n".join(
            [
                "user: I prefer concise replies",
                "assistant: Here is a long answer",
                "user: This didn't solve my refund issue",
            ]
        )
    )

    assert artifact.preferences
    assert artifact.failures
    assert artifact.retrieval_hints


def test_get_graph_respects_requested_scope_and_builds_summary(monkeypatch):
    service = MemoryService()
    scope = Scope(org_id="org", app_id="app", user_id="user", session_id="session")
    timestamp = datetime(2026, 3, 26, tzinfo=UTC)
    app_node = GraphNode(
        scope=scope,
        label="Refund Policy",
        node_type="document",
        node_id="node-app",
        evidence_ids=["mem-app"],
        memory_scope=MemoryScope.APP,
    )
    conversation_node = GraphNode(
        scope=scope,
        label="Recent Incident",
        node_type="concept",
        node_id="node-conv",
        evidence_ids=["evt-1"],
        memory_scope=MemoryScope.CONVERSATION,
    )
    app_edge = GraphEdge(
        scope=scope,
        from_node="node-app",
        to_node="node-app-target",
        relation="related_to",
        edge_id="edge-app",
        evidence_ids=["mem-app"],
        memory_scope=MemoryScope.APP,
    )
    captured_calls: list[tuple[str, MemoryScope | None]] = []

    def fake_load_graph_nodes(current_scope, *, memory_scope=None):
        captured_calls.append(("nodes", memory_scope))
        if memory_scope == MemoryScope.APP:
            return [app_node]
        if memory_scope == MemoryScope.CONVERSATION:
            return [conversation_node]
        return [app_node, conversation_node]

    def fake_load_graph_edges(current_scope, *, memory_scope=None):
        captured_calls.append(("edges", memory_scope))
        if memory_scope == MemoryScope.APP:
            return [app_edge]
        return []

    def fake_load_evidence_records(current_scope, evidence_ids):
        assert evidence_ids == ["mem-app", "mem-app"]
        return [
            MemoryRecord(
                memory_id="mem-app",
                layer=MemoryLayer.LONG_TERM,
                scope=scope,
                content="Refund policy chunks are promoted into shared graph memory.",
                metadata={"kind": "document_chunk", "source_name": "Policy Handbook"},
                source="ingestion",
                memory_scope=MemoryScope.APP,
                created_at=timestamp,
                updated_at=timestamp,
            )
        ]

    monkeypatch.setattr(service, "_load_graph_nodes", fake_load_graph_nodes)
    monkeypatch.setattr(service, "_load_graph_edges", fake_load_graph_edges)
    monkeypatch.setattr(service, "_load_evidence_records", fake_load_evidence_records)

    result = service.get_graph(scope, memory_scope=MemoryScope.APP)

    assert result["memory_scope"] == "app"
    assert result["summary"]["node_count"] == 1
    assert result["summary"]["edge_count"] == 1
    assert result["summary"]["evidence_count"] == 1
    assert result["scope_counts"]["app"]["nodes"] == 1
    assert result["scope_counts"]["conversation"]["nodes"] == 1
    assert result["nodes"][0]["evidence_preview"][0]["title"] == "Policy Handbook"
    assert ("nodes", MemoryScope.APP) in captured_calls
    assert ("edges", MemoryScope.APP) in captured_calls


def test_mcp_service_forwards_memory_scope_for_remember_and_graph(monkeypatch):
    service = MCPService()
    captured: dict[str, MemoryScope] = {}
    scope = ScopeModel(org_id="org", app_id="app", user_id="user", session_id="session")

    def fake_remember(record):
        captured["remember"] = record.memory_scope
        return record

    def fake_get_graph(scope_obj, *, memory_scope=None):
        captured["graph"] = memory_scope
        return {"memory_scope": memory_scope.value if memory_scope else "conversation", "scope_counts": {}, "summary": {}, "nodes": [], "edges": []}

    monkeypatch.setattr("app.services.mcp.memory_service.remember", fake_remember)
    monkeypatch.setattr("app.services.mcp.memory_service.get_graph", fake_get_graph)

    service.remember(
        RememberRequest(
            scope=scope,
            content="Remember this as shared knowledge.",
            memory_scope=MemoryScope.APP,
        )
    )
    service.search_graph(type("Payload", (), {"scope": scope, "memory_scope": MemoryScope.USER})())

    assert captured["remember"] == MemoryScope.APP
    assert captured["graph"] == MemoryScope.USER


def test_mcp_tool_catalog_matches_live_capabilities():
    service = MCPService()

    tool_names = {tool["name"] for tool in service.describe_tools()}

    assert "close_conversation" in tool_names
    assert "record_feedback" in tool_names
    assert "recall" in tool_names


def test_ingest_documents_skips_unchanged_source_without_requeue(monkeypatch):
    service = MemoryService()
    scope = Scope(org_id="org", app_id="app", user_id="user", session_id="session")
    scheduled: list[tuple] = []

    monkeypatch.setattr(
        service,
        "_upsert_document_source",
        lambda *args, **kwargs: {
            "source_id": "src-1",
            "source_hash": "hash",
            "scope_ref": "app",
            "conversation_id": "session",
            "source_status": "ready",
            "unchanged": True,
        },
    )
    monkeypatch.setattr(
        service,
        "_upsert_ingestion_chunks",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("chunk upsert should not run for unchanged sources")),
    )
    monkeypatch.setattr(
        "app.services.memory.job_service.enqueue_reflection_if_due",
        lambda *args, **kwargs: scheduled.append((args, kwargs)) or True,
    )

    result = service.ingest_documents(
        scope,
        "Policy Handbook",
        [
            {
                "content": "Refunds above $500 require manager approval.",
                "source_uri": "memory://policy-handbook#chunk-1",
                "title": "Refund Policy",
                "metadata": {},
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["skipped"] is True
    assert result["source_id"] == "src-1"
    assert scheduled == []


def test_ingest_documents_upserts_chunks_and_prunes_removed_evidence(monkeypatch):
    service = MemoryService()
    scope = Scope(org_id="org", app_id="app", user_id="user", session_id="session")
    pruned: list[dict] = []
    scheduled: list[tuple] = []

    monkeypatch.setattr(
        service,
        "_upsert_document_source",
        lambda *args, **kwargs: {
            "source_id": "src-2",
            "source_hash": "hash-2",
            "scope_ref": "app",
            "conversation_id": "session",
            "source_status": "indexed_pending_reflection",
            "unchanged": False,
        },
    )
    monkeypatch.setattr(
        service,
        "_upsert_ingestion_chunks",
        lambda *args, **kwargs: {
            "created": 2,
            "updated": 1,
            "removed": 1,
            "unchanged": 0,
            "touched_memory_ids": ["mem-a", "mem-b", "mem-c"],
            "removed_memory_ids": ["mem-old"],
        },
    )
    monkeypatch.setattr(
        service,
        "_prune_graph_evidence",
        lambda scope_value, evidence_ids, **kwargs: pruned.append(
            {"scope": scope_value, "evidence_ids": evidence_ids, **kwargs}
        ),
    )
    monkeypatch.setattr(
        "app.services.memory.job_service.enqueue_reflection_if_due",
        lambda *args, **kwargs: scheduled.append((args, kwargs)) or True,
    )

    result = service.ingest_documents(
        scope,
        "Policy Handbook",
        [
            {
                "content": "Updated refunds policy.",
                "source_uri": "memory://policy-handbook#chunk-1",
                "title": "Refund Policy",
                "metadata": {},
            }
        ],
        source_type="manual_text",
        memory_scope=MemoryScope.APP,
    )

    assert result["status"] == "queued"
    assert result["skipped"] is False
    assert result["chunks_created"] == 2
    assert result["chunks_updated"] == 1
    assert result["chunks_removed"] == 1
    assert pruned == [
        {
            "scope": scope,
            "evidence_ids": ["mem-old"],
            "memory_scope": MemoryScope.APP,
            "scope_ref": "app",
            "conversation_id": "session",
        }
    ]
    assert len(scheduled) == 1
