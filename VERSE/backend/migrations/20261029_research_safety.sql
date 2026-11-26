CREATE TABLE IF NOT EXISTS agent_research_tasks (
 id UUID PRIMARY KEY, owner_user_id UUID NOT NULL REFERENCES users(id), goal TEXT NOT NULL,
 state VARCHAR(24) NOT NULL DEFAULT 'unassessed' CHECK (state IN ('unassessed','allowed','blocked')),
 revision INTEGER NOT NULL DEFAULT 0, pending_turn_id UUID,
 assessment JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_research_tasks_owner_user_id ON agent_research_tasks(owner_user_id);
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS research_task_id UUID REFERENCES agent_research_tasks(id);
ALTER TABLE agent_turns ADD COLUMN IF NOT EXISTS research_task_id UUID REFERENCES agent_research_tasks(id);
ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS research_task_id UUID REFERENCES agent_research_tasks(id);
CREATE INDEX IF NOT EXISTS ix_agent_sessions_research_task_id ON agent_sessions(research_task_id);
CREATE INDEX IF NOT EXISTS ix_agent_turns_research_task_id ON agent_turns(research_task_id);
CREATE INDEX IF NOT EXISTS ix_workflow_runs_research_task_id ON workflow_runs(research_task_id);
ALTER TABLE workflow_planning_requests ADD COLUMN IF NOT EXISTS research_task_id UUID REFERENCES agent_research_tasks(id);
CREATE INDEX IF NOT EXISTS ix_workflow_planning_requests_research_task_id ON workflow_planning_requests(research_task_id);
