-- schema.sql — SQLite schema for local RedSkill search index
-- FTS5 with trigram tokenizer (sqlite >= 3.34) — supports CJK substring match
-- for queries >= 3 chars; the CLI falls back to LIKE for 1–2 char queries.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Main metadata table — one row per downloaded skill zip.
CREATE TABLE IF NOT EXISTS skills (
    id              INTEGER PRIMARY KEY,
    identifier      TEXT    NOT NULL UNIQUE,   -- redskill slug, e.g. "worldcup-founder-personality"
    name            TEXT,                       -- frontmatter name OR first # heading
    description     TEXT,                       -- frontmatter description
    version         TEXT,                       -- frontmatter version (may differ from zip filename version)
    author          TEXT,
    category        TEXT,                       -- frontmatter metadata.category (most common)
    tags_json       TEXT,                       -- JSON array, from discovered.json
    license         TEXT,
    homepage        TEXT,

    -- SKILL.md location + content
    skill_md_path   TEXT,                       -- path inside the zip, e.g. "SKILL.md" or "invest/SKILL.md"
    skill_md_text   TEXT,                       -- full SKILL.md content (frontmatter stripped)
    skill_md_size   INTEGER,                    -- raw bytes of SKILL.md

    -- Bundle info
    zip_path        TEXT,                       -- local path: downloads/<id>@<ver>.zip
    zip_size        INTEGER,                    -- zip file size in bytes
    sha256          TEXT,                       -- from sibling manifest
    n_entries       INTEGER,                    -- number of files inside the zip
    entries_json    TEXT,                       -- JSON array of all zip entry names

    -- Provenance
    discovered_at   TEXT,                       -- from discovered.json (updated_at if present)
    indexed_at      TEXT NOT NULL,              -- build_index run timestamp (UTC ISO)

    has_skill_md    INTEGER NOT NULL DEFAULT 0  -- 1 if SKILL.md found, 0 otherwise
);

CREATE INDEX IF NOT EXISTS idx_skills_name        ON skills(name);
CREATE INDEX IF NOT EXISTS idx_skills_author      ON skills(author);
CREATE INDEX IF NOT EXISTS idx_skills_category    ON skills(category);
CREATE INDEX IF NOT EXISTS idx_skills_zip_size    ON skills(zip_size);

-- Contentless FTS5: we manually populate (rowid, name, description, body).
-- No content-table indirection — keeps FTS independent of the skills table's
-- column names. Queries join back via rowid.
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    name,
    description,
    body,
    tokenize = 'trigram'
);

-- Note ID mapping: which xiaohongshu notes promote which skill.
CREATE TABLE IF NOT EXISTS skill_notes (
    note_id          TEXT PRIMARY KEY,
    skill_identifier TEXT NOT NULL,
    source           TEXT NOT NULL,  -- 'list_api' | 'search_fallback' | 'manual'
    confidence       REAL,            -- 1.0 for official API; fallback = similarity score
    discovered_at    TEXT,
    raw_json         TEXT,
    FOREIGN KEY (skill_identifier) REFERENCES skills(identifier)
);
CREATE INDEX IF NOT EXISTS idx_skill_notes_skill ON skill_notes(skill_identifier);

-- Official usage / engagement metrics for skills.
CREATE TABLE IF NOT EXISTS skill_usage (
    skill_identifier TEXT PRIMARY KEY,
    usage_count      INTEGER,
    download_count   INTEGER,
    click_count      INTEGER,
    raw_json         TEXT,
    updated_at       TEXT,
    FOREIGN KEY (skill_identifier) REFERENCES skills(identifier)
);
