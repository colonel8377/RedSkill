"""models.py — dataclass models for Red Skill API responses.

Key design: every model keeps the full `raw` dict from the API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _unwrap(data: Any, label: str) -> dict:
    """Strip {code, success, data} envelope from API responses."""
    if not isinstance(data, dict):
        return data if isinstance(data, dict) else {}
    if "data" in data and ("code" in data or "success" in data):
        code = data.get("code")
        success = data.get("success")
        if (code is not None and code != 0) or success is False:
            msg = (data.get("msg") or data.get("message") or "").strip() or "backend error"
            raise RuntimeError(f"{label}: {msg} (code={code})")
        inner = data.get("data")
        return inner if isinstance(inner, dict) else {}
    return data


def _extract_results(data: dict) -> list:
    """Robustly find the results/items list across response shapes."""
    for key in ("results", "items", "list", "skills"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    nested = data.get("data")
    if isinstance(nested, dict):
        for key in ("results", "items", "list", "skills"):
            v = nested.get(key)
            if isinstance(v, list):
                return v
    return []


@dataclass
class SkillSummary:
    """Lightweight skill metadata from search/list APIs. Always keeps raw."""
    identifier: str
    name: str = ""
    description: str = ""
    version: str | None = None
    tags: list[str] = field(default_factory=list)
    author: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: dict) -> "SkillSummary":
        if not isinstance(raw, dict):
            return cls(identifier="", raw={})
        ident = raw.get("identifier") or raw.get("id") or raw.get("skill_id") or ""
        return cls(
            identifier=str(ident),
            name=raw.get("name") or raw.get("title") or "",
            description=raw.get("description") or raw.get("desc") or "",
            version=raw.get("version"),
            tags=raw.get("tags") or raw.get("categories") or [],
            author=raw.get("author") or raw.get("creator") or "",
            raw=raw,
        )


@dataclass
class SkillBundle:
    """Manifest/bundle info from get_skill_bundle API."""
    identifier: str
    version: str | None = None
    zip_url: str = ""
    sha256: str | None = None
    bundle_size_bytes: int | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_response(cls, data: dict, identifier: str) -> "SkillBundle":
        bundle = cls(
            identifier=identifier,
            version=data.get("version"),
            zip_url=data.get("zip_url", ""),
            sha256=(data.get("sha256") or "").lower() or None,
            bundle_size_bytes=data.get("bundle_size_bytes"),
            raw=data,
        )
        if not bundle.zip_url or not bundle.sha256:
            raise RuntimeError(f"manifest missing zip_url/sha256 for {identifier}: {data}")
        return bundle
