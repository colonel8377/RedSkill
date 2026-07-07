"""charts.py — generate publication-quality PDF charts at 300 DPI.

All charts are styled with a unified mplstyle and output to data/charts/.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import seaborn as sns

from src.core.config import DB_PATH, ROOT

OUT_DIR = ROOT / "data" / "charts"
DPI = 300

# Unified style
plt.rcParams.update({
    "figure.dpi": DPI,
    "savefig.dpi": DPI,
    "font.size": 10,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "figure.titlesize": 14,
    "font.family": "sans-serif",
    "font.sans-serif": ["Heiti SC", "PingFang SC", "Hiragino Sans GB", "Arial Unicode MS", "DejaVu Sans"],
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.unicode_minus": False,
})


def _savefig(name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.pdf"
    plt.tight_layout()
    plt.savefig(path, dpi=DPI, bbox_inches="tight")
    print(f"  -> {path}")
    plt.close()
    return path


# ─────────────────────────────────────────
# Chart 1: Field coverage bar chart
# ─────────────────────────────────────────
def chart_field_coverage() -> Path:
    """Horizontal bar chart of field fill rates (from audit_results)."""
    audit_path = ROOT / "data" / "audit.json"
    if not audit_path.exists():
        print("Skipping field_coverage: run python -m src.audit --json first")
        return Path()

    with open(audit_path) as f:
        audit = json.load(f)

    fc = audit.get("field_coverage", {})
    if "_total" in fc:
        del fc["_total"]

    fields = sorted(fc.keys(), key=lambda k: fc[k]["pct"])
    values = [fc[f]["pct"] for f in fields]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.barh(fields, values, color="#4472C4")
    ax.set_xlabel("Fill Rate (%)")
    ax.set_title("Field Coverage in skills.db")
    ax.set_xlim(0, 105)
    for bar, v in zip(bars, values):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{v:.1f}%", va="center", fontsize=8)
    return _savefig("01_field_coverage")


# ─────────────────────────────────────────
# Chart 2: Name duplicates Top-20
# ─────────────────────────────────────────
def chart_name_duplicates() -> Path:
    """Horizontal bar chart of top-20 repeated skill names."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT name, COUNT(*) AS cnt
        FROM skills
        WHERE name IS NOT NULL AND name <> ''
        GROUP BY name HAVING cnt > 1
        ORDER BY cnt DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    if not rows:
        return Path()

    names = [r[0][:30] for r in rows]
    counts = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(range(len(names)), counts, color="#ED7D31")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("Duplicate Count")
    ax.set_title("Top-20 Repeated Skill Names")
    ax.invert_yaxis()
    for i, (bar, c) in enumerate(zip(bars, counts)):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                str(c), va="center", fontsize=8)
    return _savefig("02_name_duplicates")


# ─────────────────────────────────────────
# Chart 3: Body length distribution histogram
# ─────────────────────────────────────────
def chart_body_length() -> Path:
    """Histogram of skill_md_text body lengths (log scale)."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT LENGTH(skill_md_text) AS body_len
        FROM skills
        WHERE skill_md_text IS NOT NULL AND skill_md_text <> ''
    """).fetchall()
    conn.close()

    lengths = [r[0] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(lengths, bins=60, color="#4472C4", edgecolor="white", alpha=0.85)
    ax.set_xscale("log")
    ax.set_xlabel("Body Length (chars, log scale)")
    ax.set_ylabel("Count")
    ax.set_title(f"SKILL.md Body Length Distribution (n={len(lengths):,})")
    ax.axvline(x=200, color="#ED7D31", linestyle="--", alpha=0.7, label="Thin (<200ch)")
    ax.axvline(x=2000, color="#70AD47", linestyle="--", alpha=0.7, label="Rich (>2000ch)")
    ax.legend(fontsize=9)
    return _savefig("03_body_length_hist")


# ─────────────────────────────────────────
# Chart 4: Author concentration Lorenz curve
# ─────────────────────────────────────────
def chart_author_concentration() -> Path:
    """Lorenz curve showing author concentration (Gini)."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT author, COUNT(*) AS cnt
        FROM skills WHERE author IS NOT NULL AND author <> ''
        GROUP BY author ORDER BY cnt ASC
    """).fetchall()
    conn.close()

    if not rows:
        return Path()

    counts = [r[1] for r in rows]
    n = len(counts)
    cumsum = np.cumsum(counts)
    total = cumsum[-1]

    lorenz_x = np.linspace(0, 1, n)
    lorenz_y = np.concatenate([[0], cumsum / total])

    # Gini
    sorted_vals = sorted(counts)
    mean = sum(sorted_vals) / n
    gini = (2 * sum((i+1)*v for i, v in enumerate(sorted_vals))) / (n * sum(sorted_vals)) - (n+1)/n

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot([0] + list(lorenz_x), lorenz_y, color="#4472C4", linewidth=2, label=f"Author concentration (Gini={gini:.3f})")
    ax.plot([0, 1], [0, 1], color="gray", linestyle="--", alpha=0.6, label="Perfect equality")
    ax.fill_between([0] + list(lorenz_x), lorenz_y, [0] + list(lorenz_x), alpha=0.15, color="#4472C4")
    ax.set_xlabel("Cumulative share of authors")
    ax.set_ylabel("Cumulative share of skills")
    ax.set_title("Author Concentration (Lorenz Curve)")
    ax.legend(fontsize=9)
    return _savefig("04_author_lorenz")


