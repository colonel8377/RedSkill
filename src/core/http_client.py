"""http_client.py — HTTP helpers extracted from crawl_redskills.py.

Provides http_get with retry, _read_body, _build_headers.
"""
from __future__ import annotations

import json
import random
import socket
import time
import urllib.error
import urllib.request
from typing import Optional

from src.core.config import MAX_JSON_BYTES, MAX_RETRY, TIMEOUT_JSON, UA


def _retry_sleep(attempt: int) -> None:
    time.sleep(0.5 * (attempt + 1) + random.random() * 0.4)


def _read_body(resp, max_bytes: int) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = resp.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise RuntimeError(f"response exceeds {max_bytes // 1024 // 1024} MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _build_headers(cookie: Optional[str], accept: str) -> dict:
    h = {"User-Agent": UA, "Accept": accept}
    if cookie:
        c = cookie.strip()
        if not c.lower().startswith("cookie:"):
            h["Cookie"] = c
        else:
            h["Cookie"] = c.split(":", 1)[1].strip()
    return h


def http_get(
    url: str,
    *,
    cookie: Optional[str] = None,
    accept: str = "application/json",
    timeout: int = TIMEOUT_JSON,
    max_bytes: int = MAX_JSON_BYTES,
) -> tuple[dict, bytes]:
    """GET a URL with retry, returning (response_headers_dict, body_bytes)."""
    headers = _build_headers(cookie, accept)
    req = urllib.request.Request(url, headers=headers)
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRY + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_headers = {str(k).lower(): v for k, v in resp.headers.items()}
                return resp_headers, _read_body(resp, max_bytes)
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()[:2000]
            except Exception:
                pass
            finally:
                try:
                    e.close()
                except Exception:
                    pass
            msg = ""
            if body:
                try:
                    j = json.loads(body.decode("utf-8", "replace"))
                    if isinstance(j, dict):
                        msg = str(j.get("msg") or j.get("message") or "")
                except Exception:
                    msg = body.decode("utf-8", "replace")[:200]
            err = RuntimeError(f"HTTP {e.code} {e.reason} {msg} :: {url}")
            if 400 <= e.code < 500 and e.code != 429:
                raise err
            last_err = err
        except urllib.error.URLError as e:
            last_err = RuntimeError(f"URLError {e.reason} :: {url}")
        except (TimeoutError, socket.timeout):
            last_err = RuntimeError(f"timeout >{timeout}s :: {url}")
        if attempt < MAX_RETRY:
            _retry_sleep(attempt)
    raise last_err if last_err else RuntimeError(f"unknown error :: {url}")
