from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_auth
from app.schemas.conversation import MergeEntitiesRequest, ReviewMemoryCandidateRequest, SendMessageRequest, StartConversationRequest
from app.schemas.memory import EventRequest, FeedbackRequest, RecallRequest, RememberRequest, ScopeRequest
from app.services.mcp import mcp_service


router = APIRouter(prefix="/mcp", tags=["mcp"], dependencies=[Depends(require_auth)])


@router.get("/tools")
def tools() -> dict:
    return {"tools": mcp_service.describe_tools()}


@router.post("/invoke/{tool_name}")
def invoke(tool_name: str, payload: dict, identity: dict = Depends(require_auth)) -> dict:
    if tool_name == "start_conversation":
        agent_id = str(payload.get("agent_id") or "").strip()
        if not agent_id:
            raise HTTPException(status_code=400, detail="agent_id is required")
        return mcp_service.start_conversation(identity, agent_id, StartConversationRequest(**payload))
    if tool_name == "send_message":
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        return mcp_service.send_message(identity, conversation_id, SendMessageRequest(**payload))
    if tool_name == "get_conversation":
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        return mcp_service.get_conversation(identity, conversation_id)
    if tool_name == "close_conversation":
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        reason = str(payload.get("reason") or "").strip() or None
        return mcp_service.close_conversation(identity, conversation_id, reason=reason)
    if tool_name == "list_conversations":
        return mcp_service.list_conversations(
            identity,
            app_id=payload.get("app_id"),
            user_id=payload.get("user_id"),
            limit=int(payload.get("limit", 50) or 50),
        )
    if tool_name == "classify_conversation":
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        return mcp_service.classify_conversation(identity, conversation_id)
    if tool_name == "remember":
        record = mcp_service.remember(RememberRequest(**payload))
        return {"memory_id": record.memory_id, "status": "stored"}
    if tool_name == "append_event":
        event = mcp_service.append_event(EventRequest(**payload))
        return {"event_id": event.event_id, "status": "stored"}
    if tool_name == "record_feedback":
        record = mcp_service.record_feedback(FeedbackRequest(**payload))
        return {"memory_id": record.memory_id, "status": "stored"}
    if tool_name == "recall":
        return mcp_service.recall(RecallRequest(**payload)).model_dump()
    if tool_name == "search_graph":
        request = ScopeRequest(**payload)
        return mcp_service.search_graph(request)
    if tool_name == "reflect_session":
        request = ScopeRequest(**payload)
        return mcp_service.reflect_session(request)
    if tool_name == "reflect_conversation":
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        return mcp_service.reflect_conversation(identity, conversation_id)
    if tool_name == "explain_answer":
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        return mcp_service.explain_answer(identity, conversation_id)
    if tool_name == "list_memory_candidates":
        return mcp_service.list_memory_candidates(
            identity,
            app_id=payload.get("app_id"),
            status_filter=payload.get("status"),
            limit=int(payload.get("limit", 100) or 100),
        )
    if tool_name == "approve_memory_candidate":
        candidate_id = str(payload.get("candidate_id") or "").strip()
        if not candidate_id:
            raise HTTPException(status_code=400, detail="candidate_id is required")
        return mcp_service.approve_memory_candidate(identity, candidate_id, ReviewMemoryCandidateRequest(**payload))
    if tool_name == "reject_memory_candidate":
        candidate_id = str(payload.get("candidate_id") or "").strip()
        if not candidate_id:
            raise HTTPException(status_code=400, detail="candidate_id is required")
        return mcp_service.reject_memory_candidate(identity, candidate_id, ReviewMemoryCandidateRequest(**payload))
    if tool_name == "merge_entities":
        return mcp_service.merge_entities(identity, MergeEntitiesRequest(**payload))
    if tool_name == "rebuild_graph":
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        return mcp_service.rebuild_graph(identity, conversation_id)
    raise HTTPException(status_code=404, detail="Unknown MCP tool")
