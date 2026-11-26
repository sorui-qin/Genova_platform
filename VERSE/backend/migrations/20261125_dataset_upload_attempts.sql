CREATE TABLE IF NOT EXISTS dataset_upload_attempts (
    owner_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key uuid NOT NULL,
    dataset_id uuid,
    PRIMARY KEY (owner_user_id, key)
);
