CREATE TABLE IF NOT EXISTS document_sources (
    source_id VARCHAR(128) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    memory_scope VARCHAR(32) NOT NULL DEFAULT 'app',
    scope_ref VARCHAR(128) NOT NULL DEFAULT '',
    conversation_id VARCHAR(128) NOT NULL DEFAULT '',
    source_name VARCHAR(255) NOT NULL,
    source_uri VARCHAR(512) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    parser_name VARCHAR(128) NOT NULL DEFAULT '',
    chunking_strategy VARCHAR(64) NOT NULL DEFAULT '',
    content_hash VARCHAR(128) NOT NULL,
    block_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'indexed_pending_reflection',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    last_ingested_at TIMESTAMPTZ NULL,
    last_reflected_at TIMESTAMPTZ NULL
);

ALTER TABLE memories ADD COLUMN IF NOT EXISTS document_source_id VARCHAR(128);
ALTER TABLE memories ADD COLUMN IF NOT EXISTS chunk_key VARCHAR(128);

CREATE UNIQUE INDEX IF NOT EXISTS idx_document_sources_identity
    ON document_sources (org_id, app_id, memory_scope, scope_ref, source_uri);
CREATE INDEX IF NOT EXISTS idx_document_sources_scope
    ON document_sources (org_id, app_id, memory_scope, scope_ref, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_document_sources_status
    ON document_sources (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_source_chunk
    ON memories (org_id, app_id, document_source_id, chunk_key);
