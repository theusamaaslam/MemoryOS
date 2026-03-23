from fastapi import APIRouter, Depends

from app.api.deps import require_auth
from app.models.domain import InteractionEvent, MemoryRecord, Scope
from app.schemas.ingestion import IngestionRequest, IngestionResponse
from app.schemas.memory import (
    EventRequest,
    FeedbackRequest,
    GraphResponse,
    RecallRequest,
    RecallResponse,
    ReflectionEnqueueRequest,
    ReflectionJobResponse,
    RememberRequest,
    ScopeRequest,
    TimelineResponse,
)
from app.services.jobs import job_service
from app.services.memory import memory_service


router = APIRouter(prefix="/memory", tags=["memory"], dependencies=[Depends(require_auth)])


@router.post("/remember")
def remember(payload: RememberRequest) -> dict:
    scope = Scope(**payload.scope.model_dump())
    record = memory_service.remember(
        MemoryRecord(
            layer=payload.layer,
            scope=scope,
            content=payload.content,
            metadata=payload.metadata,
            tags=payload.tags,
            source=payload.source,
        )
    )
    return {"memory_id": record.memory_id, "status": "stored", "layer": record.layer}


@router.post("/events")
def append_event(payload: EventRequest) -> dict:
    scope = Scope(**payload.scope.model_dump())
    event = memory_service.append_event(
        InteractionEvent(
            scope=scope,
            role=payload.role,
            content=payload.content,
            metadata=payload.metadata,
            outcome=payload.outcome,
        )
    )
    return {"event_id": event.event_id, "status": "stored"}


@router.post("/feedback")
def record_feedback(payload: FeedbackRequest) -> dict:
    scope = Scope(**payload.scope.model_dump())
    record = memory_service.record_feedback(scope, payload.summary, payload.helpful, payload.metadata)
    return {"memory_id": record.memory_id, "status": "stored", "layer": record.layer}


@router.post("/recall", response_model=RecallResponse)
def recall(payload: RecallRequest) -> RecallResponse:
    scope = Scope(**payload.scope.model_dump())
    return memory_service.recall(scope, payload.query, payload.top_k, payload.include_layers)


@router.post("/reflect", response_model=ReflectionJobResponse)
def reflect(payload: ScopeRequest) -> ReflectionJobResponse:
    scope = Scope(**payload.scope.model_dump())
    return ReflectionJobResponse(**memory_service.reflect(scope))


@router.post("/reflect/async", response_model=ReflectionJobResponse)
def reflect_async(payload: ReflectionEnqueueRequest) -> ReflectionJobResponse:
    scope = Scope(**payload.scope.model_dump())
    return ReflectionJobResponse(**job_service.enqueue_reflection(scope, payload.reason))


@router.get("/jobs/{job_id}", response_model=ReflectionJobResponse)
def get_job(job_id: str) -> ReflectionJobResponse:
    job = job_service.get_job(job_id)
    if job is None:
        return ReflectionJobResponse(job_id=job_id, status="missing", summary="Job not found")
    return ReflectionJobResponse(**job)


@router.post("/ingest", response_model=IngestionResponse)
def ingest(payload: IngestionRequest) -> IngestionResponse:
    scope = Scope(**payload.scope.model_dump())
    chunks = [chunk.model_dump() for chunk in payload.chunks]
    return IngestionResponse(**memory_service.ingest_documents(scope, payload.source_name, chunks))


@router.post("/graph", response_model=GraphResponse)
def graph(payload: ScopeRequest) -> GraphResponse:
    scope = Scope(**payload.scope.model_dump())
    return GraphResponse(**memory_service.get_graph(scope))


@router.post("/timeline", response_model=TimelineResponse)
def timeline(payload: ScopeRequest) -> TimelineResponse:
    scope = Scope(**payload.scope.model_dump())
    return memory_service.timeline(scope)
