from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_auth
from app.schemas.memory import EventRequest, RecallRequest, RememberRequest, ScopeRequest
from app.services.mcp import mcp_service
from app.services.memory import memory_service
from app.models.domain import Scope


router = APIRouter(prefix="/mcp", tags=["mcp"], dependencies=[Depends(require_auth)])


@router.get("/tools")
def tools() -> dict:
    return {"tools": mcp_service.describe_tools()}


@router.post("/invoke/{tool_name}")
def invoke(tool_name: str, payload: dict) -> dict:
    if tool_name == "remember":
        record = mcp_service.remember(RememberRequest(**payload))
        return {"memory_id": record.memory_id, "status": "stored"}
    if tool_name == "append_event":
        event = mcp_service.append_event(EventRequest(**payload))
        return {"event_id": event.event_id, "status": "stored"}
    if tool_name == "recall":
        return mcp_service.recall(RecallRequest(**payload)).model_dump()
    if tool_name == "search_graph":
        request = ScopeRequest(**payload)
        return memory_service.get_graph(Scope(**request.scope.model_dump()))
    if tool_name == "reflect_session":
        request = ScopeRequest(**payload)
        return memory_service.reflect(Scope(**request.scope.model_dump()))
    raise HTTPException(status_code=404, detail="Unknown MCP tool")
