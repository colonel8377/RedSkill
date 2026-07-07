# RedSkill — Local Skill Search Index

A self-contained local search engine over all public RedSkill (小红书 Red Skill) zips. Crawls the public API, downloads every published skill zip, parses each `SKILL.md`, and indexes it in SQLite with a CJK-friendly FTS5 trigram tokenizer.

```
3630 skills indexed · 358.9 MB zips · 146 MB sqlite · 100% SKILL.md coverage
```

## Project layout

```
RedSkill/
├── README.md
├── requirements.txt             # PyYAML
├── crawl_redskills.py           # crawler: discover → download → verify
├── discovered.json              # {identifier: metadata} map
├── downloads/                   # 3630 zips + manifest.json sidecars
│   ├── <id>@<ver>.zip
│   └── <id>.manifest.json       # {version, zip_url, sha256, bundle_size_bytes}
├── src/
│   ├── schema.sql               # sqlite schema (skills + skills_fts)
│   ├── build_index.py           # walk downloads/ → data/skills.db
│   └── search.py                # CLI search interface
└── data/
    └── skills.db                # generated — not in version control
```

**Code/data separation**: all source under `src/`; all generated artifacts (zip downloads, sqlite db, manifests) outside `src/`.

## Setup

```bash
conda create -n redskill-crawl python=3.11 -y
conda activate redskill-crawl
pip install -r requirements.txt
```

Python 3.11+ is required (uses stdlib `sqlite3` compiled with FTS5 + trigram tokenizer, available since sqlite 3.34 / Python 3.11).

## End-to-end pipeline

```bash
# 1. Crawl all public skills (no login needed for the public bundle API)
python crawl_redskills.py discover --keyword-sweep
python crawl_redskills.py download --workers 4
python crawl_redskills.py verify

# 2. Build the search index
python -m src.build_index --force

# 3. Search
python -m src.search "小红书爆款"
```

## Search interface

```bash
# Full-text search (CJK substrings ≥ 3 chars; English tokens)
python -m src.search "world cup"
python -m src.search "小红书爆款" -n 5

# Short queries auto-fall-back to LIKE (so 1–2 char queries still work)
python -m src.search "PPT" -n 3

# Filters
python -m src.search --author 王鲸
python -m src.search --category 内容创作
python -m src.search --tag 投资理财

# Exact identifier lookup
python -m src.search --identifier worldcup-founder-personality

# Print the full SKILL.md for one skill
python -m src.search --show worldcup-founder-personality

# Index stats / tag frequency table
python -m src.search --stats
python -m src.search --list-tags
```

## Schema

`skills` — one row per downloaded zip, with frontmatter fields (`name`, `description`, `version`, `author`, `category`, `tags_json`), provenance (`zip_path`, `sha256`, `zip_size`, `n_entries`, `entries_json`), and the parsed `SKILL.md` content (`skill_md_path`, `skill_md_text`, `skill_md_size`).

`skills_fts` — contentless FTS5 virtual table over `(name, description, body)` with the **trigram** tokenizer. Trigram handles Chinese, Japanese, Korean, emoji-free text uniformly as 3-character substrings — no external word segmenter needed.

Indexes: `name`, `author`, `category`, `zip_size` plus the implicit FTS5 index.

## How crawler + indexer relate

| Stage | Tool | Output |
|---|---|---|
| Discover | `crawl_redskills.py discover` | `discovered.json` |
| Download | `crawl_redskills.py download` | `downloads/*.zip` + `*.manifest.json` |
| Verify   | `crawl_redskills.py verify`   | sha256 reconciliation |
| Index    | `src.build_index` | `data/skills.db` |
| Query    | `src.search` | stdout |

The indexer reads `discovered.json` for fallback metadata and `downloads/*.manifest.json` for sha256, so re-running `--force` after a fresh crawl is safe and idempotent.

## Notes on coverage

- 3632 identifiers discovered; **3630 zips** downloaded; **2 unreachable** (`99`, `resume-design-pro-v1`) — both return `41000 "Skill 已被永久删除"` from the backend and cannot be retrieved by any means.
- All 3630 indexed skills have a parseable `SKILL.md`.
- 3114 have a frontmatter description; the remaining 516 fall back to first-heading extraction.
- Cookie for the `list_published_skills` endpoint is optional — the public `search_published_skills` + `get_skill_bundle` path already covers 99.9%.

## Operational tips

- Re-build the index any time: `python -m src.build_index --force` (~7 seconds for 3630 zips).
- Incremental re-runs without `--force` upsert by `identifier`, so newly crawled skills merge cleanly.
- WAL journaling is enabled; safe to query while a re-index is running.
- The `data/` directory is regenerated — do not commit it to git.
