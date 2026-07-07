"""robustness.py — robustness scoring (the opposite of clickbait).

Measures how robust/well-crafted a skill is:
- Structured sections (## headings)
- Code/examples/references (``` blocks)
- Body length > 2000 chars
- Multiple files in zip (n_entries > 1)
- Version > 1.0.0 (evidence of iteration)
"""
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

from src.core.config import DB_PATH, ROOT

OUT_DIR = ROOT / "data"

HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
CODE_BLOCK_RE = re.compile(r"```", re.MULTILINE)


def _score_sections(body: str) -> float:
    """Score based on structured headings."""
    headings = len(HEADING_RE.findall(body))
    if headings >= 5:
        return 1.0
    if headings >= 3:
        return 0.7
    if headings >= 1:
        return 0.3
    return 0.0


def _score_code_examples(body: str) -> float:
    """Score based on code blocks (executable content)."""
    blocks = len(CODE_BLOCK_RE.findall(body)) // 2  # pairs of ```
    if blocks >= 3:
        return 1.0
    if blocks >= 1:
        return 0.5
    return 0.0


def _score_body_length(body: str) -> float:
    """Longer = more thorough content."""
    length = len(body)
    if length > 5000:
        return 1.0
    if length > 2000:
        return 0.6
    if length > 1000:
        return 0.3
    return 0.0


def _score_zip_complexity(n_entries: int) -> float:
    """Multi-file zips suggest more sophisticated skills."""
    if n_entries > 10:
        return 1.0
    if n_entries > 5:
        return 0.7
    if n_entries > 1:
        return 0.3
    return 0.0


def _score_version_maturity(version: str | None) -> float:
    """Versions > 1.0.0 suggest iteration."""
    if not version:
        return 0.0
    try:
        v = version.replace("v", "").split(".")
        major = int(v[0])
        minor = int(v[1]) if len(v) > 1 else 0
        if major > 1:
            return 1.0
        if major == 1 and minor > 0:
            return 0.5
        return 0.0
    except (ValueError, IndexError):
        return 0.0


def compute_robustness_scores() -> list[dict]:
    """Compute robustness scores for all skills and save to CSV."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT identifier, name, version, skill_md_text, n_entries, zip_size
        FROM skills
        WHERE name IS NOT NULL AND name <> ''
    """).fetchall()
    conn.close()

    print(f"Computing robustness scores for {len(rows)} skills...")

    results = []
    for r in rows:
        body = r["skill_md_text"] or ""
        n_entries = r["n_entries"] or 1

        scores = {
            "identifier": r["identifier"],
            "name": r["name"],
            "version": r["version"],
            "body_len": len(body),
            "n_entries": n_entries,
            "sections": round(_score_sections(body), 3),
            "code_examples": round(_score_code_examples(body), 3),
            "body_length": round(_score_body_length(body), 3),
            "zip_complexity": round(_score_zip_complexity(n_entries), 3),
            "version_maturity": round(_score_version_maturity(r["version"]), 3),
        }

        # Composite (equal weights)
        components = [
            scores["sections"],
            scores["code_examples"],
            scores["body_length"],
            scores["zip_complexity"],
            scores["version_maturity"],
        ]
        scores["composite"] = round(sum(components) / len(components), 3)
        results.append(scores)

    results.sort(key=lambda x: -x["composite"])

    # Save
    out_path = OUT_DIR / "robustness_scores.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"  Saved -> {out_path}")

    # Summary
    composites = [r["composite"] for r in results]
    print(f"\n  Robustness Score Distribution:")
    print(f"    Mean:   {sum(composites)/len(composites):.3f}")
    print(f"    Median: {sorted(composites)[len(composites)//2]:.3f}")
    print(f"    Max:    {max(composites):.3f}")
    print(f"    >= 0.5: {sum(1 for c in composites if c >= 0.5)} ({sum(1 for c in composites if c >= 0.5)/len(composites)*100:.1f}%)")
    print(f"    >= 0.7: {sum(1 for c in composites if c >= 0.7)} ({sum(1 for c in composites if c >= 0.7)/len(composites)*100:.1f}%)")

    # Top robust skills
    print(f"\n  Top-10 Robustness Scores:")
    for r in results[:10]:
        print(f"    [{r['identifier']}] {r['name'][:60]}: {r['composite']:.3f}")

    return results


if __name__ == "__main__":
    compute_robustness_scores()
