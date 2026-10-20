"""Stage 7 -- turn LSH band collisions into verified near-duplicate clusters.

Three steps:

1. CANDIDATES. For each of the 24 band columns, group reviews sharing a band hash.
   A bucket of size m contributes m-1 star edges to a candidate graph. Buckets
   larger than LSH_BUCKET_CAP are truncated and every truncation is logged --
   a silent cap reads as "we covered everything" when it did not.

2. COMPONENTS. scipy.sparse.csgraph.connected_components over the candidate graph.
   networkx would need ~500 B/edge and is not usable at this scale.

3. VERIFICATION. LSH produces candidates, not answers: two documents can share a
   band by chance. Each component member is compared against the component
   exemplar by EXACT Jaccard over word k-shingles, and members below the
   configuration's threshold are dropped. This is linear in component size, not
   quadratic, and it gives the UI a real similarity number to display rather
   than a probabilistic one.

Two independent cluster sets are produced from the same signatures:
    loose  (16 bands x 8 rows)  verified at Jaccard >= 0.707
    tight  ( 8 bands x 16 rows) verified at Jaccard >= 0.878
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xxhash
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

OUT_CLUSTERS = common.ns(common.DATA / "features" / "neardup_clusters.parquet")
OUT_MEMBERS = common.ns(common.DATA / "features" / "neardup_members.parquet")

CONFIGS = {
    "loose": {"prefix": "loose", "n_bands": common.LSH_CONFIGS["loose"][0], "threshold": 0.707},
    "tight": {"prefix": "tight", "n_bands": common.LSH_CONFIGS["tight"][0], "threshold": 0.878},
}
K = common.SHINGLE_K
MAX_VERIFY_MEMBERS = 5_000  # components larger than this are verified on a sample


def shingle_set(text: str) -> set[int]:
    words = text.lower().split()
    if len(words) < K:
        return {xxhash.xxh64_intdigest(" ".join(words))}
    return {xxhash.xxh64_intdigest(" ".join(words[i:i + K])) for i in range(len(words) - K + 1)}


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def candidate_edges(con, prefix: str, n_bands: int) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Star edges from every multi-member LSH bucket across this config's bands."""
    left, right, truncated, buckets = [], [], 0, 0
    for band in range(n_bands):
        column = f"{prefix}_{band:02d}"
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE g AS
            SELECT {column} AS h, count(*)::INTEGER AS c, min(review_sk) AS root
            FROM bands GROUP BY 1 HAVING count(*) > 1
        """)
        n_buckets, n_over = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE c > {common.LSH_BUCKET_CAP}) FROM g"
        ).fetchone()
        pairs = con.execute(f"""
            SELECT b.review_sk, g.root
            FROM bands b JOIN g ON b.{column} = g.h
            WHERE b.review_sk <> g.root AND g.c <= {common.LSH_BUCKET_CAP}
        """).fetchnumpy()
        left.append(pairs["review_sk"].astype(np.int64))
        right.append(pairs["root"].astype(np.int64))
        buckets += n_buckets
        truncated += n_over
        print(f"    {column}: {n_buckets:>9,} multi-member buckets, "
              f"{len(pairs['root']):>10,} edges"
              + (f"  [{n_over:,} buckets over cap, DROPPED]" if n_over else ""), flush=True)
    return np.concatenate(left), np.concatenate(right), buckets, truncated


def main() -> None:
    common.guard_disk()
    con = common.connect()
    con.execute(f"CREATE VIEW bands AS {common.bands_sql()}")
    con.execute(f"CREATE VIEW f AS SELECT * FROM '{common.FACT_PARQUET.as_posix()}'")
    con.execute(f"CREATE VIEW raw AS {common.raw_sql()}")
    n_docs = con.execute("SELECT count(*) FROM bands").fetchone()[0]
    print(f"{n_docs:,} documents carry band hashes\n")

    all_clusters, all_members = [], []

    for name, cfg in CONFIGS.items():
        with common.stage(f"07_neardup: {name} candidates (J >= {cfg['threshold']})"):
            src, dst, n_buckets, n_trunc = candidate_edges(con, cfg["prefix"], cfg["n_bands"])
            print(f"  {n_buckets:,} multi-member buckets, {len(src):,} candidate edges"
                  + (f", {n_trunc:,} oversized buckets dropped" if n_trunc else ""))
            if not len(src):
                print("  no candidates; skipping")
                continue

            # Relabel to a dense index so the graph is only as big as the docs involved.
            nodes = np.unique(np.concatenate([src, dst]))
            index = {int(v): i for i, v in enumerate(nodes)}
            si = np.fromiter((index[int(v)] for v in src), dtype=np.int32, count=len(src))
            di = np.fromiter((index[int(v)] for v in dst), dtype=np.int32, count=len(dst))
            graph = coo_matrix((np.ones(len(si), dtype=np.int8), (si, di)),
                               shape=(len(nodes), len(nodes))).tocsr()
            n_comp, labels = connected_components(graph, directed=False)
            print(f"  {len(nodes):,} documents in {n_comp:,} candidate components")

        with common.stage(f"07_neardup: {name} exact-Jaccard verification"):
            order = np.argsort(labels, kind="stable")
            sorted_labels = labels[order]
            starts = np.searchsorted(sorted_labels, np.arange(n_comp))
            ends = np.searchsorted(sorted_labels, np.arange(n_comp), side="right")

            # Pull the text for every candidate document once, in one query.
            candidate_sks = nodes.astype(np.int64)
            con.execute("CREATE OR REPLACE TEMP TABLE cand AS SELECT * FROM "
                        "(SELECT unnest(?::BIGINT[]) AS review_sk)", [candidate_sks.tolist()])
            text_rows = con.execute("""
                SELECT c.review_sk, r.reviewText
                FROM cand c JOIN raw r ON r.review_sk = c.review_sk
            """).fetchall()
            texts = {int(sk): txt for sk, txt in text_rows}
            print(f"  fetched text for {len(texts):,} candidate documents")

            shingles: dict[int, set[int]] = {}
            kept_cluster, kept_member, sampled = [], [], 0
            threshold = cfg["threshold"]

            for comp in range(n_comp):
                members = nodes[order[starts[comp]:ends[comp]]]
                if len(members) < 2:
                    continue
                if len(members) > MAX_VERIFY_MEMBERS:
                    sampled += 1
                    members = members[:MAX_VERIFY_MEMBERS]
                exemplar = int(members.min())
                if exemplar not in shingles:
                    shingles[exemplar] = shingle_set(texts.get(exemplar, ""))
                base = shingles[exemplar]
                verified = [(exemplar, 1.0)]
                for raw_sk in members:
                    sk = int(raw_sk)
                    if sk == exemplar:
                        continue
                    score = jaccard(base, shingle_set(texts.get(sk, "")))
                    if score >= threshold:
                        verified.append((sk, score))
                if len(verified) < 2:
                    continue
                cid = len(kept_cluster)
                kept_cluster.append((cid, exemplar, len(verified),
                                     float(np.mean([s for _, s in verified]))))
                kept_member.extend((sk, cid, score) for sk, score in verified)

            print(f"  verified {len(kept_cluster):,} clusters covering "
                  f"{len(kept_member):,} documents "
                  f"({100 * (n_comp - len(kept_cluster)) / max(n_comp, 1):.1f}% of candidate "
                  f"components rejected as LSH false positives)")
            if sampled:
                print(f"  NOTE: {sampled:,} components exceeded {MAX_VERIFY_MEMBERS:,} members "
                      f"and were verified on the first {MAX_VERIFY_MEMBERS:,} only")

        if not kept_cluster:
            continue

        con.execute("CREATE OR REPLACE TEMP TABLE m (review_sk BIGINT, cluster_id INTEGER, "
                    "jaccard DOUBLE)")
        con.executemany("INSERT INTO m VALUES (?, ?, ?)", kept_member)
        con.execute("CREATE OR REPLACE TEMP TABLE c (cluster_id INTEGER, exemplar_sk BIGINT, "
                    "n_reviews INTEGER, mean_jaccard DOUBLE)")
        con.executemany("INSERT INTO c VALUES (?, ?, ?, ?)", kept_cluster)

        con.execute(f"""
            CREATE OR REPLACE TABLE clusters_{name} AS
            SELECT '{name}' AS config, c.cluster_id, c.exemplar_sk, c.n_reviews, c.mean_jaccard,
                   s.n_reviewers, s.n_products, s.span_days, s.mean_rating, s.first_day
            FROM c JOIN (
                SELECT m.cluster_id,
                       count(DISTINCT f.reviewer_sk)::INTEGER AS n_reviewers,
                       count(DISTINCT f.product_sk)::INTEGER  AS n_products,
                       (max(f.day) - min(f.day))              AS span_days,
                       avg(f.rating::DOUBLE)                  AS mean_rating,
                       min(f.day)                             AS first_day
                FROM m JOIN f ON f.review_sk = m.review_sk GROUP BY 1
            ) s USING (cluster_id)
        """)
        con.execute(f"""
            CREATE OR REPLACE TABLE members_{name} AS
            SELECT '{name}' AS config, m.review_sk::INTEGER AS review_sk, m.cluster_id, m.jaccard,
                   f.reviewer_sk, f.product_sk, f.day, f.rating
            FROM m JOIN f ON f.review_sk = m.review_sk
        """)
        all_clusters.append(f"clusters_{name}")
        all_members.append(f"members_{name}")

    if not all_clusters:
        raise SystemExit("No near-duplicate clusters found in either configuration.")

    con.execute(f"COPY ({' UNION ALL BY NAME '.join(f'SELECT * FROM {t}' for t in all_clusters)}) "
                f"TO '{OUT_CLUSTERS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY ({' UNION ALL BY NAME '.join(f'SELECT * FROM {t}' for t in all_members)}) "
                f"TO '{OUT_MEMBERS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")

    print("\n[summary]")
    for row in con.execute(f"""
        SELECT config, count(*) AS clusters, sum(n_reviews) AS reviews,
               count(*) FILTER (WHERE n_reviewers > 1) AS cross_reviewer,
               count(*) FILTER (WHERE n_reviewers >= 3) AS three_plus,
               max(n_reviewers) AS max_accounts, round(avg(mean_jaccard), 3) AS avg_j
        FROM '{OUT_CLUSTERS.as_posix()}' GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"  {row[0]:<6} {row[1]:>8,} clusters  {row[2]:>9,} reviews  "
              f"{row[3]:>7,} cross-reviewer  {row[4]:>6,} with >=3 accounts  "
              f"max {row[5]:,} accounts  mean J {row[6]}")

    print("\n[top cross-reviewer near-duplicate clusters (loose)]")
    rows = con.execute(f"""
        SELECT c.cluster_id, c.n_reviewers, c.n_products, c.n_reviews, c.span_days,
               round(c.mean_jaccard, 3), round(c.mean_rating, 2),
               left(replace(r.reviewText, chr(10), ' '), 80)
        FROM '{OUT_CLUSTERS.as_posix()}' c
        JOIN raw r ON r.review_sk = c.exemplar_sk
        WHERE c.config = 'loose' AND c.n_reviewers >= 3
        ORDER BY c.n_reviewers DESC LIMIT 15""").fetchall()
    print(f"  {'id':>7} {'accts':>6} {'prods':>6} {'revs':>5} {'days':>6} {'J':>6} {'rating':>6}  text")
    for row in rows:
        print(f"  {row[0]:>7} {row[1]:>6} {row[2]:>6} {row[3]:>5} {row[4]:>6} "
              f"{row[5]:>6} {row[6]:>6}  {row[7]}")

    con.close()
    print("\nStage 7 complete.")


if __name__ == "__main__":
    main()
