"""similarity.py — two-phase content similarity analysis.

Phase 1: MinHash + Jaccard pre-filter (no API cost)
Phase 2: OpenAI text-embedding-3-small + DBSCAN clustering

Outputs:
    data/similarity_pairs.csv   — near-duplicate pairs
    data/embeddings.npy         — embedding vectors
    data/clusters.csv           — DBSCAN cluster assignments
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from src.core.config import DB_PATH, ROOT

OUT_DIR = ROOT / "data"


def _tokenize(text: str) -> list[int]:
    """Simple 3-gram tokenization to integers for MinHash."""
    if not text:
        return []
    tokens = []
    for i in range(len(text) - 2):
        chunk = text[i:i+3]
        tokens.append(hash(chunk) & 0x7FFFFFFF)
    return tokens


def _minhash_signature(tokens: list[int], num_hashes: int = 128) -> np.ndarray:
    """Compute MinHash signature for a token list."""
    if not tokens:
        return np.full(num_hashes, 2**31 - 1, dtype=np.int64)
    max_int = 2**31 - 1
    sig = np.full(num_hashes, max_int, dtype=np.int64)
    tokens_arr = np.array(tokens, dtype=np.int64)
    for i in range(num_hashes):
        a = i * 2 + 1
        b = i * 3 + 7
        h = ((a * tokens_arr + b) % 2147483647) % max_int
        sig[i] = int(h.min())
    return sig


def _jaccard_from_sigs(sig1: np.ndarray, sig2: np.ndarray) -> float:
    """Estimate Jaccard from two MinHash signatures."""
    return float((sig1 == sig2).mean())


def phase1_minhash_filter(threshold: float = 0.90) -> list[dict]:
    """Pre-filter: find pairs with MinHash Jaccard >= threshold.

    Returns list of {ident1, name1, ident2, name2, jaccard} dicts.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT identifier, name, skill_md_text
        FROM skills
        WHERE skill_md_text IS NOT NULL AND skill_md_text <> ''
    """).fetchall()
    conn.close()

    print(f"Phase 1: MinHash on {len(rows)} skills...")

    # Build signatures
    sigs = {}
    names = {}
    texts = {}
    for r in rows:
        tokens = _tokenize(r["skill_md_text"])
        sigs[r["identifier"]] = _minhash_signature(tokens)
        names[r["identifier"]] = r["name"] or ""
        texts[r["identifier"]] = r["skill_md_text"]

    # Find high-similarity pairs
    idents = list(sigs.keys())
    n = len(idents)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = _jaccard_from_sigs(sigs[idents[i]], sigs[idents[j]])
            if sim >= threshold:
                pairs.append({
                    "ident1": idents[i],
                    "name1": names[idents[i]],
                    "ident2": idents[j],
                    "name2": names[idents[j]],
                    "jaccard": round(sim, 4),
                })

    pairs.sort(key=lambda x: -x["jaccard"])
    print(f"  Found {len(pairs)} pairs with Jaccard >= {threshold:.0%}")

    # Save
    out_path = OUT_DIR / "similarity_pairs.csv"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("ident1,name1,ident2,name2,jaccard\n")
        for p in pairs:
            f.write(f'{p["ident1"]},{p["name1"]},{p["ident2"]},{p["name2"]},{p["jaccard"]}\n')
    print(f"  Saved -> {out_path}")

    return pairs


def phase2_semantic_cluster(
    api_key: Optional[str] = None,
    *,
    eps: float = 0.05,
    min_samples: int = 2,
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """Phase 2: OpenAI embeddings + DBSCAN clustering.

    Requires OPENAI_API_KEY env var or passed api_key.

    Returns (embeddings, labels, identifiers, names).
    """
    from openai import OpenAI
    from sklearn.cluster import DBSCAN
    from sklearn.metrics.pairwise import cosine_similarity

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT identifier, name, skill_md_text
        FROM skills
        WHERE skill_md_text IS NOT NULL AND skill_md_text <> ''
        ORDER BY identifier
    """).fetchall()
    conn.close()

    texts = [r["skill_md_text"] for r in rows]
    idents = [r["identifier"] for r in rows]
    names = [r["name"] or "" for r in rows]

    print(f"Phase 2: Embedding {len(texts)} texts via OpenAI text-embedding-3-small...")
    # Rough cost estimate
    total_chars = sum(len(t) for t in texts)
    est_tokens = total_chars // 4  # rough approximation
    est_cost = est_tokens / 1_000_000 * 0.02  # $0.02 per 1M tokens
    print(f"  ~{est_tokens:,} tokens, estimated cost: ${est_cost:.3f}")

    if api_key is None:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set. Set env var or pass api_key.")
        print("Skipping Phase 2. Phase 1 MinHash results are available.")
        return np.array([]), np.array([]), idents, names

    import os

    client = OpenAI(api_key=api_key)

    embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        # Truncate very long texts to fit embedding model context
        batch_trunc = [t[:8000] for t in batch]
        resp = client.embeddings.create(model="text-embedding-3-small", input=batch_trunc)
        for item in resp.data:
            embeddings.append(item.embedding)
        if (i + batch_size) % 500 == 0:
            print(f"  embedded {min(i + batch_size, len(texts))}/{len(texts)}")

    embeddings_arr = np.array(embeddings, dtype=np.float32)
    print(f"  Embedded {len(embeddings_arr)} texts, shape={embeddings_arr.shape}")

    # Save embeddings
    np.save(OUT_DIR / "embeddings.npy", embeddings_arr)
    print(f"  Saved embeddings -> {OUT_DIR / 'embeddings.npy'}")

    # DBSCAN clustering
    print(f"Clustering with DBSCAN (eps={eps}, min_samples={min_samples})...")
    clustering = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine")
    labels = clustering.fit_predict(embeddings_arr)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int((labels == -1).sum())

    print(f"  Clusters: {n_clusters}, Noise points: {n_noise}")

    # Save cluster assignments
    out_path = OUT_DIR / "clusters.csv"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("identifier,name,cluster\n")
        for ident, name, label in zip(idents, names, labels):
            f.write(f'{ident},"{name}",{label}\n')
    print(f"  Saved -> {out_path}")

    # Cluster size distribution
    from collections import Counter
    cluster_counts = Counter(labels[labels >= 0])
    top_clusters = cluster_counts.most_common(20)
    print(f"\n  Top-20 clusters by size:")
    for cluster_id, size in top_clusters:
        # Find the "original" (earliest updated_at) in each cluster
        cluster_idents = [idents[i] for i in range(len(labels)) if labels[i] == cluster_id]
        # Get first few names
        sample_names = [names[idents.index(ci)] for ci in cluster_idents[:5]]
        print(f"    cluster {cluster_id}: {size} skills, examples: {sample_names[:3]}")

    return embeddings_arr, labels, idents, names


def main() -> None:
    """Run both phases."""
    import os

    # Phase 1: MinHash (no cost)
    pairs = phase1_minhash_filter(threshold=0.90)

    # Stats on pairs
    if pairs:
        unique_idents = set()
        for p in pairs:
            unique_idents.add(p["ident1"])
            unique_idents.add(p["ident2"])
        print(f"\nMinHash summary: {len(pairs)} pairs, {len(unique_idents)} unique skills involved")

    print()

    # Phase 2: Embeddings + clustering (needs API key)
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        embeddings, labels, idents, names = phase2_semantic_cluster(api_key)
    else:
        print("Skipping Phase 2: set OPENAI_API_KEY env var.")
        print("Phase 1 MinHash results are available in data/similarity_pairs.csv")


if __name__ == "__main__":
    main()
