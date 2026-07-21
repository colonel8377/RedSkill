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
USAGE_PATH = ROOT / "data" / "skill_usage.json"
EXPLORATION_MD = ROOT / "data" / "api_exploration.md"

NOTE_KEYS = [
    "note_id", "noteId", "note_ids",
    "post_id", "postId", "post_ids", "related_notes",
]
USAGE_KEYS = [
    "usage_count", "usageCount", "use_count",
    "download_count", "click_count", "call_count", "popularity",
]


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

    # Look for note_id / usage fields specifically
    note_id_fields = [(k, raw[k]) for k in NOTE_KEYS if k in raw]
    usage_fields = [(k, raw[k]) for k in USAGE_KEYS if k in raw]

    print("\n=== Note/Usage related fields ===")
    if note_id_fields or usage_fields:
        for k, v in note_id_fields + usage_fields:
            print(f"  {k}: {v}")
    else:
        print("  (no note_id, post_id, or usage_count fields found)")

    # Write exploration notes
    lines = [
        "# API Exploration: list_published_skills",
        "",
        "## Raw fields (from first result)",
        "```",
    ]
    for k in sorted(first.raw.keys()):
        lines.append(f"  {k}: {type(first.raw[k]).__name__}")
    lines.append("```")
    lines.append("")
    lines.append("## Field detection list")
    lines.append("Note keys checked:")
    for k in NOTE_KEYS:
        found = "yes" if k in raw else "no"
        lines.append(f"- `{k}`: {found}")
    lines.append("")
    lines.append("Usage keys checked:")
    for k in USAGE_KEYS:
        found = "yes" if k in raw else "no"
        lines.append(f"- `{k}`: {found}")
    lines.append("")
    lines.append("## Note ID Search")
    if note_id_fields:
        lines.append("Found note-related fields!")
        for k, v in note_id_fields:
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("**No note_id or post_id fields found in list API response.**")
    lines.append("")
    lines.append("## Usage/Engagement Search")
    if usage_fields:
        lines.append("Found usage-related fields!")
        for k, v in usage_fields:
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("**No usage_count, download_count, or click_count fields found.**")
    if not note_id_fields and not usage_fields:
        lines.append("")
        lines.append("### Alternative approaches:")
        lines.append("1. Search for the skill name on xiaohongshu.com web interface")
        lines.append("2. Try other API endpoints (e.g., note detail API)")
        lines.append("3. Use MediaCrawler to search by skill name directly")
    EXPLORATION_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nExploration notes -> {EXPLORATION_MD}")
    return 0


def _extract_note_ids(raw: dict) -> list[str]:
    """Return all note/post IDs found in a raw skill dict."""
    ids: list[str] = []
    for key in NOTE_KEYS:
        val = raw.get(key)
        if not val:
            continue
        if isinstance(val, str) or isinstance(val, int):
            ids.append(str(val))
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    for sub in ("note_id", "id", "post_id", "noteId", "postId"):
                        if item.get(sub):
                            ids.append(str(item[sub]))
                            break
                elif item:
                    ids.append(str(item))
    return ids


def _extract_usage(raw: dict) -> dict:
    """Return usage numbers if any are present."""
    usage: dict = {}
    for key in USAGE_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        try:
            usage[key] = int(val)
        except (ValueError, TypeError):
            usage[key] = val
    return usage


def cmd_extract(cookie: str) -> int:
    """Extract full note_id -> identifier mapping from all pages."""
    log("Extracting note_id -> identifier mapping from all list pages...")
    note_map: dict[str, str | dict] = {}
    usage_map: dict[str, dict] = {}
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
        page_with_usage = 0
        for s in results:
            raw = s.raw
            note_ids = _extract_note_ids(raw)
            for note_id in note_ids:
                note_map[note_id] = s.identifier
                page_with_note += 1

            usage = _extract_usage(raw)
            if usage:
                usage_map[s.identifier] = {
                    "usage_count": usage.get("usage_count") or usage.get("usageCount") or usage.get("use_count"),
                    "download_count": usage.get("download_count"),
                    "click_count": usage.get("click_count") or usage.get("call_count"),
                    "raw_json": json.dumps(usage, ensure_ascii=False),
                }
                page_with_usage += 1

        log(
            f"Page {page}: notes={page_with_note}, usage={page_with_usage}/"
            f"{len(results)}, total map {len(note_map)}"
        )
        if len(results) < 100:
            break
        page += 1

    if note_map:
        NODE_ID_MAP_PATH.write_text(
            json.dumps(note_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log(f"Saved {len(note_map)} note_id mappings -> {NODE_ID_MAP_PATH}")
    else:
        log("No note_id found in any results.")

    if usage_map:
        USAGE_PATH.write_text(
            json.dumps(usage_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log(f"Saved {len(usage_map)} usage records -> {USAGE_PATH}")
    else:
        log("No usage/engagement fields found.")

    if not note_map and not usage_map:
        # Document the failure
        lines = [
            "# note_id / usage extraction failed",
            "",
            "The list_published_skills API did not return note_id or usage fields.",
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
        return 1

    return 0


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

        # Check for note_id / usage fields
        note_fields = {k: v for k, v in s.raw.items() if k in NOTE_KEYS}
        usage_fields = {k: v for k, v in s.raw.items() if k in USAGE_KEYS}
        if note_fields or usage_fields:
            print(f"  NOTE/USAGE FIELDS: {note_fields} {usage_fields}")
        else:
            print("  (no note/post/usage fields)")

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
