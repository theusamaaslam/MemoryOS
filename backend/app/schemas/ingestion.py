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
    source_uri: str | None = None
    content: str | None = None
    chunks: list[DocumentChunk] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionResponse(BaseModel):
    job_id: str
    chunks_received: int
    status: str
    parser: str | None = None
    source_type: str | None = None
    chunking_strategy: str | None = None
    source_id: str | None = None
    source_status: str | None = None
    skipped: bool = False
    chunks_created: int = 0
    chunks_updated: int = 0
    chunks_removed: int = 0
