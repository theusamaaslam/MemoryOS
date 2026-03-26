from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func

from app.core.db import session_scope
from app.models.domain import ConversationStatus, InteractionEvent, MemoryCandidateStatus, MemoryLayer, MemoryRecord, MemoryScope, Outcome, Scope
from app.models.persistence import (
    AgentModel,
    AnswerAuditModel,
    ConversationLabelModel,
    ConversationMessageModel,
    ConversationModel,
    ConversationTurnModel,
    EntityAliasModel,
    GraphEdgeModel,
    GraphNodeModel,
    MemoryCandidateModel,
    RetrievalTraceModel,
    ToolInvocationModel,
)
from app.services.jobs import job_service
from app.services.memory import memory_service


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _truncate(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


_FRAGMENT_QUERY_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "can",
    "do",
    "does",
    "explain",
    "for",
    "give",
    "hello",
    "help",
    "hi",
    "how",
    "i",
    "is",
    "it",
    "me",
    "more",
    "please",
    "tell",
    "the",
    "this",
    "what",
    "who",
}


class ConversationService:
    def _normalize_utc_timestamps(self, value):
        if isinstance(value, dict):
            return {key: self._normalize_utc_timestamps(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize_utc_timestamps(item) for item in value]
        if isinstance(value, str) and value.endswith("+00:00"):
            return value[:-6] + "Z"
        return value

    def _json_safe_payload(self, value):
        if hasattr(value, "model_dump"):
            return self._normalize_utc_timestamps(value.model_dump(mode="json"))
        return self._normalize_utc_timestamps(jsonable_encoder(value))

    def _scoped_agent_storage_id(self, org_id: str, app_id: str, public_agent_id: str) -> str:
        digest = hashlib.sha1(f"{org_id}|{app_id}|{public_agent_id}".encode("utf-8")).hexdigest()
        return f"agt_{digest[:40]}"

    def _agent_public_id(self, agent: AgentModel | None, fallback: str) -> str:
        if agent is None:
            return fallback
        return (agent.public_agent_id or agent.agent_id or fallback).strip() or fallback

    def _ensure_org_access(self, identity: dict, org_id: str) -> None:
        if str(identity.get("org_id") or "") != str(org_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another organization")

    def _ensure_conversation_access(self, identity: dict, conversation: ConversationModel) -> None:
        self._ensure_org_access(identity, conversation.org_id)
        if identity.get("key_id"):
            if identity.get("app_id") != conversation.app_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is scoped to another app")
            return
        if identity.get("role") in {"owner", "admin"}:
            return
        if str(identity.get("sub") or "") != conversation.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's conversation")

    def _ensure_agent(self, org_id: str, app_id: str, agent_id: str, *, title: str | None, description: str | None) -> AgentModel:
        public_agent_id = agent_id.strip()
        if not public_agent_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent id is required")
        now = _utcnow()
        with session_scope() as session:
            agent = (
                session.query(AgentModel)
                .filter_by(org_id=org_id, app_id=app_id, public_agent_id=public_agent_id)
                .first()
            )
            if agent is None:
                agent = (
                    session.query(AgentModel)
                    .filter_by(org_id=org_id, app_id=app_id, agent_id=public_agent_id)
                    .first()
                )
            if agent is not None:
                if not agent.public_agent_id:
                    agent.public_agent_id = public_agent_id
                if description and description.strip():
                    agent.description = description.strip()
                if title and title.strip():
                    agent.name = title.strip()
                agent.updated_at = now
                return agent
            agent = AgentModel(
                agent_id=self._scoped_agent_storage_id(org_id, app_id, public_agent_id),
                org_id=org_id,
                app_id=app_id,
                public_agent_id=public_agent_id,
                name=(title or public_agent_id).strip() or public_agent_id,
                description=(description or "").strip(),
                created_at=now,
                updated_at=now,
            )
            session.add(agent)
            return agent

    def _conversation_scope(self, conversation: ConversationModel) -> Scope:
        return Scope(
            org_id=conversation.org_id,
            app_id=conversation.app_id,
            user_id=conversation.user_id,
            session_id=conversation.conversation_id,
        )

    def _label_response(self, label: ConversationLabelModel | None) -> dict:
        if label is None:
            return {
                "conversation_type": "general",
                "topic": "general",
                "outcome": "open",
                "escalation_state": "none",
                "satisfaction": "unknown",
                "hallucination_suspected": False,
                "risk_level": "normal",
                "memory_impact_score": 0.0,
                "metadata": {},
            }
        return {
            "conversation_type": label.conversation_type,
            "topic": label.topic,
            "outcome": label.outcome,
            "escalation_state": label.escalation_state,
            "satisfaction": label.satisfaction,
            "hallucination_suspected": bool(label.hallucination_suspected),
            "risk_level": label.risk_level,
            "memory_impact_score": float(label.memory_impact_score or 0.0),
            "metadata": label.metadata_json or {},
        }

    def _message_response(self, message: ConversationMessageModel) -> dict:
        return {
            "message_id": message.message_id,
            "role": message.role,
            "content": message.content,
            "citations": message.citations_json or [],
            "metadata": message.metadata_json or {},
            "created_at": message.created_at,
        }

    def _summary_response(self, conversation: ConversationModel, label: ConversationLabelModel | None, agent: AgentModel | None = None) -> dict:
        return {
            "conversation_id": conversation.conversation_id,
            "app_id": conversation.app_id,
            "user_id": conversation.user_id,
            "agent_id": self._agent_public_id(agent, conversation.agent_id),
            "title": conversation.title,
            "status": conversation.status,
            "summary": conversation.summary,
            "message_count": int(conversation.message_count or 0),
            "last_message_at": conversation.last_message_at,
            "created_at": conversation.created_at,
            "label": self._label_response(label),
        }

    def _conversation_response(
        self,
        conversation: ConversationModel,
        label: ConversationLabelModel | None,
        turns: list[ConversationTurnModel],
        messages: list[ConversationMessageModel],
        agent: AgentModel | None = None,
    ) -> dict:
        messages_by_turn: dict[str, list[ConversationMessageModel]] = {}
        for message in messages:
            if message.turn_id:
                messages_by_turn.setdefault(message.turn_id, []).append(message)
        return {
            "conversation_id": conversation.conversation_id,
            "org_id": conversation.org_id,
            "app_id": conversation.app_id,
            "user_id": conversation.user_id,
            "agent_id": self._agent_public_id(agent, conversation.agent_id),
            "title": conversation.title,
            "status": conversation.status,
            "summary": conversation.summary,
            "message_count": int(conversation.message_count or 0),
            "last_message_at": conversation.last_message_at,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "label": self._label_response(label),
            "turns": [
                {
                    "turn_id": turn.turn_id,
                    "turn_index": turn.turn_index,
                    "status": turn.status,
                    "summary": turn.summary,
                    "messages": [self._message_response(message) for message in sorted(messages_by_turn.get(turn.turn_id, []), key=lambda item: item.created_at)],
                    "created_at": turn.created_at,
                    "updated_at": turn.updated_at,
                }
                for turn in sorted(turns, key=lambda item: item.turn_index)
            ],
        }

    def start_conversation(
        self,
        *,
        org_id: str,
        app_id: str,
        user_id: str,
        agent_id: str,
        title: str | None,
        description: str | None,
        metadata: dict | None = None,
    ) -> dict:
        agent = self._ensure_agent(org_id, app_id, agent_id, title=title, description=description)
        now = _utcnow()
        conversation_id = f"conv-{uuid4().hex}"
        with session_scope() as session:
            conversation = ConversationModel(
                conversation_id=conversation_id,
                org_id=org_id,
                app_id=app_id,
                agent_id=agent.agent_id,
                user_id=user_id,
                title=(title or f"{agent_id} conversation").strip() or f"{agent_id} conversation",
                status=ConversationStatus.ACTIVE.value,
                summary="",
                message_count=0,
                last_message_at=None,
                created_at=now,
                updated_at=now,
            )
            session.add(conversation)
            session.flush()
            session.add(
                ConversationLabelModel(
                    conversation_id=conversation_id,
                    conversation_type="general",
                    topic="general",
                    outcome="open",
                    escalation_state="none",
                    satisfaction="unknown",
                    hallucination_suspected=False,
                    risk_level="normal",
                    memory_impact_score=0.0,
                    metadata_json=metadata or {},
                    updated_at=now,
                )
            )
        return self.get_conversation({"org_id": org_id, "sub": user_id, "role": "owner"}, conversation_id)

    def _classify_text(self, text: str, *, supported: bool, abstained: bool, citations: int) -> dict:
        normalized = _normalize_text(text)
        type_map = {
            "billing": {"refund", "invoice", "payment", "charge", "billing"},
            "support": {"issue", "error", "failed", "problem", "bug", "incident"},
            "implementation": {"api", "code", "build", "deploy", "sdk", "integration"},
            "research": {"how", "why", "compare", "explain", "architecture"},
        }
        conversation_type = "general"
        for candidate, keywords in type_map.items():
            if any(keyword in normalized for keyword in keywords):
                conversation_type = candidate
                break

        risk_level = "normal"
        if any(keyword in normalized for keyword in {"security", "password", "token", "auth", "secret", "pii"}):
            risk_level = "elevated"
        if any(keyword in normalized for keyword in {"medical", "legal", "financial"}):
            risk_level = "high"

        topic = "general"
        for keyword in normalized.split():
            if len(keyword) >= 4:
                topic = keyword
                break

        outcome = "resolved" if supported and not abstained else "open"
        escalation_state = "review" if abstained else "none"
        memory_impact = min(1.0, 0.2 + (0.2 * citations) + (0.3 if supported else 0.0))
        return {
            "conversation_type": conversation_type,
            "topic": topic,
            "outcome": outcome,
            "escalation_state": escalation_state,
            "satisfaction": "unknown",
            "hallucination_suspected": False,
            "risk_level": risk_level,
            "memory_impact_score": round(memory_impact, 4),
            "metadata_json": {},
        }

    def _split_grounded_fragments(self, text: str) -> list[str]:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip())
        if not cleaned:
            return []
        fragments = [
            fragment.strip(" -")
            for fragment in re.split(r"(?<=[.!?])\s+|(?<=:)\s+|\s*[;\n]\s*", cleaned)
            if fragment.strip()
        ]
        return fragments or [cleaned]

    def _best_grounded_fragment(self, query: str, content: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(content or "").strip())
        if not cleaned:
            return ""
        normalized_query = _normalize_text(query)
        query_terms = [
            term
            for term in normalized_query.split()
            if len(term) >= 3 and term not in _FRAGMENT_QUERY_STOPWORDS
        ]
        alias_terms = [
            alias
            for alias in memory_service._entity_aliases_for_query(query)
            if alias and alias not in _FRAGMENT_QUERY_STOPWORDS
        ]
        fragments = self._split_grounded_fragments(cleaned)
        if not fragments:
            return _truncate(cleaned, 220)

        best_fragment = fragments[0]
        best_score = -1.0
        for fragment in fragments:
            normalized_fragment = _normalize_text(fragment)
            lexical_hits = sum(1 for term in query_terms if term in normalized_fragment)
            alias_hits = sum(1 for alias in alias_terms if alias in normalized_fragment)
            exact_match = 1 if normalized_query and normalized_query in normalized_fragment else 0
            starts_strong = 1 if not normalized_fragment.startswith(("and ", "or ", "but ", "moreover ", "however ")) else 0
            compact_bonus = 1 if 28 <= len(fragment) <= 180 else 0
            score = (
                lexical_hits * 2.2
                + alias_hits * 2.8
                + exact_match * 2.5
                + starts_strong * 0.4
                + compact_bonus * 0.3
            )
            if score > best_score:
                best_score = score
                best_fragment = fragment

        best_fragment = best_fragment.rstrip()
        if best_fragment and best_fragment[-1] not in ".!?":
            best_fragment += "."
        return _truncate(best_fragment, 220)

    def _compose_grounded_answer(self, query: str, citations: list[dict], trace_payload: dict) -> str:
        intent = str(trace_payload.get("query_intent", "general") or "general")
        grounded_points: list[tuple[str, int]] = []
        seen_fragments: set[str] = set()

        for index, citation in enumerate(citations[:3], start=1):
            fragment = self._best_grounded_fragment(query, citation["content"])
            normalized_fragment = _normalize_text(fragment)
            if not fragment or normalized_fragment in seen_fragments:
                continue
            seen_fragments.add(normalized_fragment)
            grounded_points.append((fragment, index))

        if not grounded_points:
            grounded_points.append((_truncate(citations[0]["content"], 220), 1))

        if intent == "entity_lookup":
            lead, marker = grounded_points[0]
            answer = f"Based on the current grounded memory, {lead} [M{marker}]"
            if len(grounded_points) > 1:
                follow_up, follow_marker = grounded_points[1]
                answer += f" Related evidence also says {follow_up} [M{follow_marker}]"
            return answer

        if len(grounded_points) == 1:
            lead, marker = grounded_points[0]
            return f"Based on the current grounded memory, {lead} [M{marker}]"

        lead, lead_marker = grounded_points[0]
        follow_up, follow_marker = grounded_points[1]
        return (
            f"Based on the current grounded memory, {lead} [M{lead_marker}] "
            f"Related evidence also says {follow_up} [M{follow_marker}]"
        )

    def _query_requests_named_person(self, query: str) -> bool:
        normalized_query = _normalize_text(query)
        return any(
            phrase in normalized_query
            for phrase in (
                "who is",
                "who s",
                "name of",
                "named",
                "which person",
                "person is",
                "current holder",
            )
        )

    def _fragment_is_descriptive(self, fragment: str, alias: str | None) -> bool:
        normalized_fragment = _normalize_text(fragment)
        normalized_alias = _normalize_text(alias or "")
        if len(normalized_fragment) < 30:
            return False
        if normalized_alias and normalized_fragment == normalized_alias:
            return False
        descriptive_terms = {
            "lead",
            "leads",
            "owns",
            "oversee",
            "oversees",
            "responsible",
            "manages",
            "partners",
            "coordinates",
            "governance",
            "strategy",
            "architecture",
            "reliability",
            "planning",
            "security",
        }
        return any(term in normalized_fragment for term in descriptive_terms)

    def _synthesize_answer(self, query: str, recall_result) -> tuple[str, list[dict], bool, bool, float]:
        items = [item.model_dump() if hasattr(item, "model_dump") else dict(item) for item in recall_result.items]
        trace_payload = recall_result.trace.model_dump() if hasattr(recall_result.trace, "model_dump") else dict(recall_result.trace)
        citations = [
            {
                "memory_id": item["memory_id"],
                "layer": str(item["layer"].value if hasattr(item["layer"], "value") else item["layer"]),
                "content": _truncate(item["content"], 320),
                "score": float((item.get("metadata") or {}).get("retrieval_score", 0.0) or 0.0),
                "lexical_signal": bool((item.get("metadata") or {}).get("lexical_signal")),
                "grounding_signal": bool((item.get("metadata") or {}).get("grounding_signal")),
                "entity_match": bool((item.get("metadata") or {}).get("entity_match")),
            }
            for item in items[:3]
        ]
        if not citations:
            return (
                "I do not have enough grounded evidence to answer that confidently yet. Add more source material or ask a narrower question.",
                [],
                False,
                True,
                0.18,
            )
        strict_lookup = str(trace_payload.get("grounding_policy", "balanced")) == "strict" or str(
            trace_payload.get("query_intent", "general")
        ) in {"entity_lookup", "policy_lookup", "reference_lookup"}
        if strict_lookup:
            grounded_citations = [
                citation
                for citation in citations
                if citation["grounding_signal"] or citation["entity_match"] or citation["lexical_signal"]
            ]
            if not grounded_citations:
                return (
                    "I could not find an exact grounded match for that entity or title in the current memory scope. Ask for a specific document, or ingest the missing source first.",
                    citations,
                    False,
                    True,
                    0.24,
                )
            citations = grounded_citations
        if str(trace_payload.get("query_intent", "general")) == "entity_lookup" and items:
            top_item = items[0]
            top_content = str(top_item.get("content") or "")
            normalized_top_content = memory_service._normalize_search_text(top_content)
            grounded_alias = next(
                (
                    alias
                    for alias in memory_service._entity_aliases_for_query(query)
                    if alias and alias in normalized_top_content
                ),
                None,
            )
            if grounded_alias:
                role_name = grounded_alias.upper() if " " not in grounded_alias and len(grounded_alias) <= 5 else grounded_alias.title()
                top_fragment = self._best_grounded_fragment(query, top_content)
                descriptive_fragment = self._fragment_is_descriptive(top_fragment, grounded_alias)
                named_person_request = self._query_requests_named_person(query)
                if "company organogram" in normalized_top_content or "organizational structure" in normalized_top_content:
                    answer = (
                        f"The grounded memory identifies this role as {role_name}. It appears in the company organogram"
                        " but I do not yet have a dedicated profile or named person for this role in the current memory."
                    )
                    if descriptive_fragment:
                        answer += f" The strongest grounded description says {top_fragment} [M1]"
                    return (
                        answer,
                        citations[:1],
                        True,
                        False,
                        0.71 if descriptive_fragment else 0.68,
                    )
                if named_person_request and not descriptive_fragment:
                    return (
                        f"The grounded memory identifies the role {role_name}, but I do not yet have a named person attached to that role in the current memory.",
                        citations[:1],
                        True,
                        False,
                        0.64,
                    )
                if named_person_request and descriptive_fragment:
                    return (
                        f"The grounded memory describes the role {role_name} as {top_fragment} [M1] I do not yet have a named person attached to that role in the current memory.",
                        citations[:1],
                        True,
                        False,
                        0.72,
                    )
        strongest = max(citation["score"] for citation in citations)
        if strongest < 1.15:
            grounded_context = [self._best_grounded_fragment(query, citation["content"]) for citation in citations[:2]]
            grounded_context = [snippet for snippet in grounded_context if snippet]
            answer = "I found only weak supporting evidence, so I should not answer definitively."
            if grounded_context:
                answer += " The closest grounded context is "
                answer += " ".join(f"{snippet} [M{index}]" for index, snippet in enumerate(grounded_context, start=1))
            return answer, citations, False, True, min(0.42, 0.2 + strongest / 4)

        answer_lines = [self._compose_grounded_answer(query, citations, trace_payload)]
        if len(query.split()) <= 6 and str(trace_payload.get("query_intent", "general")) != "entity_lookup":
            answer_lines.append("Ask a more specific follow-up if you want me to narrow this to one exact policy, workflow, or document.")
        confidence = min(0.94, 0.45 + (strongest / 4))
        return "\n".join(answer_lines), citations, True, False, round(confidence, 4)

    def _upsert_label(self, conversation_id: str, payload: dict) -> None:
        now = _utcnow()
        with session_scope() as session:
            label = session.get(ConversationLabelModel, conversation_id)
            if label is None:
                label = ConversationLabelModel(conversation_id=conversation_id, updated_at=now)
                session.add(label)
            label.conversation_type = payload["conversation_type"]
            label.topic = payload["topic"]
            label.outcome = payload["outcome"]
            label.escalation_state = payload["escalation_state"]
            label.satisfaction = payload["satisfaction"]
            label.hallucination_suspected = bool(payload["hallucination_suspected"])
            label.risk_level = payload["risk_level"]
            label.memory_impact_score = float(payload["memory_impact_score"])
            label.metadata_json = payload.get("metadata_json", {})
            label.updated_at = now

    def send_message(self, identity: dict, conversation_id: str, content: str, *, top_k: int = 5, metadata: dict | None = None) -> dict:
        content = content.strip()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message content is required")

        with session_scope() as session:
            conversation = session.get(ConversationModel, conversation_id)
            if conversation is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            self._ensure_conversation_access(identity, conversation)
            if conversation.status == ConversationStatus.ARCHIVED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Conversation is closed. Start a new conversation to continue.",
                )
            turn_index = int(
                session.query(func.coalesce(func.max(ConversationTurnModel.turn_index), 0))
                .filter_by(conversation_id=conversation_id)
                .scalar()
                or 0
            ) + 1
            now = _utcnow()
            turn_id = f"turn-{uuid4().hex}"
            user_message_id = f"msg-{uuid4().hex}"
            session.add(
                ConversationTurnModel(
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                    turn_index=turn_index,
                    user_message_id=None,
                    assistant_message_id=None,
                    status="running",
                    summary=_truncate(content, 180),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                ConversationMessageModel(
                    message_id=user_message_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    role="user",
                    content=content,
                    citations_json=[],
                    metadata_json=metadata or {},
                    created_at=now,
                )
            )
            session.flush()
            turn = session.get(ConversationTurnModel, turn_id)
            if turn is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation turn could not be initialized")
            turn.user_message_id = user_message_id
            conversation.last_message_at = now
            conversation.message_count = int(conversation.message_count or 0) + 1
            conversation.summary = _truncate(content, 220)
            conversation.updated_at = now
            conversation_snapshot = {
                "org_id": conversation.org_id,
                "app_id": conversation.app_id,
                "user_id": conversation.user_id,
                "agent_id": conversation.agent_id,
                "title": conversation.title,
            }

        scope = Scope(
            org_id=conversation_snapshot["org_id"],
            app_id=conversation_snapshot["app_id"],
            user_id=conversation_snapshot["user_id"],
            session_id=conversation_id,
        )
        started = time.perf_counter()
        recall_result = memory_service.recall(scope, content, max(top_k, 8), None)
        answer_text, citations, supported, abstained, confidence = self._synthesize_answer(content, recall_result)
        latency_ms = int((time.perf_counter() - started) * 1000)
        trace_id = f"trace-{uuid4().hex}"
        audit_id = f"audit-{uuid4().hex}"
        assistant_message_id = f"msg-{uuid4().hex}"
        now = _utcnow()

        with session_scope() as session:
            conversation = session.get(ConversationModel, conversation_id)
            turn = session.get(ConversationTurnModel, turn_id)
            if conversation is None or turn is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation state was lost")
            session.add(
                ConversationMessageModel(
                    message_id=assistant_message_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    role="assistant",
                    content=answer_text,
                    citations_json=citations,
                    metadata_json={
                        "supported": supported,
                        "abstained": abstained,
                        "confidence": confidence,
                        "provider": "heuristic",
                    },
                    created_at=now,
                )
            )
            session.flush()
            trace_payload = self._json_safe_payload(recall_result.trace)
            items_payload = [self._json_safe_payload(item) for item in recall_result.items]
            session.add(
                RetrievalTraceModel(
                    trace_id=trace_id,
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    query=content,
                    items_json=items_payload,
                    trace_json=trace_payload,
                    created_at=now,
                )
            )
            session.add(
                AnswerAuditModel(
                    audit_id=audit_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    provider="heuristic",
                    model_name="grounded_extract_v1",
                    latency_ms=latency_ms,
                    confidence=confidence,
                    supported=supported,
                    abstained=abstained,
                    metadata_json={"citation_count": len(citations), "query": content},
                    created_at=now,
                )
            )
            session.add(
                ToolInvocationModel(
                    invocation_id=f"tool-{uuid4().hex}",
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    tool_name="recall",
                    payload_json={"query": content, "top_k": top_k},
                    result_json={"trace_id": trace_id, "items": [citation["memory_id"] for citation in citations]},
                    created_at=now,
                )
            )
            turn.assistant_message_id = assistant_message_id
            turn.status = "completed"
            turn.summary = _truncate(f"{content} -> {answer_text}", 220)
            turn.updated_at = now

            conversation.last_message_at = now
            conversation.message_count = int(conversation.message_count or 0) + 1
            conversation.summary = _truncate(answer_text, 240)
            conversation.updated_at = now
            if supported:
                conversation.status = ConversationStatus.RESOLVED.value

        memory_service.append_event(
            InteractionEvent(
                scope=scope,
                role="user",
                content=content,
                metadata={"conversation_id": conversation_id, **(metadata or {})},
                outcome=Outcome.UNKNOWN,
            )
        )
        memory_service.remember(
            MemoryRecord(
                layer=MemoryLayer.SESSION,
                scope=scope,
                content=f"user: {content}",
                metadata={"kind": "conversation_turn", "role": "user", "conversation_id": conversation_id},
                tags=["conversation", "user"],
                source="conversation_runtime",
            )
        )
        memory_service.append_event(
            InteractionEvent(
                scope=scope,
                role="assistant",
                content=answer_text,
                metadata={"conversation_id": conversation_id, "supported": supported, "abstained": abstained},
                outcome=Outcome.SUCCESS if supported else Outcome.PARTIAL,
            )
        )
        memory_service.remember(
            MemoryRecord(
                layer=MemoryLayer.SESSION,
                scope=scope,
                content=f"assistant: {answer_text}",
                metadata={
                    "kind": "conversation_turn",
                    "role": "assistant",
                    "conversation_id": conversation_id,
                    "citations": [citation["memory_id"] for citation in citations],
                },
                tags=["conversation", "assistant"],
                source="conversation_runtime",
            )
        )

        classification = self._classify_text(content, supported=supported, abstained=abstained, citations=len(citations))
        self._upsert_label(conversation_id, classification)
        job_service.enqueue_reflection_if_due(scope, "conversation_turn_completed")
        conversation_payload = self.get_conversation(identity, conversation_id)
        conversation_summary = {
            key: conversation_payload[key]
            for key in ("conversation_id", "app_id", "user_id", "agent_id", "title", "status", "summary", "message_count", "last_message_at", "created_at", "label")
        }
        user_message_payload = next(
            message
            for turn in conversation_payload["turns"]
            for message in turn["messages"]
            if message["message_id"] == user_message_id
        )
        assistant_message_payload = next(
            message
            for turn in conversation_payload["turns"]
            for message in turn["messages"]
            if message["message_id"] == assistant_message_id
        )
        return {
            "conversation": conversation_summary,
            "user_message": user_message_payload,
            "assistant_message": assistant_message_payload,
            "citations": citations,
            "supported": supported,
            "abstained": abstained,
            "trace_id": trace_id,
            "audit_id": audit_id,
        }

    def get_conversation(self, identity: dict, conversation_id: str) -> dict:
        with session_scope() as session:
            conversation = session.get(ConversationModel, conversation_id)
            if conversation is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            self._ensure_conversation_access(identity, conversation)
            label = session.get(ConversationLabelModel, conversation_id)
            turns = (
                session.query(ConversationTurnModel)
                .filter_by(conversation_id=conversation_id)
                .order_by(ConversationTurnModel.turn_index.asc())
                .all()
            )
            messages = (
                session.query(ConversationMessageModel)
                .filter_by(conversation_id=conversation_id)
                .order_by(ConversationMessageModel.created_at.asc())
                .all()
            )
            agent = session.get(AgentModel, conversation.agent_id)
            return self._conversation_response(conversation, label, turns, messages, agent)

    def close_conversation(self, identity: dict, conversation_id: str, *, reason: str | None = None) -> dict:
        now = _utcnow()
        with session_scope() as session:
            conversation = session.get(ConversationModel, conversation_id)
            if conversation is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            self._ensure_conversation_access(identity, conversation)
            if conversation.status != ConversationStatus.ARCHIVED.value:
                conversation.status = ConversationStatus.ARCHIVED.value
                conversation.updated_at = now
                label = session.get(ConversationLabelModel, conversation_id)
                if label is not None:
                    metadata = dict(label.metadata_json or {})
                    metadata["closed_at"] = now.isoformat()
                    if reason:
                        metadata["closure_reason"] = reason
                    label.metadata_json = metadata
                    if label.outcome == "open":
                        label.outcome = "closed"
                    label.updated_at = now
                session.add(
                    ToolInvocationModel(
                        invocation_id=f"tool-{uuid4().hex}",
                        conversation_id=conversation_id,
                        turn_id=None,
                        tool_name="close_conversation",
                        payload_json={"conversation_id": conversation_id, "reason": reason or ""},
                        result_json={"status": "archived"},
                        created_at=now,
                    )
                )
        return self.get_conversation(identity, conversation_id)

    def list_conversations(
        self,
        identity: dict,
        *,
        org_id: str | None = None,
        app_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
        admin: bool = False,
    ) -> dict:
        requested_org_id = org_id or identity.get("org_id")
        if not requested_org_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization scope is required")
        self._ensure_org_access(identity, requested_org_id)

        with session_scope() as session:
            query = session.query(ConversationModel).filter_by(org_id=requested_org_id)
            if app_id:
                if identity.get("key_id") and identity.get("app_id") != app_id:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is scoped to another app")
                query = query.filter_by(app_id=app_id)
            elif identity.get("key_id"):
                query = query.filter_by(app_id=identity["app_id"])

            if admin:
                if user_id:
                    query = query.filter_by(user_id=user_id)
            elif identity.get("key_id"):
                if user_id:
                    query = query.filter_by(user_id=user_id)
            else:
                query = query.filter_by(user_id=str(identity.get("sub") or ""))

            conversations = query.order_by(ConversationModel.updated_at.desc()).limit(max(limit, 1)).all()
            ids = [item.conversation_id for item in conversations]
            labels = {
                row.conversation_id: row
                for row in session.query(ConversationLabelModel)
                .filter(ConversationLabelModel.conversation_id.in_(ids or [""]))
                .all()
            }
            agents = {
                row.agent_id: row
                for row in session.query(AgentModel)
                .filter(AgentModel.agent_id.in_([item.agent_id for item in conversations] or [""]))
                .all()
            }
        return {"items": [self._summary_response(item, labels.get(item.conversation_id), agents.get(item.agent_id)) for item in conversations]}

    def classify_conversation(self, identity: dict, conversation_id: str) -> dict:
        conversation = self.get_conversation(identity, conversation_id)
        joined_text = "\n".join(message["content"] for turn in conversation["turns"] for message in turn["messages"])
        supported = any(
            bool(message["metadata"].get("supported"))
            for turn in conversation["turns"]
            for message in turn["messages"]
            if message["role"] == "assistant"
        )
        abstained = any(
            bool(message["metadata"].get("abstained"))
            for turn in conversation["turns"]
            for message in turn["messages"]
            if message["role"] == "assistant"
        )
        citations = sum(
            len(message["citations"])
            for turn in conversation["turns"]
            for message in turn["messages"]
            if message["role"] == "assistant"
        )
        payload = self._classify_text(joined_text, supported=supported, abstained=abstained, citations=citations)
        self._upsert_label(conversation_id, payload)
        return self.get_conversation(identity, conversation_id)["label"]

    def explain_answer(self, identity: dict, conversation_id: str) -> dict:
        with session_scope() as session:
            conversation = session.get(ConversationModel, conversation_id)
            if conversation is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            self._ensure_conversation_access(identity, conversation)
            trace = (
                session.query(RetrievalTraceModel)
                .filter_by(conversation_id=conversation_id)
                .order_by(RetrievalTraceModel.created_at.desc())
                .first()
            )
            if trace is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No retrieval trace found for this conversation")
            audit = (
                session.query(AnswerAuditModel)
                .filter_by(conversation_id=conversation_id)
                .order_by(AnswerAuditModel.created_at.desc())
                .first()
            )
        return {
            "trace_id": trace.trace_id,
            "query": trace.query,
            "items": trace.items_json or [],
            "trace": trace.trace_json or {},
            "audit": {
                "audit_id": audit.audit_id if audit else "",
                "provider": audit.provider if audit else "unknown",
                "model_name": audit.model_name if audit else "",
                "latency_ms": int(audit.latency_ms or 0) if audit else 0,
                "confidence": float(audit.confidence or 0.0) if audit else 0.0,
                "supported": bool(audit.supported) if audit else False,
                "abstained": bool(audit.abstained) if audit else False,
                "metadata": audit.metadata_json if audit else {},
            },
        }

    def _normalized_candidate_key(self, content: str) -> str:
        return _normalize_text(content)[:240]

    def _memory_scope_for_candidate(self, kind: str) -> MemoryScope:
        if kind == "preference":
            return MemoryScope.USER
        if kind in {"fact", "failure", "resolution"}:
            return MemoryScope.APP
        return MemoryScope.CONVERSATION

    def _candidate_rows_to_response(self, rows: list[MemoryCandidateModel]) -> dict:
        return {
            "items": [
                {
                    "candidate_id": row.candidate_id,
                    "org_id": row.org_id,
                    "app_id": row.app_id,
                    "user_id": row.user_id,
                    "conversation_id": row.conversation_id,
                    "memory_scope": MemoryScope(row.memory_scope),
                    "layer": MemoryLayer(row.layer),
                    "content": row.content,
                    "status": MemoryCandidateStatus(row.status),
                    "confidence": row.confidence,
                    "source_memory_ids": row.source_memory_ids_json or [],
                    "metadata": row.metadata_json or {},
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ]
        }

    def _find_existing_candidate(
        self,
        rows: list[MemoryCandidateModel],
        *,
        conversation_id: str,
        normalized_key: str,
    ) -> MemoryCandidateModel | None:
        for row in rows:
            if row.conversation_id != conversation_id:
                continue
            if self._normalized_candidate_key(row.content) == normalized_key:
                return row
        return None

    def _merge_graph_edges_after_entity_merge(self, session, *, org_id: str, app_id: str) -> None:
        seen_edges: dict[tuple[str, str, str, str, str, str, str], GraphEdgeModel] = {}
        edges = session.query(GraphEdgeModel).filter_by(org_id=org_id, app_id=app_id).all()
        for edge in edges:
            if edge.from_node == edge.to_node:
                session.delete(edge)
                continue
            key = (
                edge.user_id,
                edge.graph_scope,
                edge.scope_ref or "",
                edge.conversation_id or "",
                edge.from_node,
                edge.to_node,
                edge.relation,
            )
            existing = seen_edges.get(key)
            if existing is None:
                seen_edges[key] = edge
                continue
            merged_evidence = set(existing.evidence_ids_json or [])
            merged_evidence.update(edge.evidence_ids_json or [])
            existing.evidence_ids_json = sorted(merged_evidence)
            existing.confidence = max(float(existing.confidence or 0.0), float(edge.confidence or 0.0))
            existing.metadata_json = (existing.metadata_json or {}) | (edge.metadata_json or {})
            session.delete(edge)

    def _promote_candidate(self, row: MemoryCandidateModel, *, promotion_status: str) -> None:
        scope = Scope(org_id=row.org_id, app_id=row.app_id, user_id=row.user_id, session_id=row.conversation_id)
        if row.memory_scope == MemoryScope.USER.value:
            scope_ref = row.user_id
        elif row.memory_scope == MemoryScope.APP.value:
            scope_ref = row.app_id
        else:
            scope_ref = row.conversation_id
        memory_service.remember(
            MemoryRecord(
                layer=MemoryLayer(row.layer),
                scope=scope,
                content=row.content,
                metadata=(row.metadata_json or {}) | {"promotion_status": promotion_status, "candidate_id": row.candidate_id},
                confidence=float(row.confidence or 0.5),
                tags=["candidate", promotion_status],
                source="conversation_reflection",
                memory_scope=MemoryScope(row.memory_scope),
                scope_ref=scope_ref,
                conversation_id=row.conversation_id,
            )
        )

    def reflect_conversation(self, identity: dict, conversation_id: str) -> dict:
        with session_scope() as session:
            conversation = session.get(ConversationModel, conversation_id)
            if conversation is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            self._ensure_conversation_access(identity, conversation)
            conversation_updated_at = conversation.updated_at
            latest_reflection = (
                session.query(ToolInvocationModel)
                .filter_by(conversation_id=conversation_id, tool_name="reflect_conversation")
                .order_by(ToolInvocationModel.created_at.desc())
                .first()
            )
            latest_result = dict(latest_reflection.result_json or {}) if latest_reflection is not None else {}
            if latest_result.get("conversation_updated_at") == conversation_updated_at.isoformat():
                return {
                    "job_id": str(uuid4()),
                    "status": "completed",
                    "summary": "No new conversation activity since the last graph append. Existing merged graph is already up to date.",
                    "provider": latest_result.get("provider"),
                }
        scope = self._conversation_scope(conversation)
        provider, artifact, evidence_items = memory_service.generate_reflection_artifact(scope)
        graph_nodes, graph_edges = memory_service.apply_reflection_graph(scope, artifact.entities, artifact.relations, evidence_items)
        now = _utcnow()
        evidence_ids = [item["evidence_id"] for item in evidence_items[:8]]
        created_candidates = 0
        auto_promoted = 0
        candidate_specs = [
            ("fact", MemoryLayer.LONG_TERM, artifact.facts),
            ("preference", MemoryLayer.LONG_TERM, artifact.preferences),
            ("failure", MemoryLayer.FAILURE, artifact.failures),
            ("resolution", MemoryLayer.RESOLUTION, artifact.resolutions),
        ]
        with session_scope() as session:
            for kind, layer, values in candidate_specs:
                for value in values:
                    content = _truncate(value, 1200)
                    if not content:
                        continue
                    normalized_key = self._normalized_candidate_key(content)
                    memory_scope = self._memory_scope_for_candidate(kind)
                    existing_query = session.query(MemoryCandidateModel).filter_by(
                        org_id=conversation.org_id,
                        app_id=conversation.app_id,
                        layer=layer.value,
                        memory_scope=memory_scope.value,
                    )
                    if memory_scope != MemoryScope.APP:
                        existing_query = existing_query.filter_by(user_id=conversation.user_id)
                    existing_rows = existing_query.all()
                    existing_candidate = self._find_existing_candidate(
                        existing_rows,
                        conversation_id=conversation_id,
                        normalized_key=normalized_key,
                    )
                    repeated = any(
                        self._normalized_candidate_key(row.content) == normalized_key and row.conversation_id != conversation_id
                        for row in existing_rows
                    )
                    if existing_candidate is not None:
                        existing_candidate.content = content
                        existing_candidate.confidence = max(float(existing_candidate.confidence or 0.0), 0.76 if kind == "fact" else 0.82 if kind == "preference" else 0.74)
                        merged_sources = set(existing_candidate.source_memory_ids_json or [])
                        merged_sources.update(evidence_ids)
                        existing_candidate.source_memory_ids_json = sorted(merged_sources)
                        existing_candidate.metadata_json = (
                            (existing_candidate.metadata_json or {})
                            | {"kind": kind, "generated_by": provider.name, "normalized_key": normalized_key}
                        )
                        existing_candidate.updated_at = now
                        continue
                    candidate = MemoryCandidateModel(
                        candidate_id=f"cand-{uuid4().hex}",
                        org_id=conversation.org_id,
                        app_id=conversation.app_id,
                        user_id=conversation.user_id,
                        conversation_id=conversation_id,
                        memory_scope=memory_scope.value,
                        layer=layer.value,
                        content=content,
                        status=MemoryCandidateStatus.AUTO_PROMOTED.value if repeated else MemoryCandidateStatus.PENDING.value,
                        confidence=0.76 if kind == "fact" else 0.82 if kind == "preference" else 0.74,
                        source_memory_ids_json=evidence_ids,
                        metadata_json={"kind": kind, "generated_by": provider.name, "normalized_key": normalized_key},
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(candidate)
                    created_candidates += 1
                    if repeated:
                        auto_promoted += 1
                        self._promote_candidate(candidate, promotion_status=MemoryCandidateStatus.AUTO_PROMOTED.value)
            session.add(
                ToolInvocationModel(
                    invocation_id=f"tool-{uuid4().hex}",
                    conversation_id=conversation_id,
                    turn_id=None,
                    tool_name="reflect_conversation",
                    payload_json={"conversation_id": conversation_id},
                    result_json={
                        "provider": provider.name,
                        "nodes": len(graph_nodes),
                        "edges": len(graph_edges),
                        "conversation_updated_at": conversation_updated_at.isoformat(),
                    },
                    created_at=now,
                )
            )
        return {
            "job_id": str(uuid4()),
            "status": "completed",
            "summary": f"Reflection completed via {provider.name}. Merged {len(graph_nodes)} nodes, {len(graph_edges)} edges, and created {created_candidates} memory candidates ({auto_promoted} auto-promoted).",
            "provider": provider.name,
        }

    def list_memory_candidates(
        self,
        identity: dict,
        *,
        org_id: str | None = None,
        app_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 100,
    ) -> dict:
        requested_org_id = org_id or identity.get("org_id")
        if not requested_org_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization scope is required")
        self._ensure_org_access(identity, requested_org_id)
        with session_scope() as session:
            query = session.query(MemoryCandidateModel).filter_by(org_id=requested_org_id)
            if app_id:
                if identity.get("key_id") and identity.get("app_id") != app_id:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is scoped to another app")
                query = query.filter_by(app_id=app_id)
            elif identity.get("key_id"):
                query = query.filter_by(app_id=identity["app_id"])
            if not identity.get("key_id") and identity.get("role") not in {"owner", "admin"}:
                query = query.filter_by(user_id=str(identity.get("sub") or ""))
            if status_filter:
                query = query.filter_by(status=status_filter)
            rows = query.order_by(MemoryCandidateModel.updated_at.desc()).limit(max(limit, 1)).all()
        return self._candidate_rows_to_response(rows)

    def approve_memory_candidate(self, identity: dict, candidate_id: str, *, reason: str | None = None) -> dict:
        with session_scope() as session:
            row = session.get(MemoryCandidateModel, candidate_id)
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory candidate not found")
            self._ensure_org_access(identity, row.org_id)
            if identity.get("key_id") or identity.get("role") not in {"owner", "admin"}:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
            row.status = MemoryCandidateStatus.APPROVED.value
            row.updated_at = _utcnow()
            row.metadata_json = (row.metadata_json or {}) | {"review_reason": reason or ""}
            self._promote_candidate(row, promotion_status=MemoryCandidateStatus.APPROVED.value)
        return self._candidate_rows_to_response([row])

    def reject_memory_candidate(self, identity: dict, candidate_id: str, *, reason: str | None = None) -> dict:
        with session_scope() as session:
            row = session.get(MemoryCandidateModel, candidate_id)
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory candidate not found")
            self._ensure_org_access(identity, row.org_id)
            if identity.get("key_id") or identity.get("role") not in {"owner", "admin"}:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
            row.status = MemoryCandidateStatus.REJECTED.value
            row.updated_at = _utcnow()
            row.metadata_json = (row.metadata_json or {}) | {"review_reason": reason or ""}
        return self._candidate_rows_to_response([row])

    def merge_entities(self, identity: dict, *, org_id: str, app_id: str, canonical_label: str, alias_label: str) -> dict:
        self._ensure_org_access(identity, org_id)
        if identity.get("key_id") or identity.get("role") not in {"owner", "admin"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
        canonical = canonical_label.strip()
        alias = alias_label.strip()
        if not canonical or not alias or canonical.lower() == alias.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide distinct canonical and alias labels")
        now = _utcnow()
        with session_scope() as session:
            existing_alias = (
                session.query(EntityAliasModel)
                .filter_by(org_id=org_id, app_id=app_id)
                .filter(func.lower(EntityAliasModel.canonical_label) == canonical.lower())
                .filter(func.lower(EntityAliasModel.alias_label) == alias.lower())
                .first()
            )
            if existing_alias is None:
                session.add(
                    EntityAliasModel(
                        alias_id=f"alias-{uuid4().hex}",
                        org_id=org_id,
                        app_id=app_id,
                        canonical_label=canonical,
                        alias_label=alias,
                        metadata_json={},
                        created_at=now,
                        updated_at=now,
                    )
                )
            alias_nodes = (
                session.query(GraphNodeModel)
                .filter_by(org_id=org_id, app_id=app_id)
                .filter(func.lower(GraphNodeModel.label) == alias.lower())
                .all()
            )
            for alias_node in alias_nodes:
                canonical_node = (
                    session.query(GraphNodeModel)
                    .filter_by(
                        org_id=alias_node.org_id,
                        app_id=alias_node.app_id,
                        user_id=alias_node.user_id,
                        graph_scope=alias_node.graph_scope,
                        scope_ref=alias_node.scope_ref,
                        conversation_id=alias_node.conversation_id,
                    )
                    .filter(func.lower(GraphNodeModel.label) == canonical.lower())
                    .first()
                )
                if canonical_node is None:
                    alias_node.label = canonical
                    alias_node.metadata_json = (alias_node.metadata_json or {}) | {"merged_from": alias}
                    continue
                merged_evidence = set(canonical_node.evidence_ids_json or [])
                merged_evidence.update(alias_node.evidence_ids_json or [])
                canonical_node.evidence_ids_json = sorted(merged_evidence)
                canonical_node.confidence = max(float(canonical_node.confidence or 0.0), float(alias_node.confidence or 0.0))
                for edge in session.query(GraphEdgeModel).filter_by(from_node=alias_node.node_id).all():
                    edge.from_node = canonical_node.node_id
                for edge in session.query(GraphEdgeModel).filter_by(to_node=alias_node.node_id).all():
                    edge.to_node = canonical_node.node_id
                session.delete(alias_node)
            self._merge_graph_edges_after_entity_merge(session, org_id=org_id, app_id=app_id)
        return {"status": "merged", "canonical_label": canonical, "alias_label": alias}

    def append_graph_update(self, identity: dict, conversation_id: str) -> dict:
        return self.reflect_conversation(identity, conversation_id)

    def rebuild_graph(self, identity: dict, conversation_id: str) -> dict:
        return self.append_graph_update(identity, conversation_id)

    def reflect_conversation_internal(self, conversation_id: str) -> dict:
        with session_scope() as session:
            conversation = session.get(ConversationModel, conversation_id)
            if conversation is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            identity = {
                "org_id": conversation.org_id,
                "app_id": conversation.app_id,
                "sub": conversation.user_id,
                "role": "owner",
            }
        return self.reflect_conversation(identity, conversation_id)

    def get_conversation_trace(self, identity: dict, conversation_id: str) -> dict:
        conversation = self.get_conversation(identity, conversation_id)
        with session_scope() as session:
            traces = (
                session.query(RetrievalTraceModel)
                .filter_by(conversation_id=conversation_id)
                .order_by(RetrievalTraceModel.created_at.desc())
                .all()
            )
            audits = (
                session.query(AnswerAuditModel)
                .filter_by(conversation_id=conversation_id)
                .order_by(AnswerAuditModel.created_at.desc())
                .all()
            )
            tool_invocations = (
                session.query(ToolInvocationModel)
                .filter_by(conversation_id=conversation_id)
                .order_by(ToolInvocationModel.created_at.desc())
                .all()
            )
        return {
            "conversation": conversation,
            "traces": [
                {
                    "trace_id": row.trace_id,
                    "message_id": row.message_id,
                    "query": row.query,
                    "items": row.items_json or [],
                    "trace": row.trace_json or {},
                    "created_at": row.created_at,
                }
                for row in traces
            ],
            "audits": [
                {
                    "audit_id": row.audit_id,
                    "turn_id": row.turn_id,
                    "provider": row.provider,
                    "model_name": row.model_name,
                    "latency_ms": row.latency_ms,
                    "confidence": row.confidence,
                    "supported": row.supported,
                    "abstained": row.abstained,
                    "metadata": row.metadata_json or {},
                    "created_at": row.created_at,
                }
                for row in audits
            ],
            "tool_invocations": [
                {
                    "invocation_id": row.invocation_id,
                    "turn_id": row.turn_id,
                    "tool_name": row.tool_name,
                    "payload": row.payload_json or {},
                    "result": row.result_json or {},
                    "created_at": row.created_at,
                }
                for row in tool_invocations
            ],
        }


conversation_service = ConversationService()
