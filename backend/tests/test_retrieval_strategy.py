from datetime import UTC, datetime

from app.models.domain import MemoryLayer, MemoryRecord, MemoryScope, Scope
from app.services.memory import MemoryService
from app.services.providers import QueryRewriteResult


SCOPE = Scope(org_id="org", app_id="app", user_id="user", session_id="session")


def _record(
    memory_id: str,
    layer: MemoryLayer,
    content: str,
    *,
    source_name: str,
    metadata: dict | None = None,
    confidence: float = 0.82,
) -> MemoryRecord:
    timestamp = datetime(2026, 3, 25, tzinfo=UTC)
    base_metadata = {"source_name": source_name, "_embedding": [1.0, 0.0]}
    if metadata:
        base_metadata.update(metadata)
    return MemoryRecord(
        memory_id=memory_id,
        layer=layer,
        scope=SCOPE,
        content=content,
        metadata=base_metadata,
        confidence=confidence,
        tags=[],
        source="test",
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_query_mode_balances_local_global_and_hybrid_queries():
    service = MemoryService()

    local_query = "Who owns the refund API?"
    global_query = "How does the refund workflow improve over time across teams?"
    hybrid_query = "Show the relationship between refund API and escalation policy"

    assert service._infer_query_mode(local_query, service._tokenize_search_text(local_query)) == "local"
    assert service._infer_query_mode(global_query, service._tokenize_search_text(global_query)) == "global"
    assert service._infer_query_mode(hybrid_query, service._tokenize_search_text(hybrid_query)) == "hybrid"


def test_retrieval_plan_uses_troubleshooting_bias_for_incident_queries():
    service = MemoryService()
    query = "Why did the refund incident fail and how was it resolved?"

    plan = service._plan_retrieval(query, service._tokenize_search_text(query), None)

    assert plan["intent"] == "troubleshooting"
    assert plan["graph_strategy"] == "expanded"
    assert plan["preferred_layers"][0] == MemoryLayer.RESOLUTION
    assert plan["freshness_bias"] == "normal"


def test_retrieval_plan_prefers_strict_grounding_for_policy_queries():
    service = MemoryService()
    query = "What is our latest refund policy according to the handbook?"

    plan = service._plan_retrieval(query, service._tokenize_search_text(query), None)

    assert plan["intent"] == "policy_lookup"
    assert plan["scope_bias"] == "shared"
    assert plan["grounding_policy"] == "strict"
    assert plan["freshness_bias"] == "high"


def test_graph_boost_increases_recall_score_for_grounded_candidates():
    service = MemoryService()
    query = "How does the incident workflow improve across platform teams?"
    query_terms = service._tokenize_search_text(query)
    plan = service._plan_retrieval(query, query_terms, None)

    plain = _record(
        "plain",
        MemoryLayer.LONG_TERM,
        "The incident runbook explains escalation, ownership, and platform workflow.",
        source_name="runbook",
        metadata={"kind": "document_chunk"},
    )
    grounded = _record(
        "grounded",
        MemoryLayer.LONG_TERM,
        "The incident runbook explains escalation, ownership, and platform workflow.",
        source_name="runbook",
        metadata={"kind": "document_chunk", "_graph_boost": 0.32},
    )
    candidates = [plain, grounded]
    query_weights = service._build_query_term_weights(query_terms, candidates)
    expansion_weights = {"escalation": 0.4, "ownership": 0.3}
    query_embedding = [1.0, 0.0]
    now = datetime(2026, 3, 25, tzinfo=UTC)

    plain_score = service._score_recall_candidate(
        plain,
        query,
        query_terms,
        query_weights,
        expansion_weights,
        query_embedding,
        "global",
        plan,
        now,
    )
    grounded_score = service._score_recall_candidate(
        grounded,
        query,
        query_terms,
        query_weights,
        expansion_weights,
        query_embedding,
        "global",
        plan,
        now,
    )

    assert grounded_score > plain_score


def test_select_recall_results_prefers_diverse_sources_before_hint_memories():
    service = MemoryService()
    query_terms = service._tokenize_search_text("refund policy escalation")
    scored_candidates = [
        (
            5.1,
            _record(
                "doc-a-1",
                MemoryLayer.LONG_TERM,
                "Refund policy escalation steps for customer credits and exception review.",
                source_name="policy-handbook",
                metadata={"kind": "document_chunk"},
            ),
        ),
        (
            5.0,
            _record(
                "hint-1",
                MemoryLayer.RETRIEVAL_HINT,
                "Prioritize refund policy exception handling and escalation workflow.",
                source_name="reflection",
            ),
        ),
        (
            4.9,
            _record(
                "doc-b-1",
                MemoryLayer.LONG_TERM,
                "Escalation matrix for refunds, approvals, and finance review.",
                source_name="ops-runbook",
                metadata={"kind": "document_chunk"},
            ),
        ),
        (
            4.8,
            _record(
                "doc-a-2",
                MemoryLayer.LONG_TERM,
                "Refund exception policy examples and approval notes.",
                source_name="policy-handbook",
                metadata={"kind": "document_chunk"},
            ),
        ),
        (
            4.7,
            _record(
                "doc-a-3",
                MemoryLayer.LONG_TERM,
                "Additional refund policy appendix and historical examples.",
                source_name="policy-handbook",
                metadata={"kind": "document_chunk"},
            ),
        ),
    ]

    selected = service._select_recall_results(scored_candidates, top_k=3, query_terms=query_terms, query_mode="global")
    selected_ids = [item.memory_id for _, item in selected]
    selected_sources = [item.metadata["source_name"] for _, item in selected]

    assert "hint-1" not in selected_ids
    assert selected_sources.count("policy-handbook") <= 2
    assert "ops-runbook" in selected_sources


def test_session_bias_improves_personalized_retrieval_for_same_content():
    service = MemoryService()
    query = "What are my preferred refund settings?"
    query_terms = service._tokenize_search_text(query)
    plan = service._plan_retrieval(query, query_terms, None)
    candidates = []

    session_record = _record(
        "session-pref",
        MemoryLayer.SESSION,
        "Preferred refund settings: concise approval summaries and manager escalation notes.",
        source_name="conversation",
        metadata={"kind": "preference"},
    )
    session_record.memory_scope = MemoryScope.CONVERSATION
    app_record = _record(
        "app-pref",
        MemoryLayer.LONG_TERM,
        "Preferred refund settings: concise approval summaries and manager escalation notes.",
        source_name="policy-profile",
        metadata={"kind": "preference"},
    )
    app_record.memory_scope = MemoryScope.APP
    candidates.extend([session_record, app_record])
    query_weights = service._build_query_term_weights(query_terms, candidates)
    query_embedding = [1.0, 0.0]
    now = datetime(2026, 3, 25, tzinfo=UTC)

    session_score = service._score_recall_candidate(
        session_record,
        query,
        query_terms,
        query_weights,
        {},
        query_embedding,
        str(plan["query_mode"]),
        plan,
        now,
    )
    app_score = service._score_recall_candidate(
        app_record,
        query,
        query_terms,
        query_weights,
        {},
        query_embedding,
        str(plan["query_mode"]),
        plan,
        now,
    )

    assert session_score > app_score


def test_vague_query_can_be_rewritten_before_retrieval(monkeypatch):
    service = MemoryService()
    query = "tell me more"
    query_terms = service._tokenize_search_text(query)
    plan = service._plan_retrieval(query, query_terms, None)

    class StubProvider:
        def rewrite_query(self, raw_query: str, context: str) -> QueryRewriteResult:
            assert "Refund API" in context
            return QueryRewriteResult(
                apply=True,
                rewritten_query="Explain the refund API workflow and related approval policy.",
                reason="Clarified vague request using available domain context.",
            )

    monkeypatch.setattr(service, "_build_query_rewrite_context", lambda scope: "entity: Refund API\nsource: Refund Handbook")
    monkeypatch.setattr("app.services.memory.resolve_provider", lambda preferred=None: StubProvider())

    rewritten_query, rewrite_trace = service._rewrite_query_if_needed(SCOPE, query, query_terms, plan)

    assert rewritten_query == "Explain the refund API workflow and related approval policy."
    assert rewrite_trace["query_rewrite_applied"] is True
    assert rewrite_trace["rewritten_query"] == rewritten_query


def test_title_lookup_is_not_misclassified_as_personalization():
    service = MemoryService()
    query = "hi tell me about the CTO"

    query_terms = service._tokenize_search_text(query)
    plan = service._plan_retrieval(query, query_terms, None)

    assert "me" not in query_terms
    assert plan["intent"] == "entity_lookup"
    assert plan["scope_bias"] == "shared"
    assert plan["grounding_policy"] == "strict"
    assert MemoryLayer.SESSION not in plan["preferred_layers"]
    assert MemoryLayer.EVENT not in plan["preferred_layers"]


def test_strict_lookup_filters_results_without_grounding_signal():
    service = MemoryService()
    query = "tell me about the CTO"
    query_terms = service._tokenize_search_text(query)
    plan = service._plan_retrieval(query, query_terms, None)

    ungrounded = _record(
        "ungrounded-doc",
        MemoryLayer.LONG_TERM,
        "Finance and supply chain sections describe bonuses, reporting, and commissions.",
        source_name="employee-handbook",
        metadata={"kind": "document_chunk", "_grounding_signal": False, "_entity_match": False, "_lexical_signal": False},
    )

    grounded = _record(
        "grounded-doc",
        MemoryLayer.LONG_TERM,
        "Chief Technology Officer oversees the platform engineering roadmap.",
        source_name="leadership-handbook",
        metadata={"kind": "document_chunk", "_grounding_signal": True, "_entity_match": True, "_lexical_signal": True},
    )

    selected = service._enforce_grounding_requirements([(4.2, ungrounded), (3.8, grounded)], plan)

    assert [item.memory_id for _, item in selected] == ["grounded-doc"]


def test_query_echo_candidates_are_not_treated_as_grounded_entity_matches():
    service = MemoryService()
    query = "hi tell me about the CTO"
    query_terms = service._tokenize_search_text(query)
    plan = service._plan_retrieval(query, query_terms, None)

    query_echo = _record(
        "query-echo",
        MemoryLayer.SESSION,
        "user: hi tell me about the CTO",
        source_name="conversation",
        metadata={"kind": "conversation_turn", "role": "user"},
    )
    grounded_doc = _record(
        "grounded-doc",
        MemoryLayer.LONG_TERM,
        "Chief Technology Officer oversees the platform engineering roadmap.",
        source_name="leadership-handbook",
        metadata={"kind": "document_chunk", "title": "Company Organogram"},
    )
    candidates = [query_echo, grounded_doc]
    query_weights = service._build_query_term_weights(query_terms, candidates)
    query_embedding = [1.0, 0.0]
    now = datetime(2026, 3, 25, tzinfo=UTC)

    echo_score = service._score_recall_candidate(
        query_echo,
        query,
        query_terms,
        query_weights,
        {},
        query_embedding,
        str(plan["query_mode"]),
        plan,
        now,
    )
    grounded_score = service._score_recall_candidate(
        grounded_doc,
        query,
        query_terms,
        query_weights,
        {},
        query_embedding,
        str(plan["query_mode"]),
        plan,
        now,
    )

    assert echo_score < grounded_score
    assert query_echo.metadata["_query_echo"] is True
    assert query_echo.metadata["_grounding_signal"] is False
    assert grounded_doc.metadata["_entity_alias_hit"] is True


def test_entity_lookup_prefers_exact_title_chunks_over_incidental_mentions():
    service = MemoryService()
    query = "tell me about the CTO"
    query_terms = service._tokenize_search_text(query)
    plan = service._plan_retrieval(query, query_terms, None)

    exact_title_chunk = _record(
        "title-chunk",
        MemoryLayer.LONG_TERM,
        "Company Organogram. Chief Technology Officer leads the engineering organization.",
        source_name="leadership-handbook",
        metadata={"kind": "document_chunk", "title": "Company Organogram"},
    )
    incidental_mention = _record(
        "incidental-chunk",
        MemoryLayer.LONG_TERM,
        "Certification Policy requires prior approval from CTO and VP (HR & Admin).",
        source_name="employee-handbook",
        metadata={"kind": "document_chunk", "title": "Certification Policy"},
    )
    candidates = [exact_title_chunk, incidental_mention]
    query_weights = service._build_query_term_weights(query_terms, candidates)
    query_embedding = [1.0, 0.0]
    now = datetime(2026, 3, 25, tzinfo=UTC)

    exact_score = service._score_recall_candidate(
        exact_title_chunk,
        query,
        query_terms,
        query_weights,
        {},
        query_embedding,
        str(plan["query_mode"]),
        plan,
        now,
    )
    incidental_score = service._score_recall_candidate(
        incidental_mention,
        query,
        query_terms,
        query_weights,
        {},
        query_embedding,
        str(plan["query_mode"]),
        plan,
        now,
    )

    assert exact_score > incidental_score
