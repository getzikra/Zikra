VERSION = 7
DESCRIPTION = "memory_links: directed wikilink edges for [[title]] references"

SQL = """
CREATE TABLE IF NOT EXISTS memory_links (
    from_id TEXT NOT NULL,
    to_id   TEXT NOT NULL,
    anchor  TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id),
    FOREIGN KEY (from_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (to_id)   REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_links_to ON memory_links(to_id);
"""
