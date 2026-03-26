from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.domain import MemoryLayer, MemoryScope, Outcome
from app.schemas.conversation import MergeEntitiesRequest, ReviewMemoryCandidateRequest, SendMessageRequest, StartConversationRequest
from app.schemas.memory import EventRequest, FeedbackRequest, RecallRequest, RememberRequest, ScopeModel, ScopeRequest
from app.services.auth import auth_service
from app.services.mcp import mcp_service

# Expose both modern Streamable HTTP and legacy SSE transports so different
# MCP clients can connect without needing a code change on their side.
mcp = FastMCP("MemoryOS MCP Server")


class RememberToolRequest(BaseModel):
    scope: ScopeModel | None = None
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = "interaction"
    layer: MemoryLayer = MemoryLayer.SESSION
    memory_scope: MemoryScope = MemoryScope.CONVERSATION


class EventToolRequest(BaseModel):
    scope: ScopeModel | None = None
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    outcome: Outcome = Outcome.UNKNOWN


class FeedbackToolRequest(BaseModel):
    scope: ScopeModel | None = None
    event_id: str | None = None
    summary: str
    helpful: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallToolRequest(BaseModel):
    scope: ScopeModel | None = None
    query: str
    top_k: int = 5
    include_layers: list[MemoryLayer] | None = None


class ScopeToolRequest(BaseModel):
    scope: ScopeModel | None = None
    memory_scope: MemoryScope = MemoryScope.APP


class StartConversationToolRequest(StartConversationRequest):
    agent_id: str


class SendConversationMessageToolRequest(SendMessageRequest):
    conversation_id: str


class ConversationToolRequest(BaseModel):
    conversation_id: str


class CloseConversationToolRequest(BaseModel):
    conversation_id: str
    reason: str | None = None


class ListConversationsToolRequest(BaseModel):
    app_id: str | None = None
    user_id: str | None = None
    limit: int = 50


class ListMemoryCandidatesToolRequest(BaseModel):
    app_id: str | None = None
    status: str | None = None
    limit: int = 100


class MemoryCandidateToolRequest(ReviewMemoryCandidateRequest):
    candidate_id: str


def _headers() -> dict[str, str]:
    return {str(key).lower(): value for key, value in (get_http_headers() or {}).items()}


