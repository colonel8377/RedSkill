"""indexer.py — SQLite upsert logic for skill zips.

Extracted from src/build_index.py.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Optional

from src.core.config import DB_PATH, DOWNLOADS_DIR, ROOT, SCHEMA_PATH
from src.index.parser import find_skill_md, normalize_metadata, parse_frontmatter, extract_name_from_heading


def init_db(conn: sqlite3.Connection, force: bool = False) -> None:
    """Create tables from schema.sql."""
    if force:
        conn.executescript("DROP TABLE IF EXISTS skills_fts; DROP TABLE IF EXISTS skills;")
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()


def index_one(
    zip_path: Path,
    conn: sqlite3.Connection,
    meta_from_discovered: dict,
) -> dict:
    """Parse one zip and upsert into skills + skills_fts.

    Returns stats dict: {status, identifier, has_skill_md, ...}
    """
    identifier = zip_path.name.split("@", 1)[0]
    stats = {"identifier": identifier, "status": "ok", "has_skill_md": False}

    # Manifest (sibling json)
    manifest_path = DOWNLOADS_DIR / f"{identifier}.manifest.json"
    sha256 = None
    if manifest_path.exists():
        try:
            mf = json.loads(manifest_path.read_text(encoding="utf-8"))
            sha256 = (mf.get("sha256") or "").lower() or None
        except Exception:
            pass

    discovered_meta = meta_from_discovered.get(identifier, {})

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            skill_md_path = find_skill_md(names)
            skill_md_text = ""
            skill_md_size = 0
            has_skill_md = 0
            fm_normalized = {}
            if skill_md_path:
                has_skill_md = 1
                with zf.open(skill_md_path) as f:
                    raw = f.read()
                skill_md_size = len(raw)
                text = raw.decode("utf-8", "replace")
                fm, body = parse_frontmatter(text)
                fm_normalized = normalize_metadata(fm)
                skill_md_text = body if body.strip() else text
            else:
                skill_md_text = ""

            name = fm_normalized.get("name") or extract_name_from_heading(skill_md_text)
            description = fm_normalized.get("description") or discovered_meta.get("description")
            version_fm = fm_normalized.get("version")
            version_zip = (
                zip_path.name.split("@", 1)[1].rsplit(".zip", 1)[0]
                if "@" in zip_path.name else None
            )
            version = version_fm or version_zip or discovered_meta.get("version")

            row = {
                "identifier": identifier,
                "name": name or discovered_meta.get("name"),
                "description": description,
                "version": version,
                "author": fm_normalized.get("author") or discovered_meta.get("author"),
                "category": fm_normalized.get("category"),
                "tags_json": json.dumps(
                    fm_normalized.get("tags") or discovered_meta.get("tags") or [],
                    ensure_ascii=False,
                ),
                "license": fm_normalized.get("license"),
                "homepage": fm_normalized.get("homepage"),
                "skill_md_path": skill_md_path,
                "skill_md_text": skill_md_text,
                "skill_md_size": skill_md_size,
                "zip_path": str(zip_path.relative_to(ROOT)),
                "zip_size": zip_path.stat().st_size,
                "sha256": sha256,
                "n_entries": len(names),
                "entries_json": json.dumps(names, ensure_ascii=False),
                "discovered_at": discovered_meta.get("updated_at"),
                "indexed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "has_skill_md": has_skill_md,
            }
            stats["has_skill_md"] = bool(has_skill_md)

            cols = list(row.keys())
            placeholders = ",".join(["?"] * len(cols))
            col_list = ",".join(cols)
            conn.execute(
                f"INSERT OR REPLACE INTO skills ({col_list}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )
            new_id = conn.execute(
                "SELECT id FROM skills WHERE identifier = ?", (identifier,)
            ).fetchone()[0]
            conn.execute("DELETE FROM skills_fts WHERE rowid = ?", (new_id,))
            conn.execute(
                "INSERT INTO skills_fts (rowid, name, description, body) VALUES (?, ?, ?, ?)",
                (new_id, row["name"] or "", row["description"] or "", row["skill_md_text"] or ""),
            )
            return stats
    except zipfile.BadZipFile as e:
        stats["status"] = "error"
        stats["error"] = f"BadZipFile: {e}"
        return stats
    except Exception as e:
        stats["status"] = "error"
        stats["error"] = f"{type(e).__name__}: {e}"
        return stats


def build_index(
    db_path: Path = DB_PATH,
    *,
    force: bool = False,
    limit: int = 0,
) -> int:
    """Main entry point: walk downloads/ and index all zips.

    Returns number of skills indexed.
    """
    import sys

    discovered = {}
    from src.core.config import DISCOVERED_PATH
    if DISCOVERED_PATH.exists():
        try:
            discovered = json.loads(DISCOVERED_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            sys.stderr.write(f"warn: discovered.json unreadable: {e}\n")

    zips = sorted(DOWNLOADS_DIR.glob("*.zip"))
    if limit > 0:
        zips = zips[:limit]

    if not zips:
        sys.stderr.write(f"no zips under {DOWNLOADS_DIR}\n")
        return 0

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    init_db(conn, force=force)

    n_ok = n_no_md = n_err = 0
    n_with_md = 0
    started = dt.datetime.now()
    for i, z in enumerate(zips, 1):
        stats = index_one(z, conn, discovered)
        if stats["status"] == "ok":
            n_ok += 1
            if stats.get("has_skill_md"):
                n_with_md += 1
        elif stats["status"] == "no_skill_md":
            n_no_md += 1
        else:
            n_err += 1
        if i % 200 == 0 or i == len(zips):
            conn.commit()
            elapsed = (dt.datetime.now() - started).total_seconds()
            rate = i / max(elapsed, 0.001)
            print(
                f"  indexed {i}/{len(zips)}  ok={n_ok} (with_md={n_with_md}) "
                f"no_md={n_no_md} err={n_err}  [{rate:.0f}/s]",
                flush=True,
            )

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    with_md = conn.execute("SELECT COUNT(*) FROM skills WHERE has_skill_md = 1").fetchone()[0]
    fts_rows = conn.execute("SELECT COUNT(*) FROM skills_fts").fetchone()[0]
    conn.close()

    print(f"\nDONE: {total} rows in skills, {with_md} with SKILL.md, {fts_rows} in FTS index")
    if n_err:
        print(f"  errors: {n_err}")
    print(f"  db: {db_path} ({db_path.stat().st_size // 1024} KB)")
    return total
