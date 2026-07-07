"""checkpoint.py — JSONL-based resume state for downloads.

Format (one JSON object per line):
{"identifier": "...", "status": "downloaded|failed", "timestamp": "...", "sha256": "..."}
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from src.core.config import CHECKPOINT_PATH


def load_checkpoint() -> dict[str, dict]:
    """Return {identifier: state} from the JSONL checkpoint file."""
    if not CHECKPOINT_PATH.exists():
        return {}
    state: dict[str, dict] = {}
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ident = record.get("identifier")
                if ident:
                    state[ident] = record
            except json.JSONDecodeError:
                continue
    return state


def save_checkpoint(
    identifier: str,
    status: str,
    *,
    sha256: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Append one record to the JSONL checkpoint file."""
    record = {
        "identifier": identifier,
        "status": status,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if sha256:
        record["sha256"] = sha256
    if error:
        record["error"] = error
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
