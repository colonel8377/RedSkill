"""skill_bundle.py — get_skill_bundle (public, returns zip_url + sha256)."""
from __future__ import annotations

import json
import urllib.parse

from src.api.models import SkillBundle, _unwrap
from src.core.config import URL_BUNDLE
from src.core.http_client import http_get


def get_skill_bundle(identifier: str) -> SkillBundle:
    """Fetch the bundle manifest for a skill. No auth needed."""
    url = f"{URL_BUNDLE}?identifier={urllib.parse.quote(identifier, safe='')}"
    _, body = http_get(url, accept="application/json")
    try:
        data = json.loads(body.decode("utf-8"))
        data = _unwrap(data, "get_skill_bundle")
    except json.JSONDecodeError:
        raise RuntimeError(f"manifest non-JSON for {identifier}")
    return SkillBundle.from_response(data, identifier)
