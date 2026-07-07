"""verifier.py — SHA-256 batch verification of downloaded zips."""
from __future__ import annotations

import json
from pathlib import Path

from src.core.config import DOWNLOADS_DIR
from src.core.logging import log
from src.crawl.downloader import sha256_hex


def stage_verify(discovered_count: int | None = None) -> dict:
    """Verify all downloaded zips against their manifest sha256.

    Returns stats dict.
    """
    zips = sorted(DOWNLOADS_DIR.glob("*.zip"))
    ok = mismatch = 0
    missing_manifest = []
    mismatch_list = []

    for z in zips:
        ident = z.name.split("@", 1)[0]
        mf = DOWNLOADS_DIR / f"{ident}.manifest.json"
        if not mf.exists():
            missing_manifest.append(ident)
            continue
        try:
            expected = json.loads(mf.read_text(encoding="utf-8")).get("sha256")
        except Exception:
            missing_manifest.append(ident)
            continue
        if not expected:
            missing_manifest.append(ident)
            continue
        actual = sha256_hex(z.read_bytes())
        if actual == expected:
            ok += 1
        else:
            mismatch += 1
            mismatch_list.append(f"{ident} got={actual[:12]}... expected={expected[:12]}...")

    have_zip = {z.name.split("@", 1)[0] for z in zips}
    missing_zips = 0
    if discovered_count:
        missing_zips = discovered_count - len(zips)

    log("=" * 60)
    log("VERIFY REPORT")
    if discovered_count:
        log(f"  discovered:    {discovered_count}")
    log(f"  downloaded:    {len(zips)}")
    log(f"  verified OK:   {ok}")
    log(f"  sha mismatch:  {mismatch}")
    if discovered_count:
        log(f"  missing zip:   {missing_zips}")
    if mismatch_list:
        log("  -- mismatches --")
        for m in mismatch_list[:20]:
            log(f"    {m}")
    if missing_manifest:
        log(f"  -- missing manifest (first 20) --")
        for m in missing_manifest[:20]:
            log(f"    {m}")
    log("=" * 60)

    return {
        "downloaded": len(zips),
        "verified_ok": ok,
        "mismatch": mismatch,
        "missing_manifest": len(missing_manifest),
        "missing_zips": missing_zips,
    }