def _resolve_identity() -> dict:
    headers = _headers()
    raw_api_key = headers.get("x-api-key")
    if raw_api_key:
        identity = auth_service.validate_api_key(raw_api_key)
        if identity:
            return identity
        raise ValueError("Invalid API key")

    authorization = headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise ValueError("Missing bearer token or X-API-Key header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # noqa: BLE001
        raise ValueError("Invalid bearer token") from exc
    if payload.get("type") not in (None, "access"):
        raise ValueError("Invalid token type")
    return payload


def _resolve_scope(scope: ScopeModel | None) -> ScopeModel:
    identity = _resolve_identity()
    if scope is None:
        headers = _headers()
        resolved = {
            "org_id": headers.get("x-memoryos-org-id"),
            "app_id": headers.get("x-memoryos-app-id") or identity.get("app_id"),
            "user_id": headers.get("x-memoryos-user-id") or identity.get("sub") or identity.get("key_id"),
            "session_id": headers.get("x-memoryos-session-id"),
        }
        missing = [key for key, value in resolved.items() if not value]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(
                "Memory scope missing. Provide payload.scope or send "
                "X-MemoryOS-Org-Id, X-MemoryOS-App-Id, X-MemoryOS-User-Id, and "
                f"X-MemoryOS-Session-Id headers. Missing: {joined}."
            )
        scope = ScopeModel(**resolved)

    if str(scope.org_id) != str(identity.get("org_id")):
        raise ValueError("Requested org scope does not match the authenticated identity")
    if identity.get("key_id") and str(scope.app_id) != str(identity.get("app_id")):
        raise ValueError("Requested app scope does not match the API key scope")
    if not identity.get("key_id") and identity.get("role") not in {"owner", "admin"} and str(scope.user_id) != str(identity.get("sub")):
        raise ValueError("Requested user scope does not match the authenticated user")
    return scope


@mcp.tool()
def start_conversation(payload: StartConversationToolRequest) -> dict:
    """Open a new server-managed conversation before any send_message call and return the conversation_id for that agent thread."""
    identity = _resolve_identity()
    return mcp_service.start_conversation(identity, payload.agent_id, payload)


@mcp.tool()
def send_message(payload: SendConversationMessageToolRequest) -> dict:
    """Send one user turn into an existing conversation and get a grounded reply after query planning, hybrid retrieval, citations, and audit logging."""
    identity = _resolve_identity()
    return mcp_service.send_message(identity, payload.conversation_id, payload)


@mcp.tool()
def get_conversation(payload: ConversationToolRequest) -> dict:
    """Read the full stored conversation thread, including turns, messages, citations, label metadata, and current status."""
    identity = _resolve_identity()
    return mcp_service.get_conversation(identity, payload.conversation_id)


@mcp.tool()
def close_conversation(payload: CloseConversationToolRequest) -> dict:
    """Archive a conversation when the chat session is finished so it stops behaving like an active runtime thread and later sends are blocked."""
    identity = _resolve_identity()
    return mcp_service.close_conversation(identity, payload.conversation_id, reason=payload.reason)


@mcp.tool()
def list_conversations(payload: ListConversationsToolRequest) -> dict:
    """List recent conversations in scope so a client can discover resumable threads, choose a conversation_id, or inspect open versus archived sessions."""
    identity = _resolve_identity()
    return mcp_service.list_conversations(identity, app_id=payload.app_id, user_id=payload.user_id, limit=payload.limit)


@mcp.tool()
def classify_conversation(payload: ConversationToolRequest) -> dict:
    """Refresh the structured label for a conversation, including topic, type, risk, outcome, and memory impact score."""
    identity = _resolve_identity()
    return mcp_service.classify_conversation(identity, payload.conversation_id)


@mcp.tool()
def remember(payload: RememberToolRequest) -> dict:
    """Write an explicit memory record into the active scope for durable facts, preferences, failures, resolutions, or other retrievable knowledge."""
    record = mcp_service.remember(
        RememberRequest(
            scope=_resolve_scope(payload.scope),
            content=payload.content,
            tags=payload.tags,
            metadata=payload.metadata,
            source=payload.source,
            layer=payload.layer,
            memory_scope=payload.memory_scope,
        )
    )
    return {"memory_id": record.memory_id, "status": "stored"}


@mcp.tool()
def recall(payload: RecallToolRequest) -> dict:
    """Run hybrid retrieval without generating a chat answer and return evidence items plus retrieval trace metadata."""
    return mcp_service.recall(
        RecallRequest(
            scope=_resolve_scope(payload.scope),
            query=payload.query,
            top_k=payload.top_k,
            include_layers=payload.include_layers,
        )
    ).model_dump()


@mcp.tool()
def append_event(payload: EventToolRequest) -> dict:
    """Append a raw event to the chronological event stream before later reflection promotes it into memory or graph updates."""
    event = mcp_service.append_event(
        EventRequest(
            scope=_resolve_scope(payload.scope),
            role=payload.role,
            content=payload.content,
            metadata=payload.metadata,
            outcome=payload.outcome,
        )
    )
    return {"event_id": event.event_id, "status": "stored"}


@mcp.tool()
def record_feedback(payload: FeedbackToolRequest) -> dict:
    """Store explicit helpful or unhelpful feedback so future retrieval, review, and reflection can learn from what worked or failed."""
    record = mcp_service.record_feedback(
        FeedbackRequest(
            scope=_resolve_scope(payload.scope),
            event_id=payload.event_id,
            summary=payload.summary,
            helpful=payload.helpful,
            metadata=payload.metadata,
        )
    )
    return {"memory_id": record.memory_id, "status": "stored"}


@mcp.tool()
def search_graph(payload: ScopeToolRequest) -> dict:
    """Read the grounded knowledge graph for the requested memory scope and return evidence-linked nodes and relations."""
    return mcp_service.search_graph(ScopeRequest(scope=_resolve_scope(payload.scope), memory_scope=payload.memory_scope))


@mcp.tool()
def reflect_session(payload: ScopeToolRequest) -> dict:
    """Trigger reflection for the current scope so recent memories and events can be promoted into longer-term memory and graph updates."""
    return mcp_service.reflect_session(ScopeRequest(scope=_resolve_scope(payload.scope), memory_scope=payload.memory_scope))


@mcp.tool()
def reflect_conversation(payload: ConversationToolRequest) -> dict:
    """Reflect one conversation into reviewable memory candidates and incremental grounded graph updates without touching unrelated graph state."""
    identity = _resolve_identity()
    return mcp_service.reflect_conversation(identity, payload.conversation_id)


@mcp.tool()
def explain_answer(payload: ConversationToolRequest) -> dict:
    """Explain why the assistant answered as it did by returning retrieval trace details, selected evidence, and answer audit metadata."""
    identity = _resolve_identity()
    return mcp_service.explain_answer(identity, payload.conversation_id)


@mcp.tool()
def list_memory_candidates(payload: ListMemoryCandidatesToolRequest) -> dict:
    """List reflection-created memory candidates that are waiting in the reviewer inbox before becoming durable shared memory."""
    identity = _resolve_identity()
    return mcp_service.list_memory_candidates(identity, app_id=payload.app_id, status_filter=payload.status, limit=payload.limit)


@mcp.tool()
def approve_memory_candidate(payload: MemoryCandidateToolRequest) -> dict:
    """Approve a reflected memory candidate so it is promoted into durable memory and can influence future retrieval."""
    identity = _resolve_identity()
    return mcp_service.approve_memory_candidate(identity, payload.candidate_id, payload)


@mcp.tool()
def reject_memory_candidate(payload: MemoryCandidateToolRequest) -> dict:
    """Reject a reflected memory candidate so noisy, duplicate, or incorrect reflection output does not pollute long-term memory."""
    identity = _resolve_identity()
    return mcp_service.reject_memory_candidate(identity, payload.candidate_id, payload)


@mcp.tool()
def merge_entities(payload: MergeEntitiesRequest) -> dict:
    """Merge duplicate or alias graph labels into one canonical entity and collapse duplicate or self-loop relations afterwards."""
    identity = _resolve_identity()
    return mcp_service.merge_entities(identity, payload)


@mcp.tool()
def rebuild_graph(payload: ConversationToolRequest) -> dict:
    """Apply the latest incremental graph merge for one conversation from grounded evidence; despite the name, this is not a full tenant graph reset."""
    identity = _resolve_identity()
    return mcp_service.rebuild_graph(identity, payload.conversation_id)


def _build_http_app():
    http_factory = getattr(mcp, "http_app", None)
    if callable(http_factory):
        return http_factory(path="/")

    streamable_http_factory = getattr(mcp, "streamable_http_app", None)
    if callable(streamable_http_factory):
        return streamable_http_factory(path="/")

    raise RuntimeError("FastMCP HTTP transport is unavailable; upgrade fastmcp to 2.3.2+.")


def _build_sse_app():
    sse_factory = getattr(mcp, "sse_app", None)
    if callable(sse_factory):
        return sse_factory(path="/", message_path="/messages/")

    http_factory = getattr(mcp, "http_app", None)
    if callable(http_factory):
        return http_factory(path="/", transport="sse")

    raise RuntimeError("FastMCP SSE transport is unavailable in the installed fastmcp version.")


mcp_http_app = _build_http_app()
mcp_sse_app = _build_sse_app()
