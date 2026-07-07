"""statistics.py — statistical tests for research findings.

Tests:
- Mann-Whitney U (distribution differences between groups)
- Cliff's delta (effect size)
- Bootstrap confidence intervals
- Spearman rank correlation

Used to compare: clickbait vs robustness, author groups, etc.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats as scipy_stats

from src.core.config import ROOT

OUT_DIR = ROOT / "data"


def bootstrap_ci(
    data: np.ndarray,
    statistic: callable = np.mean,
    n_bootstrap: int = 10_000,
    ci: float = 0.95,
    random_seed: int = 42,
) -> tuple[float, float, float]:
    """Bootstrap confidence interval for a statistic.

    Returns (lower_bound, estimate, upper_bound).
    """
    rng = np.random.default_rng(random_seed)
    estimates = []
    for _ in range(n_bootstrap):
        sample = rng.choice(data, size=len(data), replace=True)
        estimates.append(statistic(sample))
    estimate = statistic(data)
    alpha = (1 - ci) / 2
    lower = np.percentile(estimates, alpha * 100)
    upper = np.percentile(estimates, (1 - alpha) * 100)
    return lower, estimate, upper


def cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    """Cliff's delta effect size for two independent samples.

    Returns value in [-1, 1]. Interpretation:
    - |d| < 0.147: negligible
    - |d| < 0.33: small
    - |d| < 0.474: medium
    - |d| >= 0.474: large
    """
    n_x, n_y = len(x), len(y)
    if n_x == 0 or n_y == 0:
        return 0.0
    dominance = 0
    for xi in x:
        for yj in y:
            if xi > yj:
                dominance += 1
            elif xi < yj:
                dominance -= 1
    return dominance / (n_x * n_y)


def compare_groups(
    group_a: np.ndarray,
    group_b: np.ndarray,
    label_a: str = "Group A",
    label_b: str = "Group B",
) -> dict:
    """Run full statistical comparison between two groups.

    Returns dict with Mann-Whitney U, Cliff's delta, bootstrap CIs.
    """
    # Mann-Whitney U
    u_stat, p_value = scipy_stats.mannwhitneyu(group_a, group_b, alternative="two-sided")

    # Cliff's delta
    delta = cliffs_delta(group_a, group_b)

    # Bootstrap CIs for means
    ci_a = bootstrap_ci(group_a)
    ci_b = bootstrap_ci(group_b)

    # Bootstrap CI for the difference
    rng = np.random.default_rng(42)
    diffs = []
    for _ in range(10_000):
        sa = rng.choice(group_a, size=len(group_a), replace=True)
        sb = rng.choice(group_b, size=len(group_b), replace=True)
        diffs.append(np.mean(sa) - np.mean(sb))
    diff_lower = np.percentile(diffs, 2.5)
    diff_upper = np.percentile(diffs, 97.5)

    result = {
        "label_a": label_a,
        "label_b": label_b,
        "n_a": len(group_a),
        "n_b": len(group_b),
        "mean_a": float(np.mean(group_a)),
        "mean_b": float(np.mean(group_b)),
        "median_a": float(np.median(group_a)),
        "median_b": float(np.median(group_b)),
        "mann_whitney_u": float(u_stat),
        "p_value": float(p_value),
        "significant": p_value < 0.05,
        "cliffs_delta": float(delta),
        "delta_magnitude": (
            "negligible" if abs(delta) < 0.147
            else "small" if abs(delta) < 0.33
            else "medium" if abs(delta) < 0.474
            else "large"
        ),
        "ci_a_95": [float(ci_a[0]), float(ci_a[2])],
        "ci_b_95": [float(ci_b[0]), float(ci_b[2])],
        "ci_diff_95": [float(diff_lower), float(diff_upper)],
    }

    print(f"\n=== {label_a} vs {label_b} ===")
    print(f"  n:  {result['n_a']} vs {result['n_b']}")
    print(f"  mean: {result['mean_a']:.4f} vs {result['mean_b']:.4f}")
    print(f"  median: {result['median_a']:.4f} vs {result['median_b']:.4f}")
    print(f"  Mann-Whitney U: {result['mann_whitney_u']:.1f}, p={result['p_value']:.6f} {'*' if result['significant'] else 'ns'}")
    print(f"  Cliff's delta: {result['cliffs_delta']:.4f} ({result['delta_magnitude']})")
    print(f"  CI(A): [{result['ci_a_95'][0]:.4f}, {result['ci_a_95'][1]:.4f}]")
    print(f"  CI(B): [{result['ci_b_95'][0]:.4f}, {result['ci_b_95'][1]:.4f}]")
    print(f"  CI(diff): [{result['ci_diff_95'][0]:.4f}, {result['ci_diff_95'][1]:.4f}]")

    return result


def load_scores(path: Path) -> dict[str, float]:
    """Load composite scores from a CSV file. Returns {identifier: score}."""
    scores = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            scores[row["identifier"]] = float(row["composite"])
    return scores


def run_all_tests() -> list[dict]:
    """Run all statistical tests on available data.

    Compares:
    1. Clickbait scores: thin (<200 chars) vs rich (>2000 chars) bodies
    2. Clickbait scores: emotional title vs non-emotional
    3. Robustness: single-file vs multi-file zips
    4. Clickbait vs robustness correlation (Spearman)
    """
    results = []

    # Load data
    clickbait_path = OUT_DIR / "clickbait_scores.csv"
    robustness_path = OUT_DIR / "robustness_scores.csv"

    if not clickbait_path.exists():
        print(f"Run clickbait.py first (missing {clickbait_path})")
        return results
    if not robustness_path.exists():
        print(f"Run robustness.py first (missing {robustness_path})")
        return results

    # Load full records with details
    cb_records = {}
    with open(clickbait_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cb_records[row["identifier"]] = row

    rb_records = {}
    with open(robustness_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rb_records[row["identifier"]] = row

    # 1. Clickbait: thin vs rich bodies
    thin = []
    rich = []
    for ident, rec in cb_records.items():
        body_len = int(rec.get("body_len", 0))
        if body_len < 200:
            thin.append(float(rec["composite"]))
        elif body_len > 2000:
            rich.append(float(rec["composite"]))

    if thin and rich:
        results.append(compare_groups(
            np.array(thin), np.array(rich),
            "Clickbait (thin body <200ch)", "Clickbait (rich body >2000ch)",
        ))

    # 2. Clickbait: high emotional vs no emotional
    high_emo = []
    no_emo = []
    for ident, rec in cb_records.items():
        emo = float(rec.get("emotional", 0))
        if emo >= 0.5:
            high_emo.append(float(rec["composite"]))
        elif emo == 0:
            no_emo.append(float(rec["composite"]))

    if high_emo and no_emo:
        results.append(compare_groups(
            np.array(high_emo), np.array(no_emo),
            "Clickbait (emotional title)", "Clickbait (neutral title)",
        ))

    # 3. Robustness: single-file vs multi-file
    single = []
    multi = []
    for ident, rec in rb_records.items():
        n_entries = int(rec.get("n_entries", 1))
        if n_entries == 1:
            single.append(float(rec["composite"]))
        elif n_entries > 5:
            multi.append(float(rec["composite"]))

    if single and multi:
        results.append(compare_groups(
            np.array(single), np.array(multi),
            "Robustness (single file)", "Robustness (multi-file >5)",
        ))

    # 4. Spearman correlation: clickbait vs robustness
    common_idents = set(cb_records.keys()) & set(rb_records.keys())
    cb_vals = [float(cb_records[i]["composite"]) for i in common_idents]
    rb_vals = [float(rb_records[i]["composite"]) for i in common_idents]

    if cb_vals and rb_vals:
        rho, p_val = scipy_stats.spearmanr(cb_vals, rb_vals)
        print(f"\n=== Spearman: Clickbait vs Robustness ===")
        print(f"  n: {len(common_idents)}")
        print(f"  rho: {rho:.4f}")
        print(f"  p: {p_val:.6f} {'*' if p_val < 0.05 else 'ns'}")
        print(f"  Interpretation: {'significant negative correlation' if rho < -0.3 and p_val < 0.05 else 'weak/no correlation'}")

    return results


if __name__ == "__main__":
    run_all_tests()
