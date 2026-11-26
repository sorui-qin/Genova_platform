CREATE TABLE IF NOT EXISTS agent_work_preferences (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text VARCHAR(500) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_agent_work_preferences_user_id ON agent_work_preferences (user_id);
