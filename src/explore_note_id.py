#!/usr/bin/env python3
"""explore_note_id.py — explore list_published_skills API to find note_id mapping.

Usage:
    # Explore what fields the list API returns (need cookie)
    python -m src.explore_note_id --cookie "<cookie>" --explore

    # Extract full note_id -> identifier mapping
    python -m src.explore_note_id --cookie "<cookie>" --extract

    # Also try search API for comparison (no cookie needed)
    python -m src.explore_note_id --compare-search

Output:
    data/note_id_map.json — {"note_id": "skill_identifier", ...}
    data/api_exploration.md — field listing and exploration notes
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.api.skill_list import list_skills
from src.api.skill_search import search_skills
from src.core.config import ROOT
from src.core.logging import log

NODE_ID_MAP_PATH = ROOT / "data" / "note_id_map.json"
EXPLORATION_MD = ROOT / "data" / "api_exploration.md"


def _inspect_skill(skill, label: str) -> None:
    """Print all available fields from a skill's raw data."""
    raw = skill.raw
    print(f"\n=== {label} ===")
    print(f"identifier: {skill.identifier}")
    print(f"name: {skill.name}")
    print(f"Fields in raw ({len(raw)} total):")
    for k, v in sorted(raw.items()):
        val_str = str(v)
        if len(val_str) > 200:
            val_str = val_str[:200] + "…"
        print(f"  {k}: {val_str}")


def cmd_explore(cookie: str) -> int:
    """Explore list API response fields."""
    log("Exploring list_published_skills API (page 1)...")
    try:
        results = list_skills(cookie, page=1, limit=5)
    except RuntimeError as e:
        log(f"ERROR: {e}")
        return 1

    if not results:
        log("No results returned from list API")
        return 1

    log(f"Got {len(results)} results from page 1")

    # Inspect first result in detail
    first = results[0]
    _inspect_skill(first, "First result (list API)")

    # Look for note_id specifically
    note_id_fields = []
    for k, v in first.raw.items():
        if "note" in k.lower() or "post" in k.lower() or "usage" in k.lower():
            note_id_fields.append((k, v))

    print("\n=== Note/Usage related fields ===")
    if note_id_fields:
        for k, v in note_id_fields:
            print(f"  {k}: {v}")
    else:
        print("  (no note_id, post_id, or usage_count fields found)")

    # Write exploration notes
    lines = [
        "# API Exploration: list_published_skills",
        "",
        f"## Raw fields (from first result)",
        "```",
    ]
    for k in sorted(first.raw.keys()):
        lines.append(f"  {k}: {type(first.raw[k]).__name__}")
    lines.append("```")
    lines.append("")
    lines.append("## Note ID Search")
    if note_id_fields:
        lines.append("Found note-related fields!")
        for k, v in note_id_fields:
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("**No note_id or usage_count fields found in list API response.**")
        lines.append("")
        lines.append("### Alternative approaches:")
        lines.append("1. Search for the skill name on xiaohongshu.com web interface")
        lines.append("2. Try other API endpoints (e.g., note detail API)")
        lines.append("3. Use MediaCrawler to search by skill name directly")
    EXPLORATION_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nExploration notes -> {EXPLORATION_MD}")
    return 0


def cmd_extract(cookie: str) -> int:
    """Extract full note_id -> identifier mapping from all pages."""
    log("Extracting note_id -> identifier mapping from all list pages...")
    note_map = {}
    page = 1
    empty_streak = 0

    while True:
        try:
            results = list_skills(cookie, page=page, limit=100)
        except RuntimeError as e:
            log(f"Error on page {page}: {e}")
            break

        if not results:
            empty_streak += 1
            if empty_streak >= 2:
                break
            page += 1
            continue

        empty_streak = 0
        page_with_note = 0
        for s in results:
            raw = s.raw
            # Try various possible note_id field names
            note_id = (
                raw.get("note_id")
                or raw.get("noteId")
                or raw.get("post_id")
                or raw.get("postId")
            )
            if note_id:
                note_map[str(note_id)] = s.identifier
                page_with_note += 1

            # Also check usage_count
            usage = raw.get("usage_count") or raw.get("usageCount")
            if usage:
                log(f"  Found usage_count: {usage} for {s.identifier}")

        log(f"Page {page}: {page_with_note}/{len(results)} have note_id, total map {len(note_map)}")
        if len(results) < 100:
            break
        page += 1

    if note_map:
        NODE_ID_MAP_PATH.write_text(
            json.dumps(note_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log(f"Saved {len(note_map)} note_id mappings -> {NODE_ID_MAP_PATH}")
    else:
        log("No note_id found in any results. Writing documentation.")
        # Document the failure
        lines = [
            "# note_id Extraction Failed",
            "",
            "The list_published_skills API did not return note_id in any of the skill objects.",
            "",
            "## Fields observed across all skills:",
            "See api_exploration.md for field listing.",
            "",
            "## Recommended next steps:",
            "1. Run MediaCrawler with skill names as search queries",
            "2. Match results back to our identifiers by skill name",
            "3. Manual mapping for top skills",
        ]
        EXPLORATION_MD.write_text("\n".join(lines), encoding="utf-8")

    return 0 if note_map else 1


def cmd_compare_search() -> int:
    """Compare what search API returns vs list API fields."""
    log("Comparing search API fields (no cookie)...")
    # Search for a common term to get diverse results
    try:
        results = search_skills("小红书", page=1, limit=3)
    except RuntimeError as e:
        log(f"ERROR: {e}")
        return 1

    if not results:
        log("No results from search API")
        return 1

    log(f"Got {len(results)} results from search API")
    for i, s in enumerate(results):
        _inspect_skill(s, f"Search result {i+1}")

        # Check for note_id fields
        note_fields = {k: v for k, v in s.raw.items() if "note" in k.lower() or "post" in k.lower()}
        if note_fields:
            print(f"  NOTE FIELDS: {note_fields}")
        else:
            print("  (no note/post fields)")

    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Explore Red Skill API for note_id mapping")
    p.add_argument("--cookie", help="Login cookie for list_published_skills")
    p.add_argument("--explore", action="store_true", help="Explore API response fields")
    p.add_argument("--extract", action="store_true", help="Extract full note_id -> identifier map")
    p.add_argument("--compare-search", action="store_true", help="Compare search API fields")
    args = p.parse_args(argv)

    if args.compare_search:
        return cmd_compare_search()

    if not args.cookie:
        print("Error: --cookie is required for --explore and --extract", file=sys.stderr)
        print("Try --compare-search first (no cookie needed) to see what fields are available",
              file=sys.stderr)
        return 2

    if args.extract:
        return cmd_extract(args.cookie)
    if args.explore:
        return cmd_explore(args.cookie)

    # Default: explore
    return cmd_explore(args.cookie)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
