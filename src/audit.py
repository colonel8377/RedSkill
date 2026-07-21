#!/usr/bin/env python3
"""audit.py — data quality audit for RedSkill SQLite index.

Usage:
    python -m src.audit                 # full audit -> data/audit_report.md
    python -m src.audit --json          # also dump data/audit.json

Reads data/skills.db + downloads/*.manifest.json.
Produces data/audit_report.md.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "skills.db"
DOWNLOADS_DIR = ROOT / "downloads"
OUTPUT_MD = ROOT / "data" / "audit_report.md"
OUTPUT_JSON = ROOT / "data" / "audit.json"

REPORT = []  # lines of markdown


def h(msg: str = "", level: int = 2) -> None:
    """Append a heading or blank line to the report."""
    if not msg:
        REPORT.append("")
    elif level == 1:
        REPORT.append(f"# {msg}")
    elif level == 2:
        REPORT.append(f"## {msg}")
    elif level == 3:
        REPORT.append(f"### {msg}")
    REPORT.append("")


def line(txt: str) -> None:
    REPORT.append(txt)


def table(headers: list[str], rows: list[list[str]]) -> None:
    REPORT.append("| " + " | ".join(headers) + " |")
    REPORT.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        REPORT.append("| " + " | ".join(str(c) for c in r) + " |")
    REPORT.append("")


def pct(n: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{n / total * 100:.1f}%"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────
# 1. Field coverage
# ─────────────────────────────────────────
def audit_field_coverage(conn: sqlite3.Connection) -> dict:
    h("1. Field Coverage")
    total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    fields = [
        ("author", "author IS NOT NULL AND author <> ''"),
        ("category", "category IS NOT NULL AND category <> ''"),
        ("description", "description IS NOT NULL AND description <> ''"),
        ("version", "version IS NOT NULL AND version <> ''"),
        ("tags_json", "tags_json IS NOT NULL AND tags_json <> '[]'"),
        ("skill_md_text", "skill_md_text IS NOT NULL AND skill_md_text <> ''"),
        ("sha256", "sha256 IS NOT NULL"),
        ("license", "license IS NOT NULL AND license <> ''"),
        ("homepage", "homepage IS NOT NULL AND homepage <> ''"),
        ("n_entries", "n_entries IS NOT NULL"),
        ("zip_size", "zip_size IS NOT NULL"),
        ("discovered_at", "discovered_at IS NOT NULL"),
    ]
    results = {}
    rows = []
    for name, condition in fields:
        n = conn.execute(f"SELECT COUNT(*) FROM skills WHERE {condition}").fetchone()[0]
        rows.append([name, str(n), pct(n, total)])
        results[name] = {"count": n, "pct": round(n / total * 100, 1)}
    table(["Field", "Non-empty", "Fill Rate"], rows)
    line(f"**Total rows**: {total}")
    results["_total"] = total
    return results


# ─────────────────────────────────────────
# 2. Name duplicates
# ─────────────────────────────────────────
def audit_name_duplicates(conn: sqlite3.Connection) -> dict:
    h("2. Name Duplicates")
    rows = conn.execute("""
        SELECT name, COUNT(*) AS cnt, GROUP_CONCAT(identifier, ', ') AS idents
        FROM skills
        WHERE name IS NOT NULL AND name <> ''
        GROUP BY name
        HAVING cnt > 1
        ORDER BY cnt DESC
        LIMIT 50
    """).fetchall()

    if not rows:
        line("(no duplicate names found)")
        return {"top_dupes": []}

    dupes = []
    table_rows = []
    for r in rows:
        table_rows.append([r["name"], str(r["cnt"]), r["idents"][:120]])
        dupes.append({"name": r["name"], "count": r["cnt"], "idents": r["idents"]})

    table(["Name", "Count", "Sample Identifiers"], table_rows)

    total_duped = conn.execute("""
        SELECT SUM(cnt) FROM (
            SELECT COUNT(*) AS cnt FROM skills
            WHERE name IS NOT NULL AND name <> ''
            GROUP BY name HAVING cnt > 1
        )
    """).fetchone()[0] or 0
    total_named = conn.execute(
        "SELECT COUNT(*) FROM skills WHERE name IS NOT NULL AND name <> ''"
    ).fetchone()[0]
    line(f"**Skills involved in duplicates**: {total_duped} / {total_named} named skills")
    return {"top_dupes": dupes, "total_duped": total_duped, "total_named": total_named}


# ─────────────────────────────────────────
# 3. Content near-duplicates (MinHash)
# ─────────────────────────────────────────
def _minhash_signature(tokens: list[int], num_hashes: int = 128) -> list[int]:
    """Simple MinHash using universal hashing (no external library needed)."""
    if not tokens:
        return [2**31 - 1] * num_hashes
    max_int = 2**31 - 1
    sig = [max_int] * num_hashes
    for token in tokens:
        for i in range(num_hashes):
            # Use a simple universal hash: (a*x + b) mod p mod max_int
            a = (i * 2 + 1)
            b = (i * 3 + 7)
            h = ((a * token + b) % 2147483647) % max_int
            if h < sig[i]:
                sig[i] = h
    return sig


def _jaccard_from_signatures(sig1: list[int], sig2: list[int]) -> float:
    """Estimate Jaccard similarity from two MinHash signatures."""
    matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
    return matches / len(sig1)


def _tokenize(text: str) -> list[int]:
    """Simple 3-gram tokenization to integers."""
    if not text:
        return []
    # Use character 3-grams for language-agnostic matching
    tokens = []
    for i in range(len(text) - 2):
        chunk = text[i:i+3]
        tokens.append(hash(chunk) & 0x7FFFFFFF)
    return tokens


def audit_content_near_dupes(conn: sqlite3.Connection) -> dict:
    h("3. Content Near-Duplicates (MinHash + Jaccard)")

    rows = conn.execute("""
        SELECT identifier, name, skill_md_text
        FROM skills
        WHERE skill_md_text IS NOT NULL AND skill_md_text <> ''
    """).fetchall()

    if not rows:
        line("(no skill_md_text content to compare)")
        return {"near_dupes": []}

    # Build signatures
    sigs = {}
    names = {}
    for r in rows:
        tokens = _tokenize(r["skill_md_text"])
        sigs[r["identifier"]] = _minhash_signature(tokens)
        names[r["identifier"]] = r["name"] or ""

    # Find pairs with Jaccard > 0.90
    idents = list(sigs.keys())
    high_sim = []
    threshold = 0.90
    n = len(idents)

    for i in range(n):
        for j in range(i + 1, n):
            sim = _jaccard_from_signatures(sigs[idents[i]], sigs[idents[j]])
            if sim >= threshold:
                high_sim.append({
                    "ident1": idents[i],
                    "name1": names[idents[i]],
                    "ident2": idents[j],
                    "name2": names[idents[j]],
                    "jaccard": round(sim, 4),
                })

    high_sim.sort(key=lambda x: -x["jaccard"])

    line(f"**MinHash signatures**: {n} skills")
    line(f"**Pairs with Jaccard >= {threshold:.0%}**: {len(high_sim)}")
    h("")

    if high_sim:
        table_rows = []
        for pair in high_sim[:30]:
            table_rows.append([
                pair["ident1"][:50],
                pair["name1"][:40],
                pair["ident2"][:50],
                pair["name2"][:40],
                f"{pair['jaccard']:.3f}",
            ])
        table(
            ["Identifier A", "Name A", "Identifier B", "Name B", "Jaccard"],
            table_rows,
        )
        if len(high_sim) > 30:
            line(f"  ... and {len(high_sim) - 30} more pairs")

    return {"near_dupes": high_sim, "total_compared": n}


# ─────────────────────────────────────────
# 4. Version distribution
# ─────────────────────────────────────────
def audit_versions(conn: sqlite3.Connection) -> dict:
    h("4. Version Distribution")
    total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    # Parse version strings
    rows = conn.execute("""
        SELECT version, COUNT(*) AS cnt
        FROM skills
        WHERE version IS NOT NULL AND version <> ''
        GROUP BY version
        ORDER BY cnt DESC
    """).fetchall()

    if not rows:
        line("(no version data)")
        return {}

    # Detect version patterns
    unknown = sum(r["cnt"] for r in rows if r["version"] == "unknown")
    has_ver = total - conn.execute(
        "SELECT COUNT(*) FROM skills WHERE version IS NULL OR version = ''"
    ).fetchone()[0]
    without_ver = total - has_ver

    table_rows = []
    for r in rows[:20]:
        table_rows.append([r["version"], str(r["cnt"]), pct(r["cnt"], total)])

    table(["Version", "Count", "% of Total"], table_rows)
    if len(rows) > 20:
        line(f"  ... and {len(rows) - 20} more unique versions")

    line(f"**Skills with version**: {has_ver} ({pct(has_ver, total)})")
    line(f"**Skills without version**: {without_ver} ({pct(without_ver, total)})")

    # Count major versions > 1.0
    gt_1 = 0
    for r in rows:
        try:
            v = r["version"]
            if v and v != "unknown":
                parts = v.replace("v", "").split(".")
                if int(parts[0]) > 1:
                    gt_1 += r["cnt"]
        except (ValueError, IndexError):
            pass
    line(f"**Versions > 1.x**: {gt_1} ({pct(gt_1, total)})")

    return {
        "version_counts": {r["version"]: r["cnt"] for r in rows},
        "has_version": has_ver,
        "without_version": without_ver,
        "gt_1": gt_1,
    }


# ─────────────────────────────────────────
# 5. Body length distribution
# ─────────────────────────────────────────
def audit_body_length(conn: sqlite3.Connection) -> dict:
    h("5. Body Length Distribution (skill_md_text)")

    rows = conn.execute("""
        SELECT LENGTH(skill_md_text) AS body_len
        FROM skills
        WHERE skill_md_text IS NOT NULL AND skill_md_text <> ''
        ORDER BY body_len
    """).fetchall()

    if not rows:
        line("(no body text)")
        return {}

    lengths = [r["body_len"] for r in rows]
    n = len(lengths)
    total_len = sum(lengths)

    # Decile buckets
    deciles = []
    for i in range(10):
        idx = int(n * i / 10)
        deciles.append(lengths[idx])
    deciles.append(lengths[-1])

    table_rows = []
    for i in range(10):
        lo = deciles[i]
        hi = deciles[i + 1]
        count = sum(1 for l in lengths if lo <= l <= hi)
        table_rows.append([
            f"P{i*10}–P{(i+1)*10}",
            f"{lo:,} – {hi:,}",
            str(count),
            pct(count, n),
        ])

    table(["Percentile", "Range (chars)", "Count", "%"], table_rows)

    stats = {
        "count": n,
        "min": lengths[0],
        "max": lengths[-1],
        "mean": int(total_len / n),
        "median": lengths[n // 2],
        "total_chars": total_len,
        "short_bodies": sum(1 for l in lengths if l < 200),
        "long_bodies": sum(1 for l in lengths if l > 2000),
    }

    line(f"**Count**: {n:,}")
    line(f"**Min / Median / Max**: {stats['min']:,} / {stats['median']:,} / {stats['max']:,}")
    line(f"**Mean**: {stats['mean']:,}")
    line(f"**< 200 chars (thin)**: {stats['short_bodies']} ({pct(stats['short_bodies'], n)})")
    line(f"**> 2,000 chars (rich)**: {stats['long_bodies']} ({pct(stats['long_bodies'], n)})")
    line(f"**Total chars**: {total_len:,}")

    return stats


# ─────────────────────────────────────────
# 6. Author concentration
# ─────────────────────────────────────────
def _gini(values: list[float]) -> float:
    """Compute Gini coefficient."""
    if not values or sum(values) == 0:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    cumsum = 0.0
    for i, v in enumerate(sorted_vals, 1):
        cumsum += i * v
    mean = sum(sorted_vals) / n
    return (2 * cumsum) / (n * sum(sorted_vals)) - (n + 1) / n


def audit_author_concentration(conn: sqlite3.Connection) -> dict:
    h("6. Author Concentration")

    rows = conn.execute("""
        SELECT author, COUNT(*) AS cnt
        FROM skills
        WHERE author IS NOT NULL AND author <> ''
        GROUP BY author
        ORDER BY cnt DESC
    """).fetchall()

    if not rows:
        line("(no author data)")
        return {}

    counts = [r["cnt"] for r in rows]
    gini = _gini(counts)
    total = sum(counts)
    n_authors = len(counts)

    # Top-N share
    for top_n in [5, 10, 20, 50]:
        share = sum(r["cnt"] for r in rows[:top_n])
        line(f"- **Top-{top_n} authors**: {share:,} skills ({pct(share, total)})")

    table_rows = []
    for r in rows[:20]:
        table_rows.append([
            r["author"],
            str(r["cnt"]),
            pct(r["cnt"], total),
        ])
    table(["Author", "Skills", "% of Total"], table_rows)

    line(f"**Total unique authors**: {n_authors}")
    line(f"**Total authored skills**: {total:,}")
    line(f"**Gini coefficient**: {gini:.4f}")

    return {
        "n_authors": n_authors,
        "total_authored": total,
        "gini": round(gini, 4),
        "top_authors": [{"author": r["author"], "count": r["cnt"]} for r in rows[:50]],
    }


# ─────────────────────────────────────────
# 7. Tag coverage
# ─────────────────────────────────────────
def audit_tags(conn: sqlite3.Connection) -> dict:
    h("7. Tag Coverage")

    rows = conn.execute("""
        SELECT identifier, tags_json
        FROM skills
        WHERE tags_json IS NOT NULL AND tags_json <> '[]'
    """).fetchall()

    total_skills = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]

    if not rows:
        line(f"(no tags — 0/{total_skills} skills have tags)")
        return {}

    freq: dict[str, int] = {}
    for r in rows:
        try:
            for t in json.loads(r["tags_json"] or "[]"):
                t = str(t).strip()
                if t:
                    freq[t] = freq.get(t, 0) + 1
        except json.JSONDecodeError:
            continue

    if not freq:
        line(f"0 unique tags across {len(rows)} skills with tags_json")
        return {}

    sorted_tags = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    n_with_tags = len(rows)
    n_unique_tags = len(sorted_tags)

    line(f"**Skills with >= 1 tag**: {n_with_tags} ({pct(n_with_tags, total_skills)})")
    line(f"**Unique tags**: {n_unique_tags}")
    line(f"**Most common tag**: '{sorted_tags[0][0]}' ({sorted_tags[0][1]} uses)")
    h("")

    table_rows = []
    for tag, cnt in sorted_tags[:30]:
        table_rows.append([tag, str(cnt), pct(cnt, n_with_tags)])
    table(["Tag", "Count", "% of Tagged Skills"], table_rows)

    if len(sorted_tags) > 30:
        line(f"  ... and {len(sorted_tags) - 30} more tags")

    return {
        "skills_with_tags": n_with_tags,
        "unique_tags": n_unique_tags,
        "top_tags": [{"tag": t, "count": c} for t, c in sorted_tags[:100]],
    }


# ─────────────────────────────────────────
# 8. Zip complexity
# ─────────────────────────────────────────
def audit_zip_complexity(conn: sqlite3.Connection) -> dict:
    h("8. Zip Complexity (entries per bundle)")

    rows = conn.execute("""
        SELECT identifier, n_entries, entries_json, zip_size
        FROM skills
        WHERE n_entries IS NOT NULL
        ORDER BY n_entries DESC
    """).fetchall()

    if not rows:
        line("(no zip data)")
        return {}

    n_entries = [r["n_entries"] for r in rows]
    total = len(n_entries)

    # Distribution
    dist = Counter(n_entries)

    table_rows = []
    for nf, cnt in sorted(dist.items()):
        table_rows.append([str(nf), str(cnt), pct(cnt, total)])

    table(["Files in Zip", "Count", "%"], table_rows)

    # Stats
    line(f"**Total zips**: {total:,}")
    line(f"**Min / Median / Max files**: {min(n_entries)} / {sorted(n_entries)[total//2]} / {max(n_entries)}")
    line(f"**Single-file zips**: {dist.get(1, 0)} ({pct(dist.get(1, 0), total)})")

    # Show biggest zips
    biggest = sorted(rows, key=lambda r: -r["zip_size"])[:5]
    line("")
    line("**Largest zips by size**:")
    for r in biggest:
        size_kb = r["zip_size"] // 1024 if r["zip_size"] else 0
        line(f"- `{r['identifier']}` — {size_kb:,} KB, {r['n_entries']} files")

    return {
        "total_zips": total,
        "min_files": min(n_entries),
        "median_files": sorted(n_entries)[total // 2],
        "max_files": max(n_entries),
        "single_file_zips": dist.get(1, 0),
        "distribution": {str(k): v for k, v in dist.items()},
    }


# ─────────────────────────────────────────
# 9. Recover raw data from manifests
# ─────────────────────────────────────────
def audit_manifest_raw(conn: sqlite3.Connection) -> dict:
    h("9. Raw Data Recovery from Manifests")

    manifests = sorted(DOWNLOADS_DIR.glob("*.manifest.json"))
    if not manifests:
        line("(no manifest files found)")
        return {}

    n_manifests = len(manifests)
    has_raw = 0
    extra_fields: Counter = Counter()
    sample_raw_keys = None

    for mf_path in manifests:
        try:
            mf = json.loads(mf_path.read_text(encoding="utf-8"))
            raw = mf.get("raw")
            if isinstance(raw, dict) and raw:
                has_raw += 1
                for k in raw:
                    extra_fields[k] += 1
                if sample_raw_keys is None:
                    sample_raw_keys = list(raw.keys())
        except Exception:
            pass

    line(f"**Total manifest files**: {n_manifests}")
    line(f"**Manifests with 'raw' field**: {has_raw} ({pct(has_raw, n_manifests)})")
    h("")

    if sample_raw_keys:
        line("**Fields in raw data**:")
        for k, v in extra_fields.most_common():
            line(f"- `{k}`: present in {v} manifests ({pct(v, has_raw)})")
    h("")

    # Check db skills count vs manifest count
    db_count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    db_sha = conn.execute("SELECT COUNT(*) FROM skills WHERE sha256 IS NOT NULL").fetchone()[0]

    line(f"**DB skills with sha256**: {db_sha} / {db_count} ({pct(db_sha, db_count)})")
    line("*(raw data is already stored in manifest.json files; the `raw` key preserves the full API response)*")

    return {
        "n_manifests": n_manifests,
        "has_raw": has_raw,
        "raw_fields": {k: v for k, v in extra_fields.most_common()},
        "db_sha_coverage": db_sha,
    }


# ─────────────────────────────────────────
# 10. Note / usage coverage
# ─────────────────────────────────────────
def audit_note_usage(conn: sqlite3.Connection) -> dict:
    h("10. Note ID and Usage Coverage")

    total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    with_notes = conn.execute(
        "SELECT COUNT(DISTINCT skill_identifier) FROM skill_notes"
    ).fetchone()[0]
    with_usage = conn.execute(
        "SELECT COUNT(*) FROM skill_usage WHERE usage_count IS NOT NULL"
    ).fetchone()[0]

    line(f"**Skills with note mapping**: {with_notes} / {total} ({pct(with_notes, total)})")
    line(f"**Skills with usage data**: {with_usage} / {total} ({pct(with_usage, total)})")
    h("")

    # By source
    source_rows = conn.execute(
        "SELECT source, COUNT(*) AS cnt FROM skill_notes GROUP BY source ORDER BY cnt DESC"
    ).fetchall()
    if source_rows:
        h("Mapping sources")
        table_rows = [[r["source"], str(r["cnt"]), pct(r["cnt"], with_notes)] for r in source_rows]
        table(["Source", "Count", "% of Mapped"], table_rows)

    # Top by note count
    top_notes = conn.execute("""
        SELECT s.identifier, s.name, COUNT(sn.note_id) AS note_count
        FROM skills s
        JOIN skill_notes sn ON sn.skill_identifier = s.identifier
        GROUP BY s.identifier
        ORDER BY note_count DESC, s.identifier
        LIMIT 20
    """).fetchall()
    if top_notes:
        h("Top skills by note count")
        table(["Identifier", "Name", "Notes"], [
            [r["identifier"][:50], r["name"][:40] or "(unnamed)", str(r["note_count"])]
            for r in top_notes
        ])

    # Top by usage count
    top_usage = conn.execute("""
        SELECT s.identifier, s.name, su.usage_count
        FROM skills s
        JOIN skill_usage su ON su.skill_identifier = s.identifier
        WHERE su.usage_count IS NOT NULL
        ORDER BY su.usage_count DESC, s.identifier
        LIMIT 20
    """).fetchall()
    if top_usage:
        h("Top skills by usage count")
        table(["Identifier", "Name", "Usage"], [
            [r["identifier"][:50], r["name"][:40] or "(unnamed)", str(r["usage_count"])]
            for r in top_usage
        ])

    # Unmapped
    unmapped = conn.execute("""
        SELECT identifier, name
        FROM skills
        WHERE identifier NOT IN (SELECT DISTINCT skill_identifier FROM skill_notes)
        ORDER BY identifier
        LIMIT 100
    """).fetchall()
    h("Unmapped skills (no note_id)")
    line(f"**Count**: {len(unmapped)} shown (limit 100)")
    if unmapped:
        table(["Identifier", "Name"], [
            [r["identifier"][:60], (r["name"] or "(unnamed)")[:50]]
            for r in unmapped
        ])

    return {
        "total": total,
        "with_notes": with_notes,
        "with_usage": with_usage,
        "source_counts": {r["source"]: r["cnt"] for r in source_rows},
        "top_note_count": [{"identifier": r["identifier"], "name": r["name"], "count": r["note_count"]} for r in top_notes],
        "top_usage_count": [{"identifier": r["identifier"], "name": r["name"], "usage": r["usage_count"]} for r in top_usage],
        "unmapped_count": len(unmapped),
    }

def audit_summary(all_results: dict) -> None:
    h("Summary", level=1)
    h("")

    items = []

    # Field coverage summary
    fc = all_results.get("field_coverage", {})
    total = fc.pop("_total", 3630)
    worst = sorted(fc.items(), key=lambda kv: kv[1]["pct"])
    items.append(f"- **Total skills**: {total:,}")
    items.append(f"- **Lowest coverage fields**: {worst[0][0]} ({worst[0][1]['pct']}%), "
                  f"{worst[1][0]} ({worst[1][1]['pct']}%), "
                  f"{worst[2][0]} ({worst[2][1]['pct']}%)")

    # Duplicates
    nd = all_results.get("name_dupes", {})
    items.append(f"- **Name duplicates**: {nd.get('total_duped', 0)} skills share names with others")

    # Near dupes
    ndp = all_results.get("content_near_dupes", {})
    items.append(f"- **Near-duplicate pairs (>=90% Jaccard)**: {len(ndp.get('near_dupes', []))}")

    # Authors
    ac = all_results.get("author_concentration", {})
    items.append(f"- **Author Gini**: {ac.get('gini', 'N/A')}")

    # Versions
    vd = all_results.get("versions", {})
    items.append(f"- **Skills with version > 1.x**: {vd.get('gt_1', 0)}")

    # Body
    bl = all_results.get("body_length", {})
    items.append(f"- **Thin bodies (<200 chars)**: {bl.get('short_bodies', 0)}")
    items.append(f"- **Rich bodies (>2000 chars)**: {bl.get('long_bodies', 0)}")

    # Tags
    tc = all_results.get("tag_coverage", {})
    items.append(f"- **Skills with tags**: {tc.get('skills_with_tags', 0)} ({tc.get('unique_tags', 0)} unique tags)")

    # Note / usage
    nu = all_results.get("note_usage", {})
    items.append(f"- **Skills with note mapping**: {nu.get('with_notes', 0)} / {nu.get('total', 0)}")
    items.append(f"- **Skills with usage data**: {nu.get('with_usage', 0)} / {nu.get('total', 0)}")

    # Zip
    zc = all_results.get("zip_complexity", {})
    items.append(f"- **Single-file zips**: {zc.get('single_file_zips', 0)} / {zc.get('total_zips', 0)}")

    for item in items:
        line(item)
    REPORT.append("")


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="RedSkill data quality audit")
    p.add_argument("--json", action="store_true", help="also write data/audit.json")
    args = p.parse_args(argv)

    conn = connect()

    h("# RedSkill Data Quality Audit Report", level=1)
    line(f"*(generated from {DB_PATH})*")
    REPORT.append("")

    all_results = {}

    # Run all audits
    all_results["field_coverage"] = audit_field_coverage(conn)
    all_results["name_dupes"] = audit_name_duplicates(conn)
    all_results["content_near_dupes"] = audit_content_near_dupes(conn)
    all_results["versions"] = audit_versions(conn)
    all_results["body_length"] = audit_body_length(conn)
    all_results["author_concentration"] = audit_author_concentration(conn)
    all_results["tag_coverage"] = audit_tags(conn)
    all_results["zip_complexity"] = audit_zip_complexity(conn)
    all_results["manifest_raw"] = audit_manifest_raw(conn)
    all_results["note_usage"] = audit_note_usage(conn)

    # Summary
    audit_summary(all_results)

    # Write report
    report_text = "\n".join(REPORT)
    OUTPUT_MD.write_text(report_text, encoding="utf-8")
    print(f"audit report -> {OUTPUT_MD}")

    if args.json:
        OUTPUT_JSON.write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"audit json  -> {OUTPUT_JSON}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
