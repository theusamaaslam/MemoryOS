import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import require_auth
from app.models.domain import InteractionEvent, MemoryRecord, MemoryScope, Scope
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
    ScopeModel,
    ScopeRequest,
    SessionListResponse,
    TimelineResponse,
)
from app.services.document_ingestion import DocumentParsingError, UnsupportedDocumentError, document_ingestion_service
from app.services.jobs import job_service
from app.services.memory import memory_service


router = APIRouter(prefix="/memory", tags=["memory"], dependencies=[Depends(require_auth)])


def _decode_json_field(raw_value: str, *, field_name: str, default: list | dict) -> list | dict:
    if not raw_value.strip():
        return default
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be valid JSON.") from exc
    if not isinstance(parsed, type(default)):
        expected = "array" if isinstance(default, list) else "object"
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON {expected}.")
    return parsed


def _merge_chunk_metadata(chunks: list[dict], metadata: dict) -> list[dict]:
    if not metadata:
        return chunks
    return [
        {
            **chunk,
            "metadata": metadata | dict(chunk.get("metadata", {})),
        }
        for chunk in chunks
    ]


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
            memory_scope=payload.memory_scope,
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
    return ReflectionJobResponse(**memory_service.reflect(scope, memory_scope=payload.memory_scope))


@router.post("/reflect/async", response_model=ReflectionJobResponse)
def reflect_async(payload: ReflectionEnqueueRequest) -> ReflectionJobResponse:
    scope = Scope(**payload.scope.model_dump())
    return ReflectionJobResponse(**job_service.enqueue_reflection(scope, payload.reason, memory_scope=payload.memory_scope))


@router.get("/jobs/{job_id}", response_model=ReflectionJobResponse)
def get_job(job_id: str) -> ReflectionJobResponse:
    job = job_service.get_job(job_id)
    if job is None:
        return ReflectionJobResponse(job_id=job_id, status="missing", summary="Job not found")
    return ReflectionJobResponse(**job)


@router.post("/ingest", response_model=IngestionResponse)
def ingest(payload: IngestionRequest) -> IngestionResponse:
    scope = Scope(**payload.scope.model_dump())
    if payload.content and payload.content.strip():
        try:
            document = document_ingestion_service.build_manual_document(payload.source_name, payload.content)
            chunks, strategy = document_ingestion_service.chunk_document(document)
        except DocumentParsingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        chunks = _merge_chunk_metadata(chunks, payload.metadata)
        return IngestionResponse(
            **memory_service.ingest_documents(
                scope,
                document.source_name,
                chunks,
                tags=payload.tags,
                source_type=document.source_type,
                source_uri=payload.source_uri or document.source_uri,
                source_metadata=document.metadata | payload.metadata,
                parser=document.parser_name,
                chunking_strategy=str(strategy["chunking_strategy"]),
                memory_scope=MemoryScope.APP,
            )
        )

    if payload.chunks:
        chunks = _merge_chunk_metadata([chunk.model_dump() for chunk in payload.chunks], payload.metadata)
        return IngestionResponse(
            **memory_service.ingest_documents(
                scope,
                payload.source_name,
                chunks,
                tags=payload.tags,
                source_type=payload.source_type,
                source_uri=payload.source_uri,
                source_metadata=payload.metadata,
                memory_scope=MemoryScope.APP,
            )
        )

    raise HTTPException(status_code=400, detail="Provide either document content or document chunks for ingestion.")


@router.post("/ingest/upload", response_model=IngestionResponse)
async def ingest_upload(
    org_id: str = Form(...),
    app_id: str = Form(...),
    user_id: str = Form(...),
    session_id: str = Form(...),
    source_name: str = Form(""),
    tags_json: str = Form("[]"),
    metadata_json: str = Form("{}"),
    file: UploadFile = File(...),
) -> IngestionResponse:
    scope_model = ScopeModel(org_id=org_id, app_id=app_id, user_id=user_id, session_id=session_id)
    scope = Scope(**scope_model.model_dump())
    tags = _decode_json_field(tags_json, field_name="tags_json", default=[])
    metadata = _decode_json_field(metadata_json, field_name="metadata_json", default={})

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        document = document_ingestion_service.parse_upload(file.filename, file.content_type, contents)
    except UnsupportedDocumentError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except DocumentParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if source_name.strip():
        document.source_name = source_name.strip()
        document.title = source_name.strip()

    try:
        chunks, strategy = document_ingestion_service.chunk_document(document)
    except DocumentParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    chunks = _merge_chunk_metadata(chunks, metadata)
    return IngestionResponse(
        **memory_service.ingest_documents(
            scope,
            document.source_name,
            chunks,
            tags=tags,
            source_type=document.source_type,
            source_uri=document.source_uri,
            source_metadata=document.metadata | metadata,
            parser=document.parser_name,
            chunking_strategy=str(strategy["chunking_strategy"]),
            memory_scope=MemoryScope.APP,
        )
    )


@router.post("/graph", response_model=GraphResponse)
def graph(payload: ScopeRequest) -> GraphResponse:
    scope = Scope(**payload.scope.model_dump())
    return GraphResponse(**memory_service.get_graph(scope, memory_scope=payload.memory_scope))


@router.post("/timeline", response_model=TimelineResponse)
def timeline(payload: ScopeRequest) -> TimelineResponse:
    scope = Scope(**payload.scope.model_dump())
    return memory_service.timeline(scope, graph_memory_scope=payload.memory_scope)


@router.post("/sessions", response_model=SessionListResponse)
def sessions(payload: ScopeRequest) -> SessionListResponse:
    scope = Scope(**payload.scope.model_dump())
    return SessionListResponse(items=memory_service.list_sessions(scope))
