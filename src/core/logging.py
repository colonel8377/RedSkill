"""logging.py — thread-safe structured logging.

Outputs to both console and file.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

_print_lock = threading.Lock()
_log_path: Path | None = None


def set_log_path(path: Path) -> None:
    """Set the log file path. Call once at startup."""
    global _log_path
    _log_path = path


def log(msg: str) -> None:
    """Thread-safe log to console and file."""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with _print_lock:
        print(line, flush=True)
    if _log_path:
        try:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
