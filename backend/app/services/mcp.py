from __future__ import annotations

from app.models.domain import InteractionEvent, MemoryRecord, Scope
from app.schemas.conversation import MergeEntitiesRequest, ReviewMemoryCandidateRequest, SendMessageRequest, StartConversationRequest
from app.schemas.memory import EventRequest, FeedbackRequest, RecallRequest, RememberRequest, ScopeRequest
from app.services.conversations import conversation_service
from app.services.memory import memory_service


class MCPService:
    def describe_tools(self) -> list[dict]:
        return [
            {
                "name": "start_conversation",
                "category": "conversation",
                "description": "Open a new server-managed conversation before you call send_message. Use this when an agent needs a fresh chat thread and you want a stable conversation_id tied to the current org, app, and user scope.",
                "required_fields": ["agent_id"],
                "optional_fields": ["app_id", "user_id", "title", "description", "metadata"],
            },
            {
                "name": "send_message",
                "category": "conversation",
                "description": "Send one user turn into an existing conversation and get a grounded assistant reply back. This runs query planning, embeddings recall, graph expansion, reranking, citation building, and audit logging before storing the turn.",
                "required_fields": ["conversation_id", "content"],
                "optional_fields": ["top_k", "metadata"],
            },
            {
                "name": "get_conversation",
                "category": "conversation",
                "description": "Read the full stored conversation state for one conversation_id. Use this to inspect prior turns, messages, citations, labels, and status before resuming or reviewing a thread.",
                "required_fields": ["conversation_id"],
                "optional_fields": [],
            },
            {
                "name": "list_conversations",
                "category": "conversation",
                "description": "List recent conversations in the caller's scope so a client can discover resumeable threads, choose the right conversation_id, or inspect open versus archived sessions.",
                "required_fields": [],
                "optional_fields": ["app_id", "user_id", "limit"],
            },
            {
                "name": "close_conversation",
                "category": "conversation",
                "description": "Archive a conversation when the chat session is finished. Use this to mark a thread closed so it stops acting like an active runtime session and later send_message calls are blocked.",
                "required_fields": ["conversation_id"],
                "optional_fields": ["reason"],
            },
            {
                "name": "classify_conversation",
                "category": "conversation",
                "description": "Recompute the structured label for a conversation after new turns arrive. This refreshes fields like topic, conversation type, risk level, outcome, and memory impact score.",
                "required_fields": ["conversation_id"],
                "optional_fields": [],
            },
            {
                "name": "remember",
                "category": "memory",
                "description": "Write an explicit memory record into the active scope. Use this for facts, preferences, failures, resolutions, or other durable information you want retrieval to find later.",
                "required_fields": ["content"],
                "optional_fields": ["scope", "tags", "metadata", "source", "layer", "memory_scope"],
            },
            {
                "name": "recall",
                "category": "memory",
                "description": "Run hybrid memory retrieval without generating a chat answer. Use this when you want raw evidence items plus retrieval trace data showing how query planning, optional rewrite, embeddings, graph expansion, and reranking behaved.",
                "required_fields": ["query"],
                "optional_fields": ["scope", "top_k", "include_layers"],
            },
            {
                "name": "append_event",
                "category": "memory",
                "description": "Append a raw event to the chronological event stream. Use this for observations, actions, messages, or outcomes that should be stored first and reflected into memory or graph updates later.",
                "required_fields": ["role", "content"],
                "optional_fields": ["scope", "metadata", "outcome"],
            },
            {
                "name": "record_feedback",
                "category": "memory",
                "description": "Store explicit helpful or unhelpful feedback tied to the current scope. Use this after an answer or workflow completes so future retrieval, review, and reflection can learn from what worked or failed.",
                "required_fields": ["summary", "helpful"],
                "optional_fields": ["scope", "event_id", "metadata"],
            },
            {
                "name": "search_graph",
                "category": "graph",
                "description": "Read the grounded knowledge graph for the requested memory scope. Use this when you want nodes, relations, and evidence-linked graph structure instead of normal memory recall results.",
                "required_fields": [],
                "optional_fields": ["scope", "memory_scope"],
            },
            {
                "name": "reflect_session",
                "category": "graph",
                "description": "Trigger reflection for the current scope so recent memories and events can be promoted into longer-term memory and grounded graph updates. Use this after a session accumulates important information.",
                "required_fields": [],
                "optional_fields": ["scope", "memory_scope"],
            },
            {
                "name": "reflect_conversation",
                "category": "graph",
                "description": "Reflect one conversation into reviewable memory candidates and incremental graph updates. Use this when you want to process a specific conversation without touching unrelated graph state.",
                "required_fields": ["conversation_id"],
                "optional_fields": [],
            },
            {
                "name": "explain_answer",
                "category": "review",
                "description": "Explain why the assistant answered the way it did for one conversation. This returns retrieval trace details, selected evidence, and answer audit metadata for operator review or debugging.",
                "required_fields": ["conversation_id"],
                "optional_fields": [],
            },
            {
                "name": "list_memory_candidates",
                "category": "review",
                "description": "List memory candidates created by reflection before they become durable shared memory. Use this to fetch the reviewer inbox of pending facts, preferences, failures, or resolutions.",
                "required_fields": [],
                "optional_fields": ["app_id", "status", "limit"],
            },
            {
                "name": "approve_memory_candidate",
                "category": "review",
                "description": "Approve a reflected memory candidate so it is promoted into durable memory. Use this when the supporting evidence is good and you want the knowledge to become retrievable later.",
                "required_fields": ["candidate_id"],
                "optional_fields": ["reason"],
            },
            {
                "name": "reject_memory_candidate",
                "category": "review",
                "description": "Reject a reflected memory candidate so noisy, duplicate, or incorrect reflection output does not pollute long-term memory or the shared graph.",
                "required_fields": ["candidate_id"],
                "optional_fields": ["reason"],
            },
            {
                "name": "merge_entities",
                "category": "graph",
                "description": "Merge duplicate or alias entity labels into one canonical graph node. Use this for graph repair when two labels refer to the same real thing and you want duplicate or self-loop edges collapsed afterwards.",
                "required_fields": ["app_id", "canonical_label", "alias_label"],
                "optional_fields": [],
            },
            {
                "name": "rebuild_graph",
                "category": "graph",
                "description": "Apply the latest grounded graph merge for one conversation. Despite the historical tool name, this is incremental append-and-merge behavior for that conversation, not a full tenant graph reset.",
                "required_fields": ["conversation_id"],
                "optional_fields": [],
            },
        ]

    def start_conversation(self, identity: dict, agent_id: str, payload: StartConversationRequest):
        if identity.get("key_id") and payload.app_id and payload.app_id != identity.get("app_id"):
            raise ValueError("Requested app does not match the API key scope")
        if not identity.get("key_id") and payload.user_id and identity.get("role") not in {"owner", "admin"} and payload.user_id != identity.get("sub"):
            raise ValueError("Requested user does not match the authenticated user")
        app_id = payload.app_id or identity.get("app_id") or ""
        user_id = payload.user_id or str(identity.get("sub") or identity.get("key_id") or "")
        if not app_id:
            raise ValueError("app_id is required to start a conversation")
        if not user_id:
            raise ValueError("user_id is required to start a conversation")
        return conversation_service.start_conversation(
            org_id=identity["org_id"],
            app_id=app_id,
            user_id=user_id,
            agent_id=agent_id,
            title=payload.title,
            description=payload.description,
            metadata=payload.metadata,
        )

    def send_message(self, identity: dict, conversation_id: str, payload: SendMessageRequest):
        return conversation_service.send_message(identity, conversation_id, payload.content, top_k=payload.top_k, metadata=payload.metadata)

    def get_conversation(self, identity: dict, conversation_id: str):
        return conversation_service.get_conversation(identity, conversation_id)

    def list_conversations(self, identity: dict, *, app_id: str | None = None, user_id: str | None = None, limit: int = 50):
        if identity.get("key_id") and app_id and app_id != identity.get("app_id"):
            raise ValueError("Requested app does not match the API key scope")
        if not identity.get("key_id") and user_id and identity.get("role") not in {"owner", "admin"} and user_id != identity.get("sub"):
            raise ValueError("Requested user does not match the authenticated user")
        return conversation_service.list_conversations(identity, org_id=identity["org_id"], app_id=app_id, user_id=user_id, limit=limit, admin=identity.get("role") in {"owner", "admin"})

    def classify_conversation(self, identity: dict, conversation_id: str):
        return conversation_service.classify_conversation(identity, conversation_id)

    def close_conversation(self, identity: dict, conversation_id: str, *, reason: str | None = None):
        return conversation_service.close_conversation(identity, conversation_id, reason=reason)

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
                memory_scope=payload.memory_scope,
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

    def record_feedback(self, payload: FeedbackRequest):
        scope = Scope(**payload.scope.model_dump())
        return memory_service.record_feedback(scope, payload.summary, payload.helpful, payload.metadata)

    def recall(self, payload: RecallRequest):
        scope = Scope(**payload.scope.model_dump())
        return memory_service.recall(scope, payload.query, payload.top_k, payload.include_layers)

    def search_graph(self, payload: ScopeRequest):
        scope = Scope(**payload.scope.model_dump())
        return memory_service.get_graph(scope, memory_scope=payload.memory_scope)

    def reflect_session(self, payload: ScopeRequest):
        scope = Scope(**payload.scope.model_dump())
        return memory_service.reflect(scope, memory_scope=payload.memory_scope)

    def reflect_conversation(self, identity: dict, conversation_id: str):
        return conversation_service.reflect_conversation(identity, conversation_id)

    def explain_answer(self, identity: dict, conversation_id: str):
        return conversation_service.explain_answer(identity, conversation_id)

    def list_memory_candidates(self, identity: dict, *, app_id: str | None = None, status_filter: str | None = None, limit: int = 100):
        return conversation_service.list_memory_candidates(identity, org_id=identity["org_id"], app_id=app_id, status_filter=status_filter, limit=limit)

    def approve_memory_candidate(self, identity: dict, candidate_id: str, payload: ReviewMemoryCandidateRequest):
        return conversation_service.approve_memory_candidate(identity, candidate_id, reason=payload.reason)

    def reject_memory_candidate(self, identity: dict, candidate_id: str, payload: ReviewMemoryCandidateRequest):
        return conversation_service.reject_memory_candidate(identity, candidate_id, reason=payload.reason)

    def merge_entities(self, identity: dict, payload: MergeEntitiesRequest):
        return conversation_service.merge_entities(
            identity,
            org_id=identity["org_id"],
            app_id=payload.app_id,
            canonical_label=payload.canonical_label,
            alias_label=payload.alias_label,
        )

    def rebuild_graph(self, identity: dict, conversation_id: str):
        return conversation_service.append_graph_update(identity, conversation_id)


mcp_service = MCPService()
