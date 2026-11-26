BEGIN;
ALTER TABLE agent_llm_profiles ADD COLUMN IF NOT EXISTS reasoning JSONB;
ALTER TABLE agent_user_settings ADD COLUMN IF NOT EXISTS reasoning JSONB;
COMMIT;
