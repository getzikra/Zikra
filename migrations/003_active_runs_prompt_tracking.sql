-- Migration 003: Fix active_runs for prompt tracking
-- Adds prompt_name column and UNIQUE(runner) constraint required by GP upsert

ALTER TABLE zikra.active_runs
    ADD COLUMN IF NOT EXISTS prompt_name text;

COMMENT ON COLUMN zikra.active_runs.prompt_name IS
    'Human-readable name of the prompt being executed, from get_prompt calls';

-- Allow ON CONFLICT (runner) upsert — one active run per runner at a time
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'active_runs_runner_unique'
          AND conrelid = 'zikra.active_runs'::regclass
    ) THEN
        ALTER TABLE zikra.active_runs ADD CONSTRAINT active_runs_runner_unique UNIQUE (runner);
    END IF;
END $$;
