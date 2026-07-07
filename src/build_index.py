#!/usr/bin/env python3
"""build_index.py — thin wrapper. Use python -m src.index.indexer for full control.

Usage:
    python -m src.build_index                # full index
    python -m src.build_index --force        # drop + recreate
    python -m src.build_index --limit 50     # smoke test
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.core.config import DB_PATH
from src.index.indexer import build_index


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Build local SQLite index of RedSkill zips")
    p.add_argument("--force", action="store_true", help="drop + recreate tables")
    p.add_argument("--limit", type=int, default=0, help="only index first N zips (0 = all)")
    p.add_argument("--db", type=Path, default=DB_PATH, help="sqlite path")
    args = p.parse_args(argv)

    n = build_index(db_path=args.db, force=args.force, limit=args.limit)
    return 0 if n > 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