# ─────────────────────────────────────────
# Chart 5: Clickbait vs body length scatter
# ─────────────────────────────────────────
def chart_clickbait_scatter() -> Path:
    """Scatter plot: clickbait composite vs body length."""
    cb_path = ROOT / "data" / "clickbait_scores.csv"
    if not cb_path.exists():
        print("Skipping clickbait_scatter: run python -m src.analyze.clickbait first")
        return Path()

    body_lens = []
    scores = []
    with open(cb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bl = int(row["body_len"])
            if bl > 0:
                body_lens.append(min(bl, 50000))  # cap extreme values
                scores.append(float(row["composite"]))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(body_lens, scores, alpha=0.15, s=4, color="#4472C4")
    ax.set_xscale("log")
    ax.set_xlabel("Body Length (chars, log scale)")
    ax.set_ylabel("Clickbait Score")
    ax.set_title(f"Clickbait Score vs Body Length (n={len(scores):,})")
    # Add trend line
    if len(scores) > 1:
        z = np.polyfit(np.log10(body_lens), scores, 1)
        p = np.poly1d(z)
        xs = np.logspace(0, 5, 100)
        ax.plot(xs, p(np.log10(xs)), color="#ED7D31", linewidth=1.5, alpha=0.7)
    return _savefig("05_clickbait_vs_body")


# ─────────────────────────────────────────
# Chart 6: Robustness score boxplot by file count
# ─────────────────────────────────────────
def chart_robustness_boxplot() -> Path:
    """Box plot of robustness composite scores grouped by zip file count."""
    rb_path = ROOT / "data" / "robustness_scores.csv"
    if not rb_path.exists():
        print("Skipping robustness_boxplot: run python -m src.analyze.robustness first")
        return Path()

    groups = {"1": [], "2-3": [], "4-6": [], "7-10": [], "11+": []}
    with open(rb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            n = int(row["n_entries"])
            s = float(row["composite"])
            if n == 1:
                groups["1"].append(s)
            elif n <= 3:
                groups["2-3"].append(s)
            elif n <= 6:
                groups["4-6"].append(s)
            elif n <= 10:
                groups["7-10"].append(s)
            else:
                groups["11+"].append(s)

    data = [groups[k] for k in ("1", "2-3", "4-6", "7-10", "11+")]
    labels = list(groups.keys())

    fig, ax = plt.subplots(figsize=(8, 5))
    bp = ax.boxplot(data, patch_artist=True,
                    medianprops={"color": "#ED7D31", "linewidth": 1.5})
    ax.set_xticklabels(labels)
    for patch in bp["boxes"]:
        patch.set_facecolor("#4472C4")
        patch.set_alpha(0.6)
    ax.set_xlabel("Files in Zip")
    ax.set_ylabel("Robustness Score")
    ax.set_title("Robustness Score by Zip Complexity")

    # Add n labels
    for i, (label, d) in enumerate(zip(labels, data)):
        ax.text(i + 1, ax.get_ylim()[1], f"n={len(d)}", ha="center", fontsize=8, va="bottom")

    return _savefig("06_robustness_boxplot")


# ─────────────────────────────────────────
# Chart 7: Similarity cluster sizes (from MinHash components)
# ─────────────────────────────────────────
def chart_similarity_clusters() -> Path:
    """Bar chart of duplication component sizes."""
    pairs_path = ROOT / "data" / "similarity_pairs.csv"
    if not pairs_path.exists():
        print("Skipping similarity_clusters: run phase1_minhash_filter() first")
        return Path()

    # Build components (same as duplication.py logic)
    from collections import defaultdict

    adj: dict[str, set[str]] = defaultdict(set)
    with open(pairs_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            adj[row["ident1"]].add(row["ident2"])
            adj[row["ident2"]].add(row["ident1"])

    visited = set()
    components = []
    for ident in adj:
        if ident in visited:
            continue
        comp = []
        stack = [ident]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            comp.append(node)
            for neighbor in adj[node]:
                if neighbor not in visited:
                    stack.append(neighbor)
        if len(comp) >= 2:
            components.append(len(comp))

    if not components:
        print("No duplication components to plot")
        return Path()

    sizes = Counter(components)
    size_bins = sorted(sizes.keys())
    counts = [sizes[s] for s in size_bins]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(range(len(size_bins)), counts, color="#4472C4", alpha=0.85)
    ax.set_xticks(range(len(size_bins)))
    ax.set_xticklabels([str(s) for s in size_bins], fontsize=7, rotation=45)
    ax.set_xlabel("Component Size (skills per duplication cluster)")
    ax.set_ylabel("Number of Clusters")
    ax.set_title(f"Duplication Component Size Distribution ({len(components)} clusters, {sum(components)} skills)")

    return _savefig("07_similarity_clusters")


# ─────────────────────────────────────────
# Chart 8: Version distribution pie/donut
# ─────────────────────────────────────────
def chart_version_distribution() -> Path:
    """Donut chart: 1.0.0 vs 1.0.x vs 1.x vs 2.x+."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT version, COUNT(*) AS cnt
        FROM skills WHERE version IS NOT NULL AND version <> ''
        GROUP BY version
    """).fetchall()
    conn.close()

    cat_counts = {"1.0.0": 0, "1.0.x (patch)": 0, "1.x (minor)": 0, "2.x+": 0, "other": 0}
    version_counts = {r[0]: r[1] for r in rows}

    for v, cnt in version_counts.items():
        try:
            v_clean = v.replace("v", "")
            parts = v_clean.split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0

            if major > 1:
                cat_counts["2.x+"] += cnt
            elif major == 1 and minor == 0 and patch == 0:
                cat_counts["1.0.0"] += cnt
            elif major == 1 and minor == 0:
                cat_counts["1.0.x (patch)"] += cnt
            elif major == 1:
                cat_counts["1.x (minor)"] += cnt
            else:
                cat_counts["other"] += cnt
        except (ValueError, IndexError):
            cat_counts["other"] += cnt

    labels = list(cat_counts.keys())
    sizes = list(cat_counts.values())
    colors = ["#4472C4", "#70AD47", "#ED7D31", "#FFC000", "#A5A5A5"]

    fig, ax = plt.subplots(figsize=(7, 7))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, autopct="%1.1f%%", colors=colors,
        startangle=90, pctdistance=0.75,
    )
    ax.legend(wedges, [f"{l} ({s:,})" for l, s in zip(labels, sizes)],
              title="Version Categories", loc="center left", bbox_to_anchor=(1, 0.5))
    ax.set_title(f"Version Distribution (n={sum(sizes):,})")
    return _savefig("08_version_distribution")


# ─────────────────────────────────────────
# Generate all
# ─────────────────────────────────────────
def generate_all() -> list[Path]:
    """Run all chart functions and return list of output paths."""
    print("Generating charts...")
    paths = []
    paths.append(chart_field_coverage())
    paths.append(chart_name_duplicates())
    paths.append(chart_body_length())
    paths.append(chart_author_concentration())
    paths.append(chart_clickbait_scatter())
    paths.append(chart_robustness_boxplot())
    paths.append(chart_similarity_clusters())
    paths.append(chart_version_distribution())
    valid = [p for p in paths if p]
    print(f"\nGenerated {len(valid)} charts in {OUT_DIR}/")
    return valid


if __name__ == "__main__":
    generate_all()
