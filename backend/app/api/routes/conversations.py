from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import ensure_org_access, require_admin, require_auth, resolve_app_id, resolve_end_user_id
from app.schemas.conversation import (
    ClassifyConversationRequest,
    CloseConversationRequest,
    ConversationListResponse,
    ConversationResponse,
    ConversationTraceResponse,
    ExplainAnswerResponse,
    MemoryCandidateListResponse,
    MemoryCandidateResponse,
    MergeEntitiesRequest,
    RebuildGraphRequest,
    ReviewMemoryCandidateRequest,
    SendMessageRequest,
    SendMessageResponse,
    StartConversationRequest,
)
from app.services.conversations import conversation_service


router = APIRouter(tags=["conversations"], dependencies=[Depends(require_auth)])


@router.post("/agents/{agent_id}/conversations", response_model=ConversationResponse)
def start_conversation(agent_id: str, payload: StartConversationRequest, identity: dict = Depends(require_auth)) -> ConversationResponse:
    app_id = resolve_app_id(identity, payload.app_id)
    user_id = resolve_end_user_id(identity, payload.user_id)
    return ConversationResponse(
        **conversation_service.start_conversation(
            org_id=identity["org_id"],
            app_id=app_id,
            user_id=user_id,
            agent_id=agent_id,
            title=payload.title,
            description=payload.description,
            metadata=payload.metadata,
        )
    )


@router.post("/conversations/{conversation_id}/messages", response_model=SendMessageResponse)
def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    identity: dict = Depends(require_auth),
) -> SendMessageResponse:
    return SendMessageResponse(**conversation_service.send_message(identity, conversation_id, payload.content, top_k=payload.top_k, metadata=payload.metadata))


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: str, identity: dict = Depends(require_auth)) -> ConversationResponse:
    return ConversationResponse(**conversation_service.get_conversation(identity, conversation_id))


@router.post("/conversations/{conversation_id}/close", response_model=ConversationResponse)
def close_conversation(
    conversation_id: str,
    payload: CloseConversationRequest,
    identity: dict = Depends(require_auth),
) -> ConversationResponse:
    return ConversationResponse(**conversation_service.close_conversation(identity, conversation_id, reason=payload.reason))


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    app_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    identity: dict = Depends(require_auth),
) -> ConversationListResponse:
    return ConversationListResponse(
        **conversation_service.list_conversations(
            identity,
            org_id=identity["org_id"],
            app_id=app_id,
            limit=limit,
            admin=False,
        )
    )


@router.post("/conversations/classify", response_model=dict)
def classify_conversation(payload: ClassifyConversationRequest, identity: dict = Depends(require_auth)) -> dict:
    return conversation_service.classify_conversation(identity, payload.conversation_id)


@router.get("/conversations/{conversation_id}/explain", response_model=ExplainAnswerResponse)
def explain_answer(conversation_id: str, identity: dict = Depends(require_auth)) -> ExplainAnswerResponse:
    return ExplainAnswerResponse(**conversation_service.explain_answer(identity, conversation_id))


admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@admin_router.get("/tenants/{org_id}/conversations", response_model=ConversationListResponse)
def list_tenant_conversations(
    org_id: str,
    app_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    identity: dict = Depends(require_admin),
) -> ConversationListResponse:
    ensure_org_access(identity, org_id)
    return ConversationListResponse(**conversation_service.list_conversations(identity, org_id=org_id, app_id=app_id, user_id=user_id, limit=limit, admin=True))


@admin_router.get("/conversations/{conversation_id}/trace", response_model=ConversationTraceResponse)
def get_conversation_trace(conversation_id: str, identity: dict = Depends(require_admin)) -> ConversationTraceResponse:
    return ConversationTraceResponse(**conversation_service.get_conversation_trace(identity, conversation_id))


@admin_router.get("/memory-candidates", response_model=MemoryCandidateListResponse)
def list_memory_candidates(
    org_id: str | None = Query(default=None),
    app_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    identity: dict = Depends(require_admin),
) -> MemoryCandidateListResponse:
    return MemoryCandidateListResponse(**conversation_service.list_memory_candidates(identity, org_id=org_id, app_id=app_id, status_filter=status_filter, limit=limit))


@admin_router.post("/memory-candidates/{candidate_id}/approve", response_model=MemoryCandidateResponse)
def approve_memory_candidate(
    candidate_id: str,
    payload: ReviewMemoryCandidateRequest,
    identity: dict = Depends(require_admin),
) -> MemoryCandidateResponse:
    result = conversation_service.approve_memory_candidate(identity, candidate_id, reason=payload.reason)
    return MemoryCandidateResponse(**result["items"][0])


@admin_router.post("/memory-candidates/{candidate_id}/reject", response_model=MemoryCandidateResponse)
def reject_memory_candidate(
    candidate_id: str,
    payload: ReviewMemoryCandidateRequest,
    identity: dict = Depends(require_admin),
) -> MemoryCandidateResponse:
    result = conversation_service.reject_memory_candidate(identity, candidate_id, reason=payload.reason)
    return MemoryCandidateResponse(**result["items"][0])


@admin_router.post("/graph/merge-entities", response_model=dict)
def merge_entities(payload: MergeEntitiesRequest, identity: dict = Depends(require_admin)) -> dict:
    return conversation_service.merge_entities(
        identity,
        org_id=identity["org_id"],
        app_id=payload.app_id,
        canonical_label=payload.canonical_label,
        alias_label=payload.alias_label,
    )


@admin_router.post("/graph/append", response_model=dict)
def append_graph(payload: RebuildGraphRequest, identity: dict = Depends(require_admin)) -> dict:
    return conversation_service.append_graph_update(identity, payload.conversation_id)


@admin_router.post("/graph/rebuild", response_model=dict)
def rebuild_graph(payload: RebuildGraphRequest, identity: dict = Depends(require_admin)) -> dict:
    return conversation_service.rebuild_graph(identity, payload.conversation_id)
