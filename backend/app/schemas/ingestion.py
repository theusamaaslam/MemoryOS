from typing import Any

from pydantic import BaseModel, Field

from app.schemas.memory import ScopeModel


class DocumentChunk(BaseModel):
    content: str
    source_uri: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionRequest(BaseModel):
    scope: ScopeModel
    source_type: str
    source_name: str
    chunks: list[DocumentChunk]
    tags: list[str] = Field(default_factory=list)


class IngestionResponse(BaseModel):
    job_id: str
    chunks_received: int
    status: str
