from datetime import UTC, datetime
from types import SimpleNamespace

from app.models.domain import MemoryLayer, MemoryScope
from app.services.conversations import ConversationService


def test_synthesize_answer_abstains_without_grounded_evidence():
    service = ConversationService()
    recall_result = SimpleNamespace(items=[], trace={})

    answer, citations, supported, abstained, confidence = service._synthesize_answer("What is our policy?", recall_result)

    assert citations == []
    assert supported is False
    assert abstained is True
    assert confidence < 0.3
    assert "do not have enough grounded evidence" in answer


def test_synthesize_answer_returns_citations_when_evidence_is_strong():
    service = ConversationService()
    recall_result = SimpleNamespace(
        items=[
            {
                "memory_id": "mem-1",
                "layer": MemoryLayer.LONG_TERM,
                "content": "Refunds over $500 require manager approval.",
                "metadata": {"retrieval_score": 2.4},
            },
            {
                "memory_id": "mem-2",
                "layer": MemoryLayer.RESOLUTION,
                "content": "Escalate exceptions to finance after approval is denied.",
                "metadata": {"retrieval_score": 1.9},
            },
        ],
        trace={},
    )

    answer, citations, supported, abstained, confidence = service._synthesize_answer("How do refunds work?", recall_result)

    assert supported is True
    assert abstained is False
    assert confidence > 0.5
    assert len(citations) == 2
    assert "[M1]" in answer


def test_best_grounded_fragment_prefers_query_relevant_sentence():
    service = ConversationService()

    fragment = service._best_grounded_fragment(
        "tell me about the CTO",
        "Finance runs monthly close. Chief Technology Officer (CTO) leads engineering strategy and platform architecture. Training bonuses are reviewed separately.",
    )

    assert "Chief Technology Officer" in fragment
    assert "Finance runs monthly close" not in fragment


def test_best_grounded_fragment_prefers_descriptive_title_sentence_over_short_alias_sentence():
    service = ConversationService()

    fragment = service._best_grounded_fragment(
        "hi tell me about the CTO",
        "The CTO partners with HR and Finance on enterprise systems planning. Chief Technology Officer (CTO) oversees engineering strategy, platform architecture, security coordination, AI agent infrastructure, and platform reliability reviews.",
    )

    assert "oversees engineering strategy" in fragment
    assert "partners with HR and Finance" not in fragment


def test_synthesize_answer_uses_descriptive_role_fragment_for_entity_lookup():
    service = ConversationService()
    recall_result = SimpleNamespace(
        items=[
            {
                "memory_id": "mem-cto-1",
                "layer": MemoryLayer.LONG_TERM,
                "content": "Chief Technology Officer (CTO) leads engineering strategy, platform architecture, and reliability governance.",
                "metadata": {
                    "retrieval_score": 6.2,
                    "grounding_signal": True,
                    "entity_match": True,
                    "lexical_signal": True,
                },
            },
            {
                "memory_id": "mem-cto-2",
                "layer": MemoryLayer.LONG_TERM,
                "content": "The CTO partners with HR and Finance on enterprise systems planning.",
                "metadata": {
                    "retrieval_score": 5.4,
                    "grounding_signal": True,
                    "entity_match": True,
                    "lexical_signal": True,
                },
            },
        ],
        trace={"query_intent": "entity_lookup", "grounding_policy": "strict"},
    )

    answer, citations, supported, abstained, confidence = service._synthesize_answer("tell me about the CTO", recall_result)

    assert supported is True
    assert abstained is False
    assert confidence >= 0.7
    assert "leads engineering strategy" in answer
    assert "not enough exact context" not in answer
    assert len(citations) == 2


def test_synthesize_answer_refuses_to_invent_named_person_for_role_lookup():
    service = ConversationService()
    recall_result = SimpleNamespace(
        items=[
            {
                "memory_id": "mem-cto-1",
                "layer": MemoryLayer.LONG_TERM,
                "content": "Chief Technology Officer (CTO) leads engineering strategy, platform architecture, and reliability governance.",
                "metadata": {
                    "retrieval_score": 6.2,
                    "grounding_signal": True,
                    "entity_match": True,
                    "lexical_signal": True,
                },
            }
        ],
        trace={"query_intent": "entity_lookup", "grounding_policy": "strict"},
    )

    answer, citations, supported, abstained, confidence = service._synthesize_answer("who is the CTO", recall_result)

    assert supported is True
    assert abstained is False
    assert confidence >= 0.7
    assert "do not yet have a named person" in answer
    assert "leads engineering strategy" in answer
    assert len(citations) == 1


def test_classify_text_flags_elevated_risk_for_secret_handling():
    service = ConversationService()

    result = service._classify_text(
        "How should we rotate auth tokens and password secrets?",
        supported=True,
        abstained=False,
        citations=2,
    )

    assert result["conversation_type"] in {"implementation", "research"}
    assert result["risk_level"] == "elevated"
    assert result["outcome"] == "resolved"


def test_scoped_agent_storage_id_changes_with_scope_but_is_stable_per_scope():
    service = ConversationService()

    first = service._scoped_agent_storage_id("org-a", "app-a", "memory-assistant")
    second = service._scoped_agent_storage_id("org-a", "app-a", "memory-assistant")
    different_app = service._scoped_agent_storage_id("org-a", "app-b", "memory-assistant")

    assert first == second
    assert first != different_app
    assert first.startswith("agt_")


def test_json_safe_payload_converts_enums_and_datetimes():
    service = ConversationService()

    payload = service._json_safe_payload(
        {
            "layer": MemoryLayer.LONG_TERM,
            "scope": MemoryScope.APP,
            "created_at": datetime(2026, 3, 25, 15, 30, tzinfo=UTC),
        }
    )

    assert payload["layer"] == "long_term"
    assert payload["scope"] == "app"
    assert payload["created_at"] == "2026-03-25T15:30:00Z"
