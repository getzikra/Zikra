-- Migration 004: Add missing columns to prompt_runs used by log_run command

ALTER TABLE zikra.prompt_runs
    ADD COLUMN IF NOT EXISTS session_id    text,
    ADD COLUMN IF NOT EXISTS errors        text,
    ADD COLUMN IF NOT EXISTS files_modified integer DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_usd      numeric(12, 6);

COMMENT ON COLUMN zikra.prompt_runs.session_id    IS 'Claude Code session UUID from transcript';
COMMENT ON COLUMN zikra.prompt_runs.errors        IS 'Error messages captured during execution';
COMMENT ON COLUMN zikra.prompt_runs.files_modified IS 'Number of files modified in the session';
COMMENT ON COLUMN zikra.prompt_runs.cost_usd      IS 'Estimated API cost in USD for this run';
