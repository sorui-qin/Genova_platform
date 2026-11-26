-- Agent sessions and action bindings. Apply once before the matching API/workers.

BEGIN;


CREATE TABLE agent_sessions (
	id UUID NOT NULL,
	owner_user_id UUID NOT NULL,
	goal TEXT NOT NULL,
	phase VARCHAR(40) NOT NULL,
	input_revision INTEGER NOT NULL,
	assets JSONB NOT NULL,
	confirmed_fields JSONB NOT NULL,
	pending_requirements JSONB NOT NULL,
	preparation_job_id UUID,
	active_workflow_id UUID,
	last_error VARCHAR(128),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(owner_user_id) REFERENCES users (id),
	FOREIGN KEY(preparation_job_id) REFERENCES jobs (id),
	FOREIGN KEY(active_workflow_id) REFERENCES workflow_runs (id)
)

;

CREATE INDEX ix_agent_sessions_owner_user_id ON agent_sessions (owner_user_id);


CREATE TABLE agent_turns (
	id UUID NOT NULL,
	session_id UUID NOT NULL,
	client_request_id UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	request JSONB NOT NULL,
	response JSONB NOT NULL,
	status VARCHAR(24) NOT NULL,
	attempt INTEGER NOT NULL,
	lease_until TIMESTAMP WITH TIME ZONE,
	planning_request_id UUID,
	audit JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_agent_turn_request UNIQUE (session_id, client_request_id),
	FOREIGN KEY(session_id) REFERENCES agent_sessions (id),
	FOREIGN KEY(planning_request_id) REFERENCES workflow_planning_requests (id)
)

;

CREATE INDEX ix_agent_turns_session_id ON agent_turns (session_id);


CREATE TABLE agent_action_proposals (
	id UUID NOT NULL,
	session_id UUID NOT NULL,
	turn_id UUID NOT NULL,
	kind VARCHAR(32) NOT NULL,
	payload JSONB NOT NULL,
	input_fingerprint JSONB NOT NULL,
	action_hash VARCHAR(64) NOT NULL,
	status VARCHAR(24) NOT NULL,
	workflow_id UUID,
	execution JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(session_id) REFERENCES agent_sessions (id),
	UNIQUE (turn_id),
	FOREIGN KEY(turn_id) REFERENCES agent_turns (id),
	FOREIGN KEY(workflow_id) REFERENCES workflow_runs (id)
)

;

CREATE INDEX ix_agent_action_proposals_workflow_id ON agent_action_proposals (workflow_id);

CREATE INDEX ix_agent_action_proposals_session_id ON agent_action_proposals (session_id);


CREATE TABLE agent_candidate_sets (
	id UUID NOT NULL,
	owner_user_id UUID NOT NULL,
	session_id UUID NOT NULL,
	proposal_id UUID NOT NULL,
	postprocessing_job_id UUID NOT NULL,
	artifact_hash VARCHAR(64) NOT NULL,
	selection_spec JSONB NOT NULL,
	molecule_ids JSONB NOT NULL,
	summary JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(owner_user_id) REFERENCES users (id),
	FOREIGN KEY(session_id) REFERENCES agent_sessions (id),
	UNIQUE (proposal_id),
	FOREIGN KEY(proposal_id) REFERENCES agent_action_proposals (id),
	FOREIGN KEY(postprocessing_job_id) REFERENCES jobs (id)
)

;

CREATE INDEX ix_agent_candidate_sets_session_id ON agent_candidate_sets (session_id);

ALTER TABLE workflow_runs ADD COLUMN action_proposal_id UUID REFERENCES agent_action_proposals(id);

COMMIT;
