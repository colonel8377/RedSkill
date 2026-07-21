#!/usr/bin/env python3
"""search.py — query the local RedSkill SQLite index.

Examples:
    python -m src.index.search "小红书爆款"
    python -m src.index.search "world cup" --limit 20
    python -m src.index.search --author "王鲸"
    python -m src.index.search --category 内容创作 --limit 50
    python -m src.index.search --tag 投资理财
    python -m src.index.search --identifier worldcup-founder-personality
    python -m src.index.search --list-tags
    python -m src.index.search --stats
    python -m src.index.search --show worldcup-founder-personality
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from src.core.config import DB_PATH


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        sys.stderr.write(
            f"db not found at {DB_PATH}\n"
            f"  run: python -m src.index.indexer\n"
        )
        sys.exit(2)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def human_size(n: int | None) -> str:
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def search_keyword(conn: sqlite3.Connection, q: str, limit: int, with_metrics: bool = False) -> list[sqlite3.Row]:
    metrics_sql = """
        , (SELECT COUNT(*) FROM skill_notes WHERE skill_identifier = s.identifier) AS note_count
        , (SELECT usage_count FROM skill_usage WHERE skill_identifier = s.identifier) AS usage_count
    """ if with_metrics else ""
    q = q.strip()
    if len(q) >= 3:
        sql = f"""
            SELECT s.id, s.identifier, s.name, s.description, s.author, s.category,
                   s.version, s.zip_path, s.zip_size,
                   bm25(skills_fts) AS score
                   {metrics_sql}
            FROM skills_fts
            JOIN skills s ON s.id = skills_fts.rowid
            WHERE skills_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """
        try:
            return conn.execute(sql, (q, limit)).fetchall()
        except sqlite3.OperationalError:
            pass
    pat = f"%{q}%"
    sql = f"""
        SELECT id, identifier, name, description, author, category,
               version, zip_path, zip_size,
               0.0 AS score
               {metrics_sql.replace('s.identifier', 'identifier')}
        FROM skills
        WHERE name LIKE ? OR description LIKE ? OR identifier LIKE ?
        ORDER BY
            CASE WHEN identifier LIKE ? THEN 0
                 WHEN name LIKE ? THEN 1 ELSE 2 END,
            length(description) ASC
        LIMIT ?
    """
    return conn.execute(sql, (pat, pat, pat, pat, pat, limit)).fetchall()


def filter_rows(
    conn: sqlite3.Connection,
    *,
    author: str | None,
    category: str | None,
    tag: str | None,
    limit: int,
    with_metrics: bool = False,
) -> list[sqlite3.Row]:
    where = []
    params: list = []
    if author:
        where.append("author LIKE ?")
        params.append(f"%{author}%")
    if category:
        where.append("category LIKE ?")
        params.append(f"%{category}%")
    if tag:
        where.append("tags_json LIKE ?")
        params.append(f'%"{tag}"%')
    metrics_sql = """
        , (SELECT COUNT(*) FROM skill_notes WHERE skill_identifier = skills.identifier) AS note_count
        , (SELECT usage_count FROM skill_usage WHERE skill_identifier = skills.identifier) AS usage_count
    """ if with_metrics else ""
    sql = f"""
        SELECT id, identifier, name, description, author, category,
               version, zip_path, zip_size, 0.0 AS score
               {metrics_sql}
        FROM skills
        {('WHERE ' + ' AND '.join(where)) if where else ''}
        ORDER BY name
        LIMIT ?
    """
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def print_rows(rows: list[sqlite3.Row], verbose: bool, with_metrics: bool = False) -> None:
    if not rows:
        print("(no results)")
        return
    for r in rows:
        name = r["name"] or "(unnamed)"
        print(f"[{r['identifier']}] {name}")
        if r["description"]:
            d = r["description"]
            print(f"    {d[:160]}{'…' if len(d) > 160 else ''}")
        meta_bits = []
        if r["author"]:
            meta_bits.append(f"author={r['author']}")
        if r["category"]:
            meta_bits.append(f"cat={r['category']}")
        if r["version"]:
            meta_bits.append(f"v={r['version']}")
        meta_bits.append(human_size(r["zip_size"]))
        if with_metrics:
            note_count = r["note_count"] if "note_count" in r.keys() else None
            usage_count = r["usage_count"] if "usage_count" in r.keys() else None
            meta_bits.append(f"notes={note_count or 0}")
            meta_bits.append(f"usage={usage_count if usage_count is not None else '?'}")
        if verbose:
            meta_bits.append(r["zip_path"])
        if meta_bits:
            print(f"    {' | '.join(meta_bits)}")


def show_skill_md(conn: sqlite3.Connection, identifier: str) -> int:
    row = conn.execute(
        "SELECT name, skill_md_path, skill_md_text, skill_md_size, zip_path "
        "FROM skills WHERE identifier = ?",
        (identifier,),
    ).fetchone()
    if not row:
        sys.stderr.write(f"not found: {identifier}\n")
        return 1
    print(f"# {row['name'] or identifier}")
    print(f"# path-in-zip: {row['skill_md_path']}  ({row['skill_md_size']} bytes)")
    print(f"# zip: {row['zip_path']}")
    print()
    print(row["skill_md_text"] or "(no SKILL.md in this skill)")
    return 0


def show_stats(conn: sqlite3.Connection) -> None:
    n_skills = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    n_with_md = conn.execute("SELECT COUNT(*) FROM skills WHERE has_skill_md = 1").fetchone()[0]
    n_with_desc = conn.execute(
        "SELECT COUNT(*) FROM skills WHERE description IS NOT NULL AND description <> ''"
    ).fetchone()[0]
    total_size = conn.execute("SELECT COALESCE(SUM(zip_size),0) FROM skills").fetchone()[0]
    n_authors = conn.execute(
        "SELECT COUNT(DISTINCT author) FROM skills WHERE author IS NOT NULL"
    ).fetchone()[0]
    biggest = conn.execute(
        "SELECT identifier, name, zip_size FROM skills ORDER BY zip_size DESC LIMIT 5"
    ).fetchall()
    print(f"db:                {DB_PATH} ({DB_PATH.stat().st_size // 1024} KB)")
    print(f"total skills:      {n_skills}")
    print(f"  with SKILL.md:   {n_with_md}")
    print(f"  with description:{n_with_desc}")
    print(f"  distinct authors:{n_authors}")
    print(f"total zip bytes:   {human_size(total_size)}")
    print("top 5 by zip size:")
    for r in biggest:
        print(f"  {human_size(r['zip_size']):>8}  [{r['identifier']}]  {r['name'] or ''}")


def list_tags(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT identifier, tags_json FROM skills WHERE tags_json LIKE '%[%]'")
    freq: dict[str, int] = {}
    for r in rows:
        try:
            for t in json.loads(r["tags_json"] or "[]"):
                t = str(t).strip()
                if t:
                    freq[t] = freq.get(t, 0) + 1
        except json.JSONDecodeError:
            continue
    if not freq:
        print("(no tags indexed)")
        return
    for t, n in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{n:>5}  {t}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Search the local RedSkill index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("query", nargs="?", help="full-text query")
    p.add_argument("--limit", "-n", type=int, default=20)
    p.add_argument("--author", help="filter by author (substring)")
    p.add_argument("--category", help="filter by category (substring)")
    p.add_argument("--tag", help="filter by tag (exact match)")
    p.add_argument("--identifier", help="exact identifier lookup")
    p.add_argument("--show", metavar="IDENTIFIER", help="print full SKILL.md")
    p.add_argument("--stats", action="store_true", help="print index stats")
    p.add_argument("--list-tags", action="store_true", help="print tag frequency table")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--with-metrics", action="store_true", help="show note_count and usage_count")
    args = p.parse_args(argv)

    conn = connect()

    if args.stats:
        show_stats(conn)
        return 0
    if args.list_tags:
        list_tags(conn)
        return 0
    if args.show:
        return show_skill_md(conn, args.show)
    if args.identifier:
        metrics_sql = """
            , (SELECT COUNT(*) FROM skill_notes WHERE skill_identifier = skills.identifier) AS note_count
            , (SELECT usage_count FROM skill_usage WHERE skill_identifier = skills.identifier) AS usage_count
        """ if args.with_metrics else ""
        rows = conn.execute(
            f"""
            SELECT id, identifier, name, description, author, category,
                   version, zip_path, zip_size, 0.0 AS score
                   {metrics_sql}
            FROM skills WHERE identifier = ?
            """,
            (args.identifier,),
        ).fetchall()
        print_rows(rows, args.verbose, with_metrics=args.with_metrics)
        return 0
    if args.author or args.category or args.tag:
        rows = filter_rows(
            conn,
            author=args.author,
            category=args.category,
            tag=args.tag,
            limit=args.limit,
            with_metrics=args.with_metrics,
        )
        print_rows(rows, args.verbose, with_metrics=args.with_metrics)
        return 0
    if not args.query:
        p.print_help()
        return 2

    rows = search_keyword(conn, args.query, args.limit, with_metrics=args.with_metrics)
    print_rows(rows, args.verbose, with_metrics=args.with_metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
