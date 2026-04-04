-- Migration 005: fix project isolation
-- Changes UNIQUE(title, memory_type) to UNIQUE(title, memory_type, project)
-- so the same title can exist in different projects without conflict.

ALTER TABLE zikra.memories
    DROP CONSTRAINT IF EXISTS memories_title_memory_type_key;

ALTER TABLE zikra.memories
    DROP CONSTRAINT IF EXISTS memories_unique_title_type;

ALTER TABLE zikra.memories
    ADD CONSTRAINT memories_unique_title_type_project
    UNIQUE (title, memory_type, project);
