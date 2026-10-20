"""Stage 14 -- how good is the ranking? MRR and nDCG@10, measured.

A search engine with no accuracy number is a demo, not a system. The usual obstacle is
relevance judgements: someone has to read results and mark them. This corpus supplies a
set for free.

Stage 7 verified near-duplicate clusters -- groups of reviews whose wording is provably
near-identical, exact Jaccard >= 0.878 for the tight configuration. Take one review from
a cluster, use its opening words as a query, and its cluster-mates are, by construction,
documents that ought to be retrieved. No human judging, no guesswork, and the ground
truth was computed by a completely different part of the pipeline than the one being
measured.

What this does and does not tell you
    It measures known-item and near-duplicate retrieval: can the ranking find the
    documents that really do contain this wording, out of 41.1 million? That is the
    thing search here is actually for -- an investigator pastes a suspicious sentence
    and wants every account that posted it.

    It is not a Cranfield topical-relevance evaluation. Documents outside the cluster
    are counted as non-relevant even when a human would call them on-topic, so the
    absolute numbers are a floor, not a ceiling. As a comparison between ranking
    configurations, which is what it is used for, that bias cancels.

Metrics (Manning IIR ch. 8):
    MRR      mean of 1/rank of the first relevant document
    nDCG@10  discounted cumulative gain at 10, against the ideal ordering
    Recall@k fraction of the cluster found in the top k

Run:  python pipeline/14_evaluate.py [--queries 500] [--rerank]
Writes docs/ir_evaluation.md.
"""
from __future__ import annotations

import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

import common  # noqa: E402
from api import db, docblob, search  # noqa: E402

N_QUERIES = 500
QUERY_WORDS = 20
DEPTH = 10
SEED = 20240720
OUT = ROOT / "docs" / "ir_evaluation.md"


def sample_queries(n: int) -> list[dict]:
    """One query per near-duplicate cluster: its opening words, plus its members.

    Clusters of 2 to 20 are used. Singletons have no relevant set, and the huge
    clusters are Amazon's own boilerplate ("This review is from: ..."), which would
    measure the retrieval of template text rather than of anything a person wrote.
    """
    rng = random.Random(SEED)
    clusters = db.rows(f"""
        SELECT cluster_id, count(*) AS n
        FROM neardup_members WHERE config = 'tight'
        GROUP BY cluster_id HAVING count(*) BETWEEN 2 AND 20
        ORDER BY cluster_id""")
    if not clusters:
        raise SystemExit("no near-duplicate clusters; run pipeline/07_neardup.py first")
    rng.shuffle(clusters)

    picked = clusters[: n * 2]
    ids = ",".join(str(int(c["cluster_id"])) for c in picked)
    members = db.rows(f"SELECT cluster_id, review_sk FROM neardup_members "
                      f"WHERE config = 'tight' AND cluster_id IN ({ids})")
    by_cluster: dict[int, list[int]] = {}
    for m in members:
        by_cluster.setdefault(m["cluster_id"], []).append(m["review_sk"])

    # Fetch the text of one representative per cluster in a single pruned lookup.
    reps = {cid: min(docs) for cid, docs in by_cluster.items()}
    rep_ids = ",".join(str(int(v)) for v in reps.values())
    if docblob.available():
        texts = {i: (r["reviewText"] or "")
                 for i, r in docblob.fetch(list(reps.values())).items()}
    else:
        have = db.available()
        table = "docstore" if "docstore" in have else "raw"
        texts = {r["review_sk"]: (r["reviewText"] or "") for r in db.rows(
            f"SELECT review_sk, reviewText FROM {table} WHERE review_sk IN ({rep_ids})")}

    queries = []
    for cid, rep in reps.items():
        words = texts.get(rep, "").split()
        if len(words) < QUERY_WORDS:
            continue
        query = " ".join(words[:QUERY_WORDS])
        if not search.analyse(query):
            continue
        relevant = set(by_cluster[cid]) - {rep}
        if relevant:
            queries.append({"query": query, "rep": rep, "relevant": relevant})
        if len(queries) >= n:
            break
    return queries


