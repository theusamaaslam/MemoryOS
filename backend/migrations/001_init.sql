CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    org_id VARCHAR(128) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    hashed_key VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    memory_id VARCHAR(64) PRIMARY KEY,
    layer VARCHAR(32) NOT NULL,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    content TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    source VARCHAR(64) NOT NULL DEFAULT 'interaction',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    role VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    outcome VARCHAR(32) NOT NULL DEFAULT 'unknown',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    label VARCHAR(255) NOT NULL,
    node_type VARCHAR(64) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    evidence_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    from_node VARCHAR(64) NOT NULL,
    to_node VARCHAR(64) NOT NULL,
    relation VARCHAR(64) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    evidence_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    job_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories (org_id, app_id, user_id, session_id, layer);
CREATE INDEX IF NOT EXISTS idx_events_scope ON events (org_id, app_id, user_id, session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_scope ON graph_nodes (org_id, app_id, user_id, session_id, label);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, job_type, created_at);
