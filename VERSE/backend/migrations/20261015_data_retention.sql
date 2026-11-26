CREATE TABLE IF NOT EXISTS data_retention_policy (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    first_enabled_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS data_retention_deletions (
    id UUID PRIMARY KEY,
    paths JSONB NOT NULL,
    queue_job_ids JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_user_activity_at TIMESTAMPTZ;
UPDATE agent_sessions AS s SET last_user_activity_at = GREATEST(
    s.created_at,
    (SELECT MAX(t.created_at) FROM agent_turns AS t
     WHERE t.session_id = s.id AND t.audit->>'trigger' IS NULL),
    (SELECT MAX(c.created_at) FROM workflow_commands AS c WHERE c.target_id = s.id),
    (SELECT MAX(e.created_at) FROM workflow_edit_sessions AS e WHERE e.session_id = s.id)
) WHERE s.last_user_activity_at IS NULL;
