-- Preserve current settings and ciphertext while adding named configurations.
BEGIN;
CREATE TABLE IF NOT EXISTS agent_llm_profiles (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    base_url VARCHAR(2048) NOT NULL,
    model VARCHAR(256) NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_agent_llm_profiles_user_id ON agent_llm_profiles(user_id);

ALTER TABLE agent_user_settings ADD COLUMN IF NOT EXISTS active_profile_id UUID REFERENCES agent_llm_profiles(id) ON DELETE SET NULL;

CREATE TEMP TABLE llm_profile_backfill ON COMMIT DROP AS
    SELECT gen_random_uuid() AS id, s.* FROM agent_user_settings s WHERE active_profile_id IS NULL;
INSERT INTO agent_llm_profiles(id,user_id,name,base_url,model,encrypted_api_key)
    SELECT id,user_id,'LLM',base_url,model,encrypted_api_key FROM llm_profile_backfill;
UPDATE agent_user_settings s SET active_profile_id=b.id FROM llm_profile_backfill b WHERE s.user_id=b.user_id;
COMMIT;
