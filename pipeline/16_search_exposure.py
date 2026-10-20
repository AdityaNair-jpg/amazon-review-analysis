"""Stage 16 -- where suspicious reviews reach shoppers, and what demotion does about it.

A spam review nobody reads is harmless; the harm happens at retrieval time, when a
shopper searches and the review ranks. So this runs 40 ordinary shopping searches and
counts, in each top 10, the reviews written by a top-1% suspicious account -- once as
plain BM25, once with the demotion penalty on.

What it found, which is not the dramatic version and is worth showing as-is:

    5.3% of top-10 results are from flagged accounts, against a 3.91% base rate
    -- about 1.3x, and most searches have none at all -- but a few categories are
    badly hit ("vitamin supplement": 5 of 10).

So the honest headline is concentration, not contamination: most searches are clean
and some categories are not. The search page shows every query, not only the worst.

Base rate is review-weighted -- the share of all 41.1M reviews written by a flagged
account -- because a search result is a review, not an account. It is higher than the
1% of accounts that are flagged because those accounts are prolific.

Writes data/story/search_exposure.json.  Run:  python pipeline/16_search_exposure.py
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
import common  # noqa: E402
from api import search  # noqa: E402

OUT = common.DATA / "story" / "search_exposure.json"
SCORE_CUT = 0.9
TOP_K = 10

# Everyday product searches, chosen before looking at any result. Not tuned: the point
# is the distribution across ordinary queries, so none were added or dropped for how
# they came out.
QUERIES = [
    "wireless headphones", "phone case", "coffee maker", "running shoes",
    "vitamin supplement", "hair dryer", "kids book", "bluetooth speaker", "yoga mat",
    "kitchen knife", "protein powder", "phone charger", "water bottle", "face cream",
    "dog food", "board game", "novel mystery", "usb cable", "laptop bag",
    "electric toothbrush", "sunscreen", "vacuum cleaner", "teeth whitening",
    "e-cigarette", "weight loss", "screen protector", "blender", "camera lens",
    "led flashlight", "shampoo", "cookbook", "watch band", "memory card", "baby bottle",
    "car charger", "keyboard", "tea", "perfume", "romance novel", "action movie",
]


def run(query: str, demote: bool) -> dict:
    # Every argument explicit: the endpoint's defaults are FastAPI Query objects,
    # only resolved when it is called over HTTP.
    result = search.search(q=query, limit=TOP_K, offset=0, demote=demote, rerank=False,
                           min_rating=0, group=None)
    items = result["items"]
    flagged = [h for h in items if (h.get("suspicion") or 0) >= SCORE_CUT]
    return {"n": len(items), "flagged": len(flagged),
            "flagged_ids": [h["doc_id"] for h in flagged]}


def main() -> None:
    con = common.connect()
    con.execute(f"CREATE VIEW scores AS SELECT reviewer_sk, score FROM "
                f"'{(common.DATA / 'scores' / 'reviewer_scores.parquet').as_posix()}'")
    con.execute(f"CREATE VIEW fact AS SELECT reviewer_sk FROM "
                f"'{common.FACT_PARQUET.as_posix()}'")
    with common.stage("16_exposure: review-weighted base rate"):
        base = con.execute(f"""
            SELECT avg(CASE WHEN s.score >= {SCORE_CUT} THEN 1.0 ELSE 0.0 END)
            FROM fact f JOIN scores s USING (reviewer_sk)""").fetchone()[0]
    con.close()
    print(f"  {base:.2%} of all reviews are by a flagged account")

    rows = []
    with common.stage("16_exposure: 40 searches, with and without demotion"):
        for query in QUERIES:
            t0 = time.time()
            plain, demoted = run(query, False), run(query, True)
            rows.append({"query": query, "n": plain["n"],
                         "flagged": plain["flagged"], "flagged_demoted": demoted["flagged"]})
            print(f"  {plain['flagged']:>2} -> {demoted['flagged']:>2}  of {plain['n']}  "
                  f"{query:<22} {(time.time() - t0) * 1000:5.0f} ms", flush=True)

    shown = [r for r in rows if r["n"]]
    share = sum(r["flagged"] for r in shown) / sum(r["n"] for r in shown)
    share_demoted = sum(r["flagged_demoted"] for r in shown) / sum(r["n"] for r in shown)
    rows.sort(key=lambda r: (-r["flagged"], r["query"]))
    summary = {
        "queries": len(shown), "top_k": TOP_K, "score_cut": SCORE_CUT,
        "base_rate": base, "share": share, "lift": share / base,
        "share_demoted": share_demoted,
        "clean_queries": sum(1 for r in shown if r["flagged"] == 0),
        "clean_queries_demoted": sum(1 for r in shown if r["flagged_demoted"] == 0),
        "worst": rows[0]["query"], "worst_flagged": rows[0]["flagged"],
        "median_flagged": statistics.median(r["flagged"] for r in shown),
    }
    print(f"\n  flagged share of top-{TOP_K}: {share:.1%} "
          f"({share / base:.1f}x the base rate); with demotion {share_demoted:.1%}")
    print(f"  clean searches: {summary['clean_queries']}/{len(shown)} "
          f"-> {summary['clean_queries_demoted']}/{len(shown)} with demotion")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(f"\nWrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
