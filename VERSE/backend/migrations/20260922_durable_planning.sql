BEGIN;

CREATE TABLE IF NOT EXISTS workflow_planning_requests (
    id UUID PRIMARY KEY,
    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_request_id UUID NOT NULL,
    message TEXT NOT NULL,
    protein_context_id UUID NOT NULL REFERENCES datasets(id),
    status VARCHAR(32) NOT NULL DEFAULT 'planning'
        CONSTRAINT ck_workflow_planning_status
        CHECK (status IN ('planning', 'interrupted', 'failed', 'linked')),
    attempt INTEGER NOT NULL DEFAULT 1
        CONSTRAINT ck_workflow_planning_attempt CHECK (attempt >= 1 AND attempt <= 1000),
    workflow_id UUID NULL UNIQUE REFERENCES workflow_runs(id) ON DELETE RESTRICT,
    last_error VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_workflow_planning_owner_client_request
        UNIQUE (owner_user_id, client_request_id),
    CONSTRAINT ck_workflow_planning_link
        CHECK ((status = 'linked') = (workflow_id IS NOT NULL))
);

DO $planning_schema$
DECLARE
    planning_table REGCLASS;
    missing_columns TEXT[];
BEGIN
    planning_table := to_regclass(format('%I.workflow_planning_requests', current_schema()));
    SELECT array_agg(required.name ORDER BY required.name)
      INTO missing_columns
      FROM (VALUES
          ('id'), ('owner_user_id'), ('client_request_id'), ('message'),
          ('protein_context_id'), ('status'), ('attempt'), ('workflow_id'),
          ('last_error'), ('created_at'), ('updated_at')
      ) AS required(name)
      LEFT JOIN information_schema.columns existing
        ON existing.table_schema = current_schema()
       AND existing.table_name = 'workflow_planning_requests'
       AND existing.column_name = required.name
     WHERE existing.column_name IS NULL;
    IF array_length(missing_columns, 1) IS NOT NULL THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: missing columns: %',
            array_to_string(missing_columns, ', ');
    END IF;

    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests
         WHERE id IS NULL OR owner_user_id IS NULL OR client_request_id IS NULL
            OR message IS NULL OR protein_context_id IS NULL OR status IS NULL
            OR attempt IS NULL OR created_at IS NULL OR updated_at IS NULL
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: required column contains NULL';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests GROUP BY id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: duplicate id';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests
        GROUP BY owner_user_id, client_request_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: duplicate owner_user_id/client_request_id';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests
         WHERE workflow_id IS NOT NULL
        GROUP BY workflow_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: duplicate workflow_id';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests
         WHERE status NOT IN ('planning', 'interrupted', 'failed', 'linked')
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: invalid status';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests WHERE attempt < 1 OR attempt > 1000
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: invalid attempt';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests
         WHERE (status = 'linked') <> (workflow_id IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: invalid linked/workflow_id state';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests request
        LEFT JOIN users owner ON owner.id = request.owner_user_id
        WHERE owner.id IS NULL
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: orphan owner_user_id';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests request
        LEFT JOIN datasets context ON context.id = request.protein_context_id
        WHERE context.id IS NULL
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: orphan protein_context_id';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_planning_requests request
        LEFT JOIN workflow_runs workflow ON workflow.id = request.workflow_id
        WHERE request.workflow_id IS NOT NULL AND workflow.id IS NULL
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: orphan workflow_id';
    END IF;

    ALTER TABLE workflow_planning_requests
        ALTER COLUMN owner_user_id SET NOT NULL,
        ALTER COLUMN client_request_id SET NOT NULL,
        ALTER COLUMN message SET NOT NULL,
        ALTER COLUMN protein_context_id SET NOT NULL,
        ALTER COLUMN status SET DEFAULT 'planning',
        ALTER COLUMN status SET NOT NULL,
        ALTER COLUMN attempt SET DEFAULT 1,
        ALTER COLUMN attempt SET NOT NULL,
        ALTER COLUMN created_at SET NOT NULL,
        ALTER COLUMN updated_at SET NOT NULL;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.contype = 'p'
           AND (
               SELECT array_agg(attribute.attname::TEXT ORDER BY key_column.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key_column(attnum, ordinality)
                 JOIN pg_attribute attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = key_column.attnum
           ) = ARRAY['id']
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT workflow_planning_requests_pkey PRIMARY KEY (id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.conname = 'uq_workflow_planning_owner_client_request'
           AND NOT (
               constraint_row.contype = 'u'
               AND (
                   SELECT array_agg(attribute.attname::TEXT ORDER BY key_column.ordinality)
                     FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key_column(attnum, ordinality)
                     JOIN pg_attribute attribute
                       ON attribute.attrelid = constraint_row.conrelid
                      AND attribute.attnum = key_column.attnum
               ) = ARRAY['owner_user_id', 'client_request_id']
           )
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: malformed constraint uq_workflow_planning_owner_client_request';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.conname = 'uq_workflow_planning_owner_client_request'
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT uq_workflow_planning_owner_client_request
            UNIQUE (owner_user_id, client_request_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.contype = 'u'
           AND (
               SELECT array_agg(attribute.attname::TEXT ORDER BY key_column.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key_column(attnum, ordinality)
                 JOIN pg_attribute attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = key_column.attnum
           ) = ARRAY['workflow_id']
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT uq_workflow_planning_workflow_id UNIQUE (workflow_id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.conname = 'ck_workflow_planning_status'
           AND NOT (
               lower(pg_get_constraintdef(constraint_row.oid)) LIKE '%status%'
               AND ARRAY(
                   SELECT value_match[1]
                     FROM regexp_matches(
                         lower(pg_get_constraintdef(constraint_row.oid)),
                         '''([^'']+)''',
                         'g'
                     ) AS value_match
                    ORDER BY value_match[1]
               ) = ARRAY['failed', 'interrupted', 'linked', 'planning']
           )
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: malformed constraint ck_workflow_planning_status';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.conname = 'ck_workflow_planning_status'
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT ck_workflow_planning_status
            CHECK (status IN ('planning', 'interrupted', 'failed', 'linked'));
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.conname = 'ck_workflow_planning_attempt'
           AND NOT (
               replace(lower(pg_get_constraintdef(constraint_row.oid)), ' ', '') LIKE '%attempt>=1%'
               AND replace(lower(pg_get_constraintdef(constraint_row.oid)), ' ', '') LIKE '%attempt<=1000%'
           )
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: malformed constraint ck_workflow_planning_attempt';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.conname = 'ck_workflow_planning_attempt'
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT ck_workflow_planning_attempt CHECK (attempt >= 1 AND attempt <= 1000);
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.conname = 'ck_workflow_planning_link'
           AND NOT (
               lower(pg_get_constraintdef(constraint_row.oid)) LIKE '%status%'
               AND lower(pg_get_constraintdef(constraint_row.oid)) LIKE '%workflow_id%'
               AND lower(pg_get_constraintdef(constraint_row.oid)) LIKE '%is not null%'
               AND ARRAY(
                   SELECT value_match[1]
                     FROM regexp_matches(
                         lower(pg_get_constraintdef(constraint_row.oid)),
                         '''([^'']+)''',
                         'g'
                     ) AS value_match
               ) = ARRAY['linked']
           )
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: malformed constraint ck_workflow_planning_link';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.conname = 'ck_workflow_planning_link'
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT ck_workflow_planning_link
            CHECK ((status = 'linked') = (workflow_id IS NOT NULL));
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.contype = 'f'
           AND (
               SELECT array_agg(attribute.attname::TEXT ORDER BY key_column.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key_column(attnum, ordinality)
                 JOIN pg_attribute attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = key_column.attnum
           ) = ARRAY['owner_user_id']
           AND NOT (constraint_row.confrelid = to_regclass(format('%I.users', current_schema()))
                    AND constraint_row.confdeltype = 'c')
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: unsafe owner_user_id foreign key';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.contype = 'f'
           AND constraint_row.confrelid = to_regclass(format('%I.users', current_schema()))
           AND constraint_row.confdeltype = 'c'
           AND (
               SELECT array_agg(attribute.attname::TEXT ORDER BY key_column.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key_column(attnum, ordinality)
                 JOIN pg_attribute attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = key_column.attnum
           ) = ARRAY['owner_user_id']
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT fk_workflow_planning_owner
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.contype = 'f'
           AND constraint_row.confrelid = to_regclass(format('%I.datasets', current_schema()))
           AND (
               SELECT array_agg(attribute.attname::TEXT ORDER BY key_column.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key_column(attnum, ordinality)
                 JOIN pg_attribute attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = key_column.attnum
           ) = ARRAY['protein_context_id']
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT fk_workflow_planning_context
            FOREIGN KEY (protein_context_id) REFERENCES datasets(id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.contype = 'f'
           AND (
               SELECT array_agg(attribute.attname::TEXT ORDER BY key_column.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key_column(attnum, ordinality)
                 JOIN pg_attribute attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = key_column.attnum
           ) = ARRAY['workflow_id']
           AND NOT (constraint_row.confrelid = to_regclass(format('%I.workflow_runs', current_schema()))
                    AND constraint_row.confdeltype = 'r')
    ) THEN
        RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: unsafe workflow_id foreign key';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid = planning_table
           AND constraint_row.contype = 'f'
           AND constraint_row.confrelid = to_regclass(format('%I.workflow_runs', current_schema()))
           AND constraint_row.confdeltype = 'r'
           AND (
               SELECT array_agg(attribute.attname::TEXT ORDER BY key_column.ordinality)
                 FROM unnest(constraint_row.conkey) WITH ORDINALITY AS key_column(attnum, ordinality)
                 JOIN pg_attribute attribute
                   ON attribute.attrelid = constraint_row.conrelid
                  AND attribute.attnum = key_column.attnum
           ) = ARRAY['workflow_id']
    ) THEN
        ALTER TABLE workflow_planning_requests
            ADD CONSTRAINT fk_workflow_planning_workflow
            FOREIGN KEY (workflow_id) REFERENCES workflow_runs(id) ON DELETE RESTRICT;
    END IF;
EXCEPTION WHEN OTHERS THEN
    IF SQLERRM LIKE 'PLANNING_SCHEMA_VALIDATION_FAILED:%' THEN
        RAISE;
    END IF;
    RAISE EXCEPTION 'PLANNING_SCHEMA_VALIDATION_FAILED: %', SQLERRM;
END
$planning_schema$;

CREATE INDEX IF NOT EXISTS idx_workflow_planning_owner_updated
    ON workflow_planning_requests (owner_user_id, updated_at);

COMMIT;
