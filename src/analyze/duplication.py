"""duplication.py — duplication metrics and analysis.

Answers: what percentage of skills are "near-duplicates"?
Who are the top copycat authors?
"""
from __future__ import annotations

import csv
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from src.core.config import DB_PATH, ROOT

OUT_DIR = ROOT / "data"


def analyze_duplication(similarity_csv: Path | None = None) -> dict:
    """Analyze duplication patterns from similarity pairs.

    Reads data/similarity_pairs.csv (from similarity.py Phase 1).
    """
    if similarity_csv is None:
        similarity_csv = OUT_DIR / "similarity_pairs.csv"

    if not similarity_csv.exists():
        print(f"similarity_pairs.csv not found at {similarity_csv}")
        print("Run phase1_minhash_filter() first.")
        return {}

    # Read pairs
    pairs = []
    with open(similarity_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pairs.append(row)

    print(f"Analyzing {len(pairs)} near-duplicate pairs...")

    # Build adjacency: each identifier -> set of similar identifiers
    adj: dict[str, set[str]] = defaultdict(set)
    for p in pairs:
        adj[p["ident1"]].add(p["ident2"])
        adj[p["ident2"]].add(p["ident1"])

    # Connected components (transitive closure of similarity)
    visited = set()
    components = []
    for ident in adj:
        if ident in visited:
            continue
        # BFS
        component = []
        stack = [ident]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            for neighbor in adj[node]:
                if neighbor not in visited:
                    stack.append(neighbor)
        if len(component) >= 2:
            components.append(component)

    components.sort(key=len, reverse=True)

    # Get author info from DB
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    id_to_author = {}
    for row in conn.execute("SELECT identifier, author FROM skills WHERE author IS NOT NULL AND author <> ''"):
        id_to_author[row["identifier"]] = row["author"]
    total_skills = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    conn.close()

    # Skills involved in duplication
    duped_skills = set()
    for c in components:
        duped_skills.update(c)

    # Author analysis for components
    author_component_count: Counter = Counter()
    for c in components:
        authors_in_c = [id_to_author.get(ident, "unknown") for ident in c]
        unique_authors = set(authors_in_c)
        for a in unique_authors:
            author_component_count[a] += 1

    # Top copycat authors (in most duplication components)
    top_copycats = author_component_count.most_common(20)

    stats = {
        "n_pairs": len(pairs),
        "n_duped_skills": len(duped_skills),
        "pct_duped": round(len(duped_skills) / total_skills * 100, 1),
        "n_components": len(components),
        "largest_component": len(components[0]) if components else 0,
        "top_copycat_authors": [(a, c) for a, c in top_copycats],
        "component_sizes": [len(c) for c in components[:50]],
    }

    print(f"\nDuplication Analysis Results:")
    print(f"  Near-duplicate pairs:     {stats['n_pairs']}")
    print(f"  Skills in dupes:         {stats['n_duped_skills']} / {total_skills} ({stats['pct_duped']}%)")
    print(f"  Duplication components:  {stats['n_components']}")
    print(f"  Largest component size:  {stats['largest_component']}")
    print(f"\n  Top copycat authors (most duplication clusters):")
    for author, count in top_copycats[:10]:
        print(f"    {author}: {count} clusters")

    return stats


if __name__ == "__main__":
    analyze_duplication()
