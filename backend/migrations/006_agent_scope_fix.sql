ALTER TABLE agents
ADD COLUMN IF NOT EXISTS public_agent_id VARCHAR(128) NOT NULL DEFAULT '';

UPDATE agents
SET public_agent_id = agent_id
WHERE public_agent_id = '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_scope_public_unique
ON agents (org_id, app_id, public_agent_id);
