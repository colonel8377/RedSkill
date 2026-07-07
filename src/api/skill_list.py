"""skill_list.py — list_published_skills (requires login cookie)."""
from __future__ import annotations

import json
import urllib.parse

from src.api.models import SkillSummary, _extract_results, _unwrap
from src.core.config import PAGE_LIMIT, URL_LIST
from src.core.http_client import http_get


def list_skills(
    cookie: str,
    *,
    page: int = 1,
    limit: int = PAGE_LIMIT,
) -> list[SkillSummary]:
    """List published skills. Requires login cookie.

    Returns raw data that may include note_id, usage_count etc.
    """
    params = urllib.parse.urlencode({"limit": limit, "page": page})
    url = f"{URL_LIST}?{params}"
    _, body = http_get(url, cookie=cookie, accept="application/json")
    data = json.loads(body.decode("utf-8"))
    data = _unwrap(data, "list_published_skills")
    results = _extract_results(data)
    return [SkillSummary.from_raw(r) for r in results if isinstance(r, dict)]
