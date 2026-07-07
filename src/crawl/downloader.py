"""downloader.py — concurrent zip download with checkpoint/resume.

Uses ThreadPoolExecutor. Skips already-downloaded zips whose sha256 matches
the manifest. Writes checkpoint records on each download outcome.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from src.api.skill_bundle import get_skill_bundle
from src.core.config import DOWNLOADS_DIR, MAX_ZIP_BYTES, TIMEOUT_ZIP
from src.core.http_client import http_get
from src.core.logging import log
from src.crawl.checkpoint import load_checkpoint, save_checkpoint


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _existing_zip(ident: str) -> Optional[Path]:
    matches = sorted(DOWNLOADS_DIR.glob(f"{ident}@*.zip"))
    return matches[-1] if matches else None


def fetch_zip_bytes(zip_url: str) -> bytes:
    _, body = http_get(
        zip_url,
        accept="application/octet-stream, application/zip, */*",
        timeout=TIMEOUT_ZIP,
        max_bytes=MAX_ZIP_BYTES,
    )
    return body


def download_one(ident: str) -> tuple[str, str]:
    """Download one skill zip. Returns (identifier, status).

    Status ∈ {OK, SKIP, FAIL}.
    """
    try:
        existing = _existing_zip(ident)
        if existing:
            mf_path = DOWNLOADS_DIR / f"{ident}.manifest.json"
            if mf_path.exists():
                try:
                    mf = json.loads(mf_path.read_text(encoding="utf-8"))
                    expected = mf.get("sha256")
                    if expected:
                        actual = sha256_hex(existing.read_bytes())
                        if actual == expected:
                            return ident, "SKIP"
                        else:
                            log(f"  {ident}: existing sha mismatch, redownload")
                except Exception:
                    pass
            else:
                return ident, "SKIP"

        manifest = get_skill_bundle(ident)
        zip_bytes = fetch_zip_bytes(manifest.zip_url)
        actual = sha256_hex(zip_bytes)
        if actual != manifest.sha256:
            raise RuntimeError(
                f"sha256 mismatch for {ident}: got {actual} expected {manifest.sha256}"
            )
        version = manifest.version or "unknown"
        v_safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(version))
        target = DOWNLOADS_DIR / f"{ident}@{v_safe}.zip"
        # Remove older versions of same ident
        for old in DOWNLOADS_DIR.glob(f"{ident}@*.zip"):
            if old != target:
                try:
                    old.unlink()
                except Exception:
                    pass
        target.write_bytes(zip_bytes)
        # Save manifest sidecar
        (DOWNLOADS_DIR / f"{ident}.manifest.json").write_text(
            json.dumps({
                "identifier": manifest.identifier,
                "version": manifest.version,
                "zip_url": manifest.zip_url,
                "sha256": manifest.sha256,
                "bundle_size_bytes": manifest.bundle_size_bytes,
                "raw": manifest.raw,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        save_checkpoint(ident, "downloaded", sha256=actual)
        return ident, "OK"
    except Exception as e:
        log(f"  FAIL {ident}: {e}")
        save_checkpoint(ident, "failed", error=str(e))
        return ident, "FAIL"


def stage_download(idents: list[str], workers: int = 4) -> dict:
    """Download all given identifiers with concurrency and resume.

    Returns {ok: int, fail: int, skip: int, failed_list: [str]}.
    """
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    checkpoint = load_checkpoint()

    # Skip already verified
    pending = []
    skip_count = 0
    for ident in idents:
        existing = _existing_zip(ident)
        if existing:
            mf = DOWNLOADS_DIR / f"{ident}.manifest.json"
            if mf.exists():
                try:
                    expected = json.loads(mf.read_text(encoding="utf-8")).get("sha256")
                    if expected and sha256_hex(existing.read_bytes()) == expected:
                        skip_count += 1
                        continue
                except Exception:
                    pass
        # Also skip if checkpoint says downloaded
        if checkpoint.get(ident, {}).get("status") == "downloaded":
            skip_count += 1
            continue
        pending.append(ident)

    log(f"download begin: {len(idents)} total, already verified: {skip_count}, pending: {len(pending)}")

    ok = fail = 0
    failed_list = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(download_one, ident): ident for ident in pending}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            ident, status = fut.result()
            if status == "OK":
                ok += 1
                log(f"  OK   {ident}  ({i}/{len(pending)})")
            elif status == "FAIL":
                fail += 1
                failed_list.append(ident)
            time.sleep(0.05)

    log(f"download done: ok={ok}, fail={fail}, skip={skip_count}")
    return {"ok": ok, "fail": fail, "skip": skip_count, "failed": failed_list}
