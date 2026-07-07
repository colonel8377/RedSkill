"""skill_search.py — search_published_skills (public, no cookie needed)."""
from __future__ import annotations

import json
import urllib.parse

from src.api.models import SkillSummary, _extract_results, _unwrap
from src.core.config import PAGE_LIMIT, URL_SEARCH
from src.core.http_client import http_get


def search_skills(
    keyword: str,
    *,
    page: int = 1,
    limit: int = PAGE_LIMIT,
) -> list[SkillSummary]:
    """Search published skills by keyword. No auth needed."""
    params = urllib.parse.urlencode({"q": keyword, "limit": limit, "page": page})
    url = f"{URL_SEARCH}?{params}"
    _, body = http_get(url, accept="application/json")
    data = json.loads(body.decode("utf-8"))
    data = _unwrap(data, "search_published_skills")
    results = _extract_results(data)
    return [SkillSummary.from_raw(r) for r in results if isinstance(r, dict)]
