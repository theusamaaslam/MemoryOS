ALTER TABLE memories
ADD COLUMN IF NOT EXISTS memory_scope VARCHAR(32) NOT NULL DEFAULT 'conversation';

ALTER TABLE memories
ADD COLUMN IF NOT EXISTS scope_ref VARCHAR(128) NOT NULL DEFAULT '';

ALTER TABLE memories
ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(128) NOT NULL DEFAULT '';

ALTER TABLE memories
ADD COLUMN IF NOT EXISTS promotion_status VARCHAR(32) NOT NULL DEFAULT 'direct';

UPDATE memories
SET conversation_id = session_id
WHERE conversation_id = '';

UPDATE memories
SET scope_ref = CASE
    WHEN memory_scope = 'user' THEN user_id
    WHEN memory_scope = 'app' THEN app_id
    ELSE session_id
END
WHERE scope_ref = '';

ALTER TABLE events
ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(128) NOT NULL DEFAULT '';

UPDATE events
SET conversation_id = session_id
WHERE conversation_id = '';

ALTER TABLE graph_nodes
ADD COLUMN IF NOT EXISTS graph_scope VARCHAR(32) NOT NULL DEFAULT 'conversation';

ALTER TABLE graph_nodes
ADD COLUMN IF NOT EXISTS scope_ref VARCHAR(128) NOT NULL DEFAULT '';

ALTER TABLE graph_nodes
ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(128) NOT NULL DEFAULT '';

UPDATE graph_nodes
SET conversation_id = session_id
WHERE conversation_id = '';

UPDATE graph_nodes
SET scope_ref = CASE
    WHEN graph_scope = 'user' THEN user_id
    WHEN graph_scope = 'app' THEN app_id
    ELSE session_id
END
WHERE scope_ref = '';

ALTER TABLE graph_edges
ADD COLUMN IF NOT EXISTS graph_scope VARCHAR(32) NOT NULL DEFAULT 'conversation';

ALTER TABLE graph_edges
ADD COLUMN IF NOT EXISTS scope_ref VARCHAR(128) NOT NULL DEFAULT '';

ALTER TABLE graph_edges
ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(128) NOT NULL DEFAULT '';

UPDATE graph_edges
SET conversation_id = session_id
WHERE conversation_id = '';

UPDATE graph_edges
SET scope_ref = CASE
    WHEN graph_scope = 'user' THEN user_id
    WHEN graph_scope = 'app' THEN app_id
    ELSE session_id
END
WHERE scope_ref = '';

CREATE TABLE IF NOT EXISTS agents (
    agent_id VARCHAR(128) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id VARCHAR(128) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    agent_id VARCHAR(128) NOT NULL REFERENCES agents(agent_id),
    user_id VARCHAR(128) NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    summary TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    last_message_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_labels (
    conversation_id VARCHAR(128) PRIMARY KEY REFERENCES conversations(conversation_id),
    conversation_type VARCHAR(64) NOT NULL DEFAULT 'general',
    topic VARCHAR(128) NOT NULL DEFAULT 'general',
    outcome VARCHAR(64) NOT NULL DEFAULT 'open',
    escalation_state VARCHAR(64) NOT NULL DEFAULT 'none',
    satisfaction VARCHAR(64) NOT NULL DEFAULT 'unknown',
    hallucination_suspected BOOLEAN NOT NULL DEFAULT FALSE,
    risk_level VARCHAR(64) NOT NULL DEFAULT 'normal',
    memory_impact_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id VARCHAR(128) PRIMARY KEY,
    conversation_id VARCHAR(128) NOT NULL REFERENCES conversations(conversation_id),
    turn_index INTEGER NOT NULL,
    user_message_id VARCHAR(128) NULL,
    assistant_message_id VARCHAR(128) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id VARCHAR(128) PRIMARY KEY,
    conversation_id VARCHAR(128) NOT NULL REFERENCES conversations(conversation_id),
    turn_id VARCHAR(128) NULL REFERENCES conversation_turns(turn_id),
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    citations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_traces (
    trace_id VARCHAR(128) PRIMARY KEY,
    conversation_id VARCHAR(128) NOT NULL REFERENCES conversations(conversation_id),
    message_id VARCHAR(128) NOT NULL REFERENCES conversation_messages(message_id),
    query TEXT NOT NULL,
    items_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    trace_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS answer_audits (
    audit_id VARCHAR(128) PRIMARY KEY,
    conversation_id VARCHAR(128) NOT NULL REFERENCES conversations(conversation_id),
    turn_id VARCHAR(128) NOT NULL REFERENCES conversation_turns(turn_id),
    user_message_id VARCHAR(128) NOT NULL REFERENCES conversation_messages(message_id),
    assistant_message_id VARCHAR(128) NOT NULL REFERENCES conversation_messages(message_id),
    provider VARCHAR(64) NOT NULL DEFAULT 'heuristic',
    model_name VARCHAR(128) NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    supported BOOLEAN NOT NULL DEFAULT FALSE,
    abstained BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_invocations (
    invocation_id VARCHAR(128) PRIMARY KEY,
    conversation_id VARCHAR(128) NOT NULL REFERENCES conversations(conversation_id),
    turn_id VARCHAR(128) NULL REFERENCES conversation_turns(turn_id),
    tool_name VARCHAR(128) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_candidates (
    candidate_id VARCHAR(128) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    conversation_id VARCHAR(128) NOT NULL,
    memory_scope VARCHAR(32) NOT NULL DEFAULT 'conversation',
    layer VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    source_memory_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    alias_id VARCHAR(128) PRIMARY KEY,
    org_id VARCHAR(128) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    canonical_label VARCHAR(255) NOT NULL,
    alias_label VARCHAR(255) NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_scope_v2 ON memories (org_id, app_id, user_id, memory_scope, scope_ref, conversation_id, layer);
CREATE INDEX IF NOT EXISTS idx_events_conversation ON events (org_id, app_id, user_id, conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_scope_v2 ON graph_nodes (org_id, app_id, user_id, graph_scope, scope_ref, conversation_id, label);
CREATE INDEX IF NOT EXISTS idx_graph_edges_scope_v2 ON graph_edges (org_id, app_id, user_id, graph_scope, scope_ref, conversation_id, relation);
CREATE INDEX IF NOT EXISTS idx_agents_org_app ON agents (org_id, app_id);
CREATE INDEX IF NOT EXISTS idx_conversations_listing ON conversations (org_id, app_id, agent_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_labels_admin ON conversation_labels (conversation_type, topic, outcome, risk_level);
CREATE INDEX IF NOT EXISTS idx_conversation_turns_lookup ON conversation_turns (conversation_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_lookup ON conversation_messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_retrieval_traces_lookup ON retrieval_traces (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_answer_audits_lookup ON answer_audits (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_lookup ON tool_invocations (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_candidates_listing ON memory_candidates (org_id, app_id, user_id, status, memory_scope, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_aliases_unique ON entity_aliases (org_id, app_id, canonical_label, alias_label);
