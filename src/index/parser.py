"""parser.py — parse SKILL.md frontmatter and zip contents.

Extracted from src/build_index.py.
"""
from __future__ import annotations

import re
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

SKILL_MD_RE = re.compile(r"(^|/)skill\.md$", re.IGNORECASE)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def find_skill_md(names: list[str]) -> Optional[str]:
    """Return the most likely SKILL.md path from a zip's namelist."""
    candidates = [n for n in names if SKILL_MD_RE.search(n) and not n.startswith("__MACOSX")]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (n.count("/"), len(n)))
    return candidates[0]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter_dict, body_text).

    Falls back to ({}, text) if no frontmatter or yaml parse fails.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_yaml, body = m.group(1), m.group(2)
    try:
        if yaml is None:
            return {}, text
        fm = yaml.safe_load(raw_yaml)
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        return {}, text
    return fm, body


def extract_name_from_heading(text: str) -> Optional[str]:
    """Fallback: pull a name from the first Markdown H1."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip().lstrip("# ").strip()[:200] or None
    return None


def normalize_tags(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    return []


def normalize_metadata(fm: dict) -> dict:
    """Flatten common frontmatter shapes into schema columns."""
    md = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    return {
        "name": (str(fm.get("name") or "").strip() or None),
        "description": (str(fm.get("description") or "").strip() or None),
        "version": (str(fm.get("version") or "").strip() or None),
        "author": (str(fm.get("author") or "").strip() or None),
        "license": (str(fm.get("license") or "").strip() or None),
        "homepage": (str(fm.get("homepage") or "").strip() or None),
        "category": (str(md.get("category") or md.get("emoji_category") or "").strip() or None),
        "tags": normalize_tags(fm.get("tags") or md.get("tags")),
    }
