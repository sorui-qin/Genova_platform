ALTER TABLE data_retention_deletions ADD COLUMN IF NOT EXISTS owner_user_id UUID;
ALTER TABLE data_retention_deletions ADD COLUMN IF NOT EXISTS origin VARCHAR(16) NOT NULL DEFAULT 'retention';
