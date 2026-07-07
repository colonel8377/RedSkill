#!/usr/bin/env python3
"""crawl_redskills.py — thin CLI entry point for RedSkill crawler.

Usage:
    python crawl_redskills.py discover --cookie "<cookie string>"
    python crawl_redskills.py discover --keyword-sweep
    python crawl_redskills.py download [--workers 4]
    python crawl_redskills.py verify
    python crawl_redskills.py all --cookie "<cookie string>"

All logic is delegated to src/{core,api,crawl,index} modules.
"""
from __future__ import annotations

import argparse
import sys

from src.core.config import DISCOVERED_PATH, DOWNLOADS_DIR, LOG_PATH, ROOT
from src.core.logging import log, set_log_path
from src.crawl.discover import (
    discover_keyword_sweep,
    discover_via_list,
    load_discovered,
    save_discovered,
)
from src.crawl.downloader import stage_download
from src.crawl.verifier import stage_verify


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

    args = p.parse_args(argv)
    ROOT.mkdir(exist_ok=True)
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    set_log_path(LOG_PATH)
    LOG_PATH.write_text("", encoding="utf-8")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
