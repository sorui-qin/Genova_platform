BEGIN;

ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS refinement_state VARCHAR(32) NOT NULL DEFAULT 'awaiting_feedback';

DO $$ BEGIN
    ALTER TABLE workflow_runs ADD CONSTRAINT ck_workflow_refinement_state
        CHECK (refinement_state IN ('awaiting_feedback', 'approved', 'running', 'closed'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

UPDATE workflow_runs
SET refinement_state = CASE
    WHEN status = 'approved' THEN 'approved'
    WHEN status = 'running' THEN 'running'
    WHEN status IN ('succeeded', 'failed', 'canceled', 'superseded') THEN 'closed'
    ELSE 'awaiting_feedback'
END;

CREATE TABLE IF NOT EXISTS workflow_interactions (
    id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    interaction_type VARCHAR(16) NOT NULL CONSTRAINT ck_workflow_interaction_type
        CHECK (interaction_type IN ('plan', 'modify', 'explain')),
    user_message TEXT NOT NULL,
    assistant_message TEXT NOT NULL,
    base_plan_version INTEGER NOT NULL,
    resulting_plan_version INTEGER NOT NULL,
    resulting_plan_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_interactions_workflow_created
    ON workflow_interactions (workflow_id, created_at);

COMMIT;
