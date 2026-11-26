BEGIN;
ALTER TABLE agent_llm_profiles ADD COLUMN IF NOT EXISTS auth_type VARCHAR(16) NOT NULL DEFAULT 'api_key';
ALTER TABLE agent_llm_profiles ADD COLUMN IF NOT EXISTS encrypted_oauth_credentials TEXT;
ALTER TABLE agent_llm_profiles ALTER COLUMN encrypted_api_key DROP NOT NULL;
ALTER TABLE agent_user_settings ALTER COLUMN encrypted_api_key DROP NOT NULL;
COMMIT;
