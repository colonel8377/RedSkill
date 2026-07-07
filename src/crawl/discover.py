"""discover.py — skill discovery strategies.

Three strategies:
- ListDiscover: uses list_published_skills (requires cookie)
- SearchDiscover: uses search_published_skills (no cookie)
- KeywordSweep: iterates keywords through search (fallback)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from src.api.models import SkillSummary
from src.api.skill_list import list_skills
from src.api.skill_search import search_skills
from src.core.config import DISCOVERED_PATH, PAGE_LIMIT, SEED_PATH, SWEEP_KEYWORDS
from src.core.logging import log


def discover_via_list(cookie: str) -> dict[str, SkillSummary]:
    """Use list_published_skills with login cookie. Paginates until exhausted."""
    found: dict[str, SkillSummary] = {}
    page = 1
    empty_streak = 0
    while True:
        try:
            results = list_skills(cookie, page=page, limit=PAGE_LIMIT)
        except RuntimeError as e:
            msg = str(e)
            if "HTTP 401" in msg or "HTTP 403" in msg or "无登录" in msg or "未登录" in msg:
                raise RuntimeError(f"COOKIE_INVALID: {msg}")
            log(f"list page {page} error: {msg}; aborting list path")
            break

        if not results:
            empty_streak += 1
            if empty_streak >= 2:
                log(f"list converged at page {page} (empty)")
                break
            page += 1
            continue
        empty_streak = 0
        new = 0
        for s in results:
            if s.identifier and s.identifier not in found:
                found[s.identifier] = s
                new += 1
        log(f"list page {page}: {len(results)} rows, +{new} new, total {len(found)}")
        if len(results) < PAGE_LIMIT:
            log(f"list exhausted at page {page} (partial page)")
            break
        page += 1
        time.sleep(0.15)
    return found


def discover_via_search(keyword: str, found: dict[str, SkillSummary]) -> int:
    """Sweep one keyword across pages. Mutates `found` in place. Returns count added."""
    added = 0
    page = 1
    while page <= 50:
        try:
            results = search_skills(keyword, page=page, limit=PAGE_LIMIT)
        except RuntimeError as e:
            log(f"  search q={keyword!r} p={page} err: {e}")
            break
        if not results:
            break
        new = 0
        for s in results:
            if s.identifier and s.identifier not in found:
                found[s.identifier] = s
                new += 1
                added += 1
        if new == 0 and len(results) < PAGE_LIMIT:
            break
        if len(results) < PAGE_LIMIT:
            break
        page += 1
        time.sleep(0.1)
    return added


def discover_keyword_sweep(seed_path: Path = SEED_PATH) -> dict[str, SkillSummary]:
    """Fallback: seed from /tmp/redskill_union.json + sweep keywords."""
    found: dict[str, SkillSummary] = {}
    if seed_path.exists():
        try:
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            for ident in seed:
                if isinstance(ident, str):
                    found[ident] = SkillSummary(identifier=ident)
            log(f"loaded seed: {len(found)} ids from {seed_path}")
        except Exception as e:
            log(f"seed load failed: {e}")

    prev = -1
    for rnd in range(1, 4):
        round_new = 0
        for kw in SWEEP_KEYWORDS:
            try:
                n = discover_via_search(kw, found)
                round_new += n
            except Exception as e:
                log(f"sweep kw {kw!r} crashed: {e}")
        log(f"sweep round {rnd}: +{round_new}, total {len(found)}")
        delta = len(found) - prev
        prev = len(found)
        if delta < 10:
            log("sweep converged")
            break
    return found


def save_discovered(found: dict[str, SkillSummary]) -> None:
    """Persist discovered skills to discovered.json (strip raw for compactness)."""
    out = {
        k: {
            "identifier": v.identifier,
            "name": v.name,
            "description": v.description,
            "version": v.version,
            "tags": v.tags,
            "author": v.author,
        }
        for k, v in found.items()
    }
    DISCOVERED_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"saved {len(out)} records -> {DISCOVERED_PATH}")


def load_discovered() -> dict[str, dict]:
    """Load discovered.json into {identifier: meta_dict}."""
    if not DISCOVERED_PATH.exists():
        return {}
    return json.loads(DISCOVERED_PATH.read_text(encoding="utf-8"))
