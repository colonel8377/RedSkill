"""clickbait.py — title-bait detection heuristics.

Heuristic scoring (no API needed):
- Emotional words: 爆款/震惊/必看/绝了/一键/秒变/神器
- Numbers in titles: "3步", "5分钟", "10个"
- Superlatives: 最好/最强/全网/首发
- Title-to-body ratio: long title (>30 chars) + short body (<200 chars) = suspect
- Template placeholders: body contains [填入], {替换}
- Thin wrapper: body < 200 chars, no structured paragraphs
"""
from __future__ import annotations

import re
import sqlite3
import csv
from pathlib import Path

from src.core.config import DB_PATH, ROOT

OUT_DIR = ROOT / "data"

# Emotional/sensational words
EMOTION_WORDS = [
    "爆款", "震惊", "必看", "绝了", "一键", "秒变", "神器",
    "全网首发", "独家", "揭秘", "颠覆", "炸裂", "神级",
    "天花板", "封神", "绝绝子", "yyds", "救命",
    "一键生成", "秒杀", "彻底改变", "革命性",
]

# Number patterns
NUMBER_PATTERNS = [
    re.compile(r"\d+步"),
    re.compile(r"\d+分钟"),
    re.compile(r"\d+个"),
    re.compile(r"\d+天"),
    re.compile(r"\d+倍"),
    re.compile(r"\d+招"),
    re.compile(r"\d+款"),
]

# Superlative words
SUPERLATIVES = [
    "最好", "最强", "全网", "首发", "第一", "顶级",
    "最全", "最新", "首发", "独家首发",
]

# Template placeholder patterns
TEMPLATE_RE = re.compile(r"\[填入\]|\[填写\]|\[.*?\]|\{替换\}|\{.*?\}|<.*?>")


def _score_emotional(title: str) -> float:
    """Count emotional words in title."""
    score = 0.0
    for word in EMOTION_WORDS:
        if word in title:
            score += 1.0
    return min(score / 3.0, 1.0)  # cap at 1.0


def _score_numbers(title: str) -> float:
    """Check for number patterns."""
    score = 0.0
    for pat in NUMBER_PATTERNS:
        if pat.search(title):
            score += 0.5
    return min(score, 1.0)


def _score_superlatives(title: str) -> float:
    """Count superlatives."""
    score = 0.0
    for word in SUPERLATIVES:
        if word in title:
            score += 1.0
    return min(score / 2.0, 1.0)


def _score_title_body_ratio(name: str, body: str) -> float:
    """Long title + short body = clickbait signal."""
    if len(name) > 30 and len(body) < 200:
        return 1.0
    if len(name) > 25 and len(body) < 400:
        return 0.5
    if len(name) > 20 and len(body) < 100:
        return 1.0
    return 0.0


def _score_template_placeholders(body: str) -> float:
    """Detect template-style content."""
    matches = len(TEMPLATE_RE.findall(body))
    if matches > 5:
        return 1.0
    if matches > 2:
        return 0.5
    return 0.0


def _score_thin_wrapper(body: str) -> float:
    """Very short body with no structure."""
    if len(body) < 100:
        return 1.0
    if len(body) < 200 and "##" not in body:
        return 0.7
    if len(body) < 300 and "##" not in body and "```" not in body:
        return 0.4
    return 0.0


def compute_clickbait_scores() -> list[dict]:
    """Compute clickbait scores for all skills and save to CSV.

    Returns list of score dicts.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT identifier, name, description, skill_md_text
        FROM skills
        WHERE name IS NOT NULL AND name <> ''
    """).fetchall()
    conn.close()

    print(f"Computing clickbait scores for {len(rows)} skills...")

    results = []
    for r in rows:
        title = r["name"] or ""
        body = r["skill_md_text"] or ""
        desc = r["description"] or ""

        # Combine description into "title" for broader analysis
        combined_title = f"{title} {desc}"

        scores = {
            "identifier": r["identifier"],
            "name": title,
            "body_len": len(body),
            "title_len": len(title),
            "emotional": round(_score_emotional(combined_title), 3),
            "numbers": round(_score_numbers(combined_title), 3),
            "superlatives": round(_score_superlatives(combined_title), 3),
            "title_body_ratio": round(_score_title_body_ratio(title, body), 3),
            "template_placeholder": round(_score_template_placeholders(body), 3),
            "thin_wrapper": round(_score_thin_wrapper(body), 3),
        }
        # Composite score (weighted average)
        weights = {
            "emotional": 0.20,
            "numbers": 0.15,
            "superlatives": 0.15,
            "title_body_ratio": 0.20,
            "template_placeholder": 0.15,
            "thin_wrapper": 0.15,
        }
        composite = sum(scores[k] * weights[k] for k in weights)
        scores["composite"] = round(composite, 3)
        results.append(scores)

    results.sort(key=lambda x: -x["composite"])

    # Save
    out_path = OUT_DIR / "clickbait_scores.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"  Saved -> {out_path}")

    # Summary stats
    composites = [r["composite"] for r in results]
    print(f"\n  Clickbait Score Distribution:")
    print(f"    Mean:   {sum(composites)/len(composites):.3f}")
    print(f"    Median: {sorted(composites)[len(composites)//2]:.3f}")
    print(f"    Max:    {max(composites):.3f}")
    print(f"    >= 0.5: {sum(1 for c in composites if c >= 0.5)} ({sum(1 for c in composites if c >= 0.5)/len(composites)*100:.1f}%)")
    print(f"    >= 0.7: {sum(1 for c in composites if c >= 0.7)} ({sum(1 for c in composites if c >= 0.7)/len(composites)*100:.1f}%)")

    # Top clickbait offenders
    print(f"\n  Top-10 Clickbait Scores:")
    for r in results[:10]:
        print(f"    [{r['identifier']}] {r['name'][:60]}: {r['composite']:.3f}")

    return results


if __name__ == "__main__":
    compute_clickbait_scores()
