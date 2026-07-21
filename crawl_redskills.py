#!/usr/bin/env python3
"""crawl_redskills.py — thin CLI entry point for RedSkill crawler.

Usage:
    python crawl_redskills.py discover --cookie "<cookie string>"
    python crawl_redskills.py discover --keyword-sweep
    python crawl_redskills.py download [--workers 4]
    python crawl_redskills.py verify
    python crawl_redskills.py all --cookie "<cookie string>"
    python crawl_redskills.py map-notes --cookie "<cookie string>"
    python crawl_redskills.py fallback-notes --crawler <path> [--dry-run]
    python crawl_redskills.py notes --identifier <id>
    python crawl_redskills.py notes --note-id <note_id>
    python crawl_redskills.py usage --identifier <id>

All logic is delegated to src/{core,api,crawl,index} modules.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from src.core.config import DB_PATH, DISCOVERED_PATH, DOWNLOADS_DIR, LOG_PATH, ROOT
from src.core.logging import log, set_log_path
from src.crawl.discover import (
    discover_keyword_sweep,
    discover_via_list,
    load_discovered,
    save_discovered,
)
from src.crawl.downloader import stage_download
from src.crawl.verifier import stage_verify
from src.crawl.note_mapper import map_notes_from_list
from src.crawl.fallback_note_search import fallback_search as fallback_note_search
from src.index.note_usage import get_notes_for_skill, get_usage_for_skill


def cmd_discover(args) -> int:
    if args.keyword_sweep:
        found = discover_keyword_sweep()
    elif args.cookie:
        try:
            found = discover_via_list(args.cookie)
        except RuntimeError as e:
            if "COOKIE_INVALID" in str(e):
                log(f"cookie rejected by backend: {e}")
                log("falling back to keyword sweep")
                found = discover_keyword_sweep()
            else:
                raise
        if len(found) < 100:
            log(f"list path returned only {len(found)}; merging with keyword sweep")
            seed = discover_keyword_sweep()
            for k, v in seed.items():
                found.setdefault(k, v)
    else:
        log("discover requires --cookie or --keyword-sweep")
        return 2
    save_discovered(found)
    return 0


def cmd_download(args) -> int:
    found = load_discovered()
    if not found:
        log("no discovered.json; run discover first")
        return 1
    stage_download(sorted(found.keys()), workers=args.workers)
    return 0


def cmd_verify(args) -> int:
    discovered = load_discovered()
    stage_verify(discovered_count=len(discovered) if discovered else None)
    return 0


def cmd_all(args) -> int:
    if not args.cookie:
        log("all mode requires --cookie")
        return 2
    rc = cmd_discover(args)
    if rc != 0:
        return rc
    cmd_download(args)
    cmd_verify(args)
    return 0


def cmd_map_notes(args) -> int:
    if not args.cookie:
        log("map-notes requires --cookie")
        return 2
    stats = map_notes_from_list(args.cookie)
    log(f"map-notes done: {stats}")
    return 0


def cmd_fallback_notes(args) -> int:
    if not args.crawler:
        log("fallback-notes requires --crawler")
        return 2
    stats = fallback_note_search(
        args.crawler,
        db_path=args.db,
        delay=args.delay,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    log(f"fallback-notes done: {stats}")
    return 0


def cmd_notes(args) -> int:
    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    if args.identifier:
        rows = get_notes_for_skill(conn, args.identifier)
        if not rows:
            print(f"(no notes for {args.identifier})")
        for r in rows:
            print(f"{r['note_id']}  source={r['source']}  confidence={r['confidence']}  "
                  f"skill={r['skill_identifier']}")
        return 0
    if args.note_id:
        row = conn.execute(
            "SELECT * FROM skill_notes WHERE note_id = ?", (args.note_id,)
        ).fetchone()
        if not row:
            print(f"(no skill for note {args.note_id})")
            return 1
        print(f"note {row['note_id']} -> skill {row['skill_identifier']} "
              f"source={row['source']} confidence={row['confidence']}")
        return 0
    log("notes requires --identifier or --note-id")
    return 2


def cmd_usage(args) -> int:
    conn = sqlite3.connect(str(args.db))
    row = get_usage_for_skill(conn, args.identifier)
    if not row:
        print(f"(no usage data for {args.identifier})")
        return 1
    print(f"usage for {args.identifier}:")
    print(f"  usage_count:    {row['usage_count']}")
    print(f"  download_count: {row['download_count']}")
    print(f"  click_count:    {row['click_count']}")
    print(f"  updated_at:     {row['updated_at']}")
    if row["raw_json"]:
        print(f"  raw: {row['raw_json']}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="RedSkill crawler")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_disc = sub.add_parser("discover", help="discover skill identifiers")
    p_disc.add_argument("--cookie", default=None, help="login cookie string for list endpoint")
    p_disc.add_argument("--keyword-sweep", action="store_true", help="no-cookie fallback path")
    p_disc.set_defaults(func=cmd_discover)

    p_dl = sub.add_parser("download", help="download all discovered zips")
    p_dl.add_argument("--workers", type=int, default=4)
    p_dl.set_defaults(func=cmd_download)

    p_v = sub.add_parser("verify", help="sha256 verify downloaded zips")
    p_v.set_defaults(func=cmd_verify)

    p_all = sub.add_parser("all", help="discover + download + verify")
    p_all.add_argument("--cookie", default=None)
    p_all.add_argument("--workers", type=int, default=4)
    p_all.set_defaults(func=cmd_all)

    p_map = sub.add_parser("map-notes", help="extract note_id/usage from list API")
    p_map.add_argument("--cookie", required=True, help="login cookie string")
    p_map.set_defaults(func=cmd_map_notes)

    p_fb = sub.add_parser("fallback-notes", help="search notes by skill name via external crawler")
    p_fb.add_argument("--crawler", required=True, help="path to crawler executable")
    p_fb.add_argument("--db", type=Path, default=DB_PATH)
    p_fb.add_argument("--delay", type=float, default=1.0)
    p_fb.add_argument("--dry-run", action="store_true")
    p_fb.add_argument("--limit", type=int, default=0)
    p_fb.set_defaults(func=cmd_fallback_notes)

    p_notes = sub.add_parser("notes", help="show note_id mapping for a skill or skill for a note")
    p_notes.add_argument("--identifier", help="skill identifier")
    p_notes.add_argument("--note-id", help="xiaohongshu note id")
    p_notes.add_argument("--db", type=Path, default=DB_PATH)
    p_notes.set_defaults(func=cmd_notes)

    p_usage = sub.add_parser("usage", help="show usage metrics for a skill")
    p_usage.add_argument("--identifier", required=True, help="skill identifier")
    p_usage.add_argument("--db", type=Path, default=DB_PATH)
    p_usage.set_defaults(func=cmd_usage)

    args = p.parse_args(argv)
    ROOT.mkdir(exist_ok=True)
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    set_log_path(LOG_PATH)
    LOG_PATH.write_text("", encoding="utf-8")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