def ndcg_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    """Binary-gain nDCG. The ideal ranking puts min(|relevant|, k) hits up front."""
    dcg = sum(1.0 / math.log2(i + 2)
              for i, doc in enumerate(ranked[:k]) if doc in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


def evaluate(queries: list[dict], rerank: bool) -> dict:
    mrr, ndcg, recall, latency, found = [], [], [], [], 0
    for i, q in enumerate(queries, 1):
        t0 = time.time()
        # Every parameter passed explicitly: the endpoint's defaults are FastAPI
        # Query objects, which are only resolved when it is called over HTTP.
        result = search.search(q=q["query"], limit=DEPTH, offset=0,
                               demote=False, rerank=rerank, min_rating=0)
        latency.append((time.time() - t0) * 1000)
        ranked = [h["doc_id"] for h in result["items"]]

        rank = next((j for j, doc in enumerate(ranked, 1) if doc in q["relevant"]), 0)
        mrr.append(1.0 / rank if rank else 0.0)
        found += 1 if rank else 0
        ndcg.append(ndcg_at_k(ranked, q["relevant"], DEPTH))
        hits = len(set(ranked) & q["relevant"])
        recall.append(hits / min(len(q["relevant"]), DEPTH))

        if i % 50 == 0:
            print(f"  {i}/{len(queries)}  MRR so far {statistics.mean(mrr):.3f}",
                  flush=True)

    latency.sort()
    return {
        "queries": len(queries),
        "mrr": round(statistics.mean(mrr), 4),
        "ndcg@10": round(statistics.mean(ndcg), 4),
        "recall@10": round(statistics.mean(recall), 4),
        "found_any": round(found / len(queries), 4),
        "p50_ms": round(latency[len(latency) // 2], 1),
        "p95_ms": round(latency[int(len(latency) * 0.95)], 1),
    }


def main() -> None:
    n = N_QUERIES
    if "--queries" in sys.argv:
        n = int(sys.argv[sys.argv.index("--queries") + 1])
    also_rerank = "--rerank" in sys.argv

    with common.stage("14_evaluate: build the query set"):
        queries = sample_queries(n)
    print(f"  {len(queries)} queries, "
          f"{statistics.mean(len(q['relevant']) for q in queries):.1f} relevant each")

    runs = {}
    with common.stage("14_evaluate: BM25"):
        runs["BM25"] = evaluate(queries, rerank=False)
    if also_rerank:
        from api import rerank as rr
        if rr.available():
            with common.stage("14_evaluate: BM25 + cross-encoder rerank"):
                runs["BM25 + neural rerank"] = evaluate(queries, rerank=True)
        else:
            print("  cross-encoder unavailable; skipping the rerank run")

    print()
    header = ["run", "MRR", "nDCG@10", "recall@10", "found", "p50 ms", "p95 ms"]
    print(" | ".join(header))
    lines = ["| " + " | ".join(header) + " |",
             "|" + "---|" * len(header)]
    for name, r in runs.items():
        cells = [name, f"{r['mrr']:.3f}", f"{r['ndcg@10']:.3f}",
                 f"{r['recall@10']:.3f}", f"{r['found_any']:.1%}",
                 f"{r['p50_ms']:.0f}", f"{r['p95_ms']:.0f}"]
        print(" | ".join(cells))
        lines.append("| " + " | ".join(cells) + " |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(f"""# Retrieval accuracy

Generated by `pipeline/14_evaluate.py` over {len(queries)} queries against all
{common.EXPECTED_ROWS:,} reviews.

## Where the relevance judgements come from

A query is the first {QUERY_WORDS} words of a review that belongs to a verified
near-duplicate cluster (stage 7, tight configuration, exact Jaccard >= 0.878). The
relevant set is that review's cluster-mates. Nobody judged anything by hand, and the
ground truth comes from a different part of the pipeline -- MinHash and LSH over
shingles -- than the ranking being measured.

Clusters are restricted to 2-20 members. Singletons have no relevant set; the very
large clusters are Amazon's own boilerplate, and retrieving template text would
flatter the numbers without meaning anything.

## Results

{chr(10).join(lines)}

## Reading these numbers

This is known-item and near-duplicate retrieval, not topical relevance. Documents
outside the cluster count as non-relevant even where a person would call them
on-topic, so these are a floor. That bias is identical across runs, so the comparison
between them is sound even though the absolute values are pessimistic.

It matches what search is for here: an investigator pastes a suspicious sentence and
wants every account that posted it.

```json
{json.dumps(runs, indent=2)}
```
""", encoding="utf-8")
    print(f"\nWrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
