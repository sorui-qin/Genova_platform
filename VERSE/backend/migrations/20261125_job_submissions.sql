CREATE TABLE IF NOT EXISTS job_submissions (
    owner_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key uuid NOT NULL,
    fingerprint varchar(64) NOT NULL,
    job_id uuid NOT NULL,
    PRIMARY KEY (owner_user_id, key)
);
