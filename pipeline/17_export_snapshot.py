"""Stage 17 -- a static snapshot of everything the dashboard shows, for hosting without a server.

The dashboard normally asks a local FastAPI service, which reads ~13 GB of Parquet. A
hosted copy cannot carry that: Vercel's free plan takes at most 100 MB and 15,000 files
per deployment. So this computes, once, every response the dashboard's pages request and
writes them as gzip-compressed JSON under web/data/snapshot/. The dashboard reads those
files directly when it runs with BDA_SNAPSHOT=1 (or on Vercel); locally, nothing changes.

What is included, and what is not:
    every chart, the overview, the methodology data, the network
    all 1,381 groups, each with members, links and timeline
    accounts: the ACCOUNT_TOP most suspicious, plus every group member and every account
              in the network view -- not all 3,035,045
    copied text: every cross-account cluster in the lists; full text for the largest
              DUP_DETAIL clusters of each kind
    products: the PRODUCT_LIST burstiest in the list; detail for the top PRODUCT_DETAIL

Account pages show their most recent reviews' text. Fetching that per account costs a
scan of the 9.7 GB archive each time (review_sk is not prunable), so every text needed
by every exported page is fetched in ONE scan instead.

Run:  python pipeline/17_export_snapshot.py      (needs the pipeline artifacts, not the API)
"""
from __future__ import annotations

import gzip
import json
import math
import shutil
import sys
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from api import charts, db, story  # noqa: E402
from api import main as api  # noqa: E402

OUT = ROOT / "web" / "data" / "snapshot"
ACCOUNT_TOP = 10_000
DUP_DETAIL = 400
PRODUCT_LIST = 2_000
PRODUCT_DETAIL = 250
RECENT_REVIEWS = 25
TIMELINE_CAP = 1_500
SHARDS = {"reviewers": 64, "rings": 16, "products": 8}
RAW = (ROOT / "data" / "raw" / "reviews.parquet").as_posix()


def clean(value):
    """JSON-safe: NaN/inf -> null, numpy scalars -> Python."""
    if isinstance(value, Decimal):          # SQL literals such as `1.0 AS jaccard`
        value = float(value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "item"):
        return clean(value.item())
    return value


def write(rel: str, payload) -> int:
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(clean(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(raw)
    return path.stat().st_size


def raw_text(review_sks: set[int]) -> dict[int, dict]:
    """Summary and text for many reviews in one scan of the archive."""
    con = db.connect().cursor()
    con.execute("CREATE OR REPLACE TABLE want AS SELECT unnest(?::BIGINT[]) AS review_sk",
                [sorted(review_sks)])
    rows = con.execute(f"""
        SELECT r.file_row_number::BIGINT AS review_sk, r.summary, r.reviewText
        FROM read_parquet('{RAW}', file_row_number=true) r
        JOIN want w ON w.review_sk = r.file_row_number""").fetchall()
    return {int(sk): {"summary": s, "reviewText": t} for sk, s, t in rows}


def main() -> None:
    t_all = time.time()
    resume = "--resume" in sys.argv
    if OUT.exists() and not resume:
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    def done(kind: str) -> bool:
        return resume and len(list((OUT / kind).glob("*.json.gz"))) == SHARDS[kind]
    sizes: dict[str, int] = defaultdict(int)

    # ---------------------------------------------------------- fixed responses
    fixed = {
        "/overview": api.overview(),
        "/meta": api.score_meta(),
        "/charts/highlights": charts.highlights(),
        "/charts/volume?bucket=60": charts.corpus_volume(bucket=60),
        "/charts/rating-by-decile": charts.rating_by_decile(),
        "/charts/family-composition?k=10000": charts.family_composition(k=10_000),
        "/charts/reviewer-scatter": charts.reviewer_scatter(min_reviews=5),
        "/charts/ring-scatter": charts.ring_scatter(),
        "/charts/cluster-sizes": charts.cluster_sizes(),
        "/charts/correlation": charts.correlation(),
        "/charts/agreement": charts.agreement(),
        "/story/network": story.network_summary(),
        "/story/network/graph?view=packs": story.network_graph(view="packs"),
        "/story/network/graph?view=core": story.network_graph(view="core"),
    }
    sizes["fixed"] += write("fixed.json.gz", fixed)
    print(f"[fixed] {len(fixed)} responses")

    # ------------------------------------------------------------------- rings
    t0 = time.time()
    ring_rows = db.rows("SELECT * FROM rings")
    sizes["lists"] += write("lists/rings.json.gz", ring_rows)
    shards = defaultdict(dict)
    for i, r in enumerate([] if done("rings") else ring_rows, 1):
        rid = int(r["ring_id"])
        shards[rid % SHARDS["rings"]][rid] = {
            "detail": api.ring_detail(rid, max_nodes=200),
            "convergence": api.ring_convergence(rid, max_products=40)}
        if i % 200 == 0:
            print(f"  rings {i}/{len(ring_rows)}  {time.time() - t0:.0f}s", flush=True)
    for k, v in shards.items():
        sizes["rings"] += write(f"rings/{k:02d}.json.gz", v)
    ring_members = {int(r["reviewer_sk"]) for r in db.rows(
        "SELECT reviewer_sk FROM ring_members WHERE ring_id IS NOT NULL")}
    print(f"[rings] {len(ring_rows):,} in {time.time() - t0:.0f}s")

    # ------------------------------------------------------- accounts selected
    network = json.loads((ROOT / "data" / "story" / "network.json").read_text(encoding="utf-8"))
    network_ids = {n["id"] for view in ("packs", "core") for n in network[view]["nodes"]}
    top = {int(r["reviewer_sk"]) for r in db.rows(
        f"SELECT reviewer_sk FROM scores ORDER BY score DESC LIMIT {ACCOUNT_TOP}")}
    accounts = sorted(top | ring_members | network_ids)
    print(f"[accounts] {len(accounts):,} selected "
          f"(top {ACCOUNT_TOP:,} + {len(ring_members):,} group members + "
          f"{len(network_ids):,} network accounts, overlapping)")

    con = db.connect().cursor()
    con.execute("CREATE OR REPLACE TABLE acc AS SELECT unnest(?::BIGINT[]) AS reviewer_sk",
                [accounts])

    def table_rows(sql: str) -> list[dict]:
        cur = db.connect().cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # list view rows (same columns the API's /reviewers returns)
    score_rows = table_rows("SELECT s.* FROM scores s JOIN acc USING (reviewer_sk)")
    sizes["lists"] += write("lists/reviewers.json.gz", score_rows)
    profile = {int(r["reviewer_sk"]): r for r in score_rows}
    features = {int(r["reviewer_sk"]): r for r in
                table_rows("SELECT f.* FROM feat_reviewer f JOIN acc USING (reviewer_sk)")}
    contrib = {int(r["reviewer_sk"]): r for r in
               table_rows("SELECT c.* FROM contributions c JOIN acc USING (reviewer_sk)")}
    families = db.meta().get("families", {})

    t0 = time.time()
    recent = defaultdict(list)
    timeline = defaultdict(list)
    skip_accounts = done("reviewers")
    for r in [] if skip_accounts else table_rows(f"""
            SELECT * FROM (
              SELECT f.reviewer_sk, f.review_sk, f.day, f.rating, f.n_words, f.helpful_yes,
                     f.helpful_total, p.asin,
                     row_number() OVER (PARTITION BY f.reviewer_sk ORDER BY f.day DESC) AS rn
              FROM fact f JOIN acc USING (reviewer_sk) JOIN dim_product p USING (product_sk))
            WHERE rn <= {RECENT_REVIEWS} ORDER BY reviewer_sk, day DESC"""):
        r.pop("rn")
        recent[int(r.pop("reviewer_sk"))].append(r)
    for r in [] if skip_accounts else table_rows(f"""
            SELECT * FROM (
              SELECT f.reviewer_sk, f.day, f.rating, f.n_words, f.helpful_yes, f.helpful_total,
                     p.asin, f.product_sk,
                     row_number() OVER (PARTITION BY f.reviewer_sk ORDER BY f.day DESC) AS rn
              FROM fact f JOIN acc USING (reviewer_sk) JOIN dim_product p USING (product_sk)
              WHERE f.day IS NOT NULL)
            WHERE rn <= {TIMELINE_CAP} ORDER BY reviewer_sk, day"""):
        r.pop("rn")
        timeline[int(r.pop("reviewer_sk"))].append(r)
    print(f"[accounts] reviews and timelines in {time.time() - t0:.0f}s")

    # ------------------------------------------------------ copied-text clusters
    dup_lists = {
        "exact": table_rows("SELECT * FROM dup_clusters WHERE is_cross_reviewer"),
        "loose": table_rows("SELECT * FROM neardup_clusters WHERE config = 'loose' AND n_reviewers > 1"),
        "tight": table_rows("SELECT * FROM neardup_clusters WHERE config = 'tight' AND n_reviewers > 1"),
    }
    for kind, rows in dup_lists.items():
        sizes["lists"] += write(f"lists/duplicates-{kind}.json.gz", rows)
    dup_members: dict[str, dict[int, list]] = {}
    for kind, rows in dup_lists.items():
        pool = [r for r in rows if kind != "exact" or r.get("is_substantive")]
        chosen = sorted(pool, key=lambda r: (-(r["n_reviewers"] or 0), r["cluster_id"]))[:DUP_DETAIL]
        ids = ",".join(str(int(r["cluster_id"])) for r in chosen)
        if kind == "exact":
            members = table_rows(f"""
                SELECT * FROM (
                  SELECT m.cluster_id, m.review_sk, m.reviewer_sk, d.reviewerID, d.reviewer_name,
                         p.asin, m.day, m.rating, 1.0 AS jaccard,
                         row_number() OVER (PARTITION BY m.cluster_id ORDER BY m.day) AS rn
                  FROM dup_members m JOIN dim_reviewer d USING (reviewer_sk)
                  JOIN dim_product p USING (product_sk) WHERE m.cluster_id IN ({ids}))
                WHERE rn <= 40 ORDER BY cluster_id, rn""")
        else:
            members = table_rows(f"""
                SELECT * FROM (
                  SELECT m.cluster_id, m.review_sk, m.reviewer_sk, d.reviewerID, d.reviewer_name,
                         p.asin, m.day, m.rating, m.jaccard,
                         row_number() OVER (PARTITION BY m.cluster_id ORDER BY m.jaccard DESC) AS rn
                  FROM neardup_members m JOIN dim_reviewer d USING (reviewer_sk)
                  JOIN dim_product p USING (product_sk)
                  WHERE m.config = '{kind}' AND m.cluster_id IN ({ids}))
                WHERE rn <= 40 ORDER BY cluster_id, rn""")
        by = defaultdict(list)
        for m in members:
            m.pop("rn")
            by[int(m.pop("cluster_id"))].append(m)
        dup_members[kind] = {"clusters": {int(r["cluster_id"]): r for r in chosen}, "members": by}

    # ---------------------------------------------- one scan for all review text
    t0 = time.time()
    want = {int(r["review_sk"]) for rows in recent.values() for r in rows}
    want |= {int(m["review_sk"]) for d in dup_members.values()
             for ms in d["members"].values() for m in ms}
    texts = raw_text(want)
    print(f"[text] {len(texts):,} reviews fetched in one scan, {time.time() - t0:.0f}s")

    # ------------------------------------------------------- write account shards
    shards = defaultdict(dict)
    for sk in ([] if done("reviewers") else accounts):
        c = {k: v for k, v in (contrib.get(sk) or {}).items() if k != "reviewer_sk"}
        reviews = []
        for r in recent.get(sk, []):
            t = texts.get(int(r["review_sk"]), {})
            reviews.append({**r, "snippet": (t.get("reviewText") or "").replace("\n", " ")
                            [:db.SNIPPET_CHARS], "summary": t.get("summary")})
        detail = {
            "profile": profile.get(sk), "features": features.get(sk),
            "contributions": [{"feature": k, "percentile": v,
                               "family": next((f for f, m in families.items() if k in m), "?")}
                              for k, v in sorted(c.items(), key=lambda kv: -(kv[1] or 0))],
            "recent_reviews": reviews}
        shards[sk % SHARDS["reviewers"]][sk] = {"detail": detail,
                                                "timeline": {"points": timeline.get(sk, [])}}
    for k, v in shards.items():
        sizes["reviewers"] += write(f"reviewers/{k:02d}.json.gz", v)

    # ---------------------------------------------------- copied-text details
    for kind, d in dup_members.items():
        out = {}
        for cid, cluster in d["clusters"].items():
            members = []
            for m in d["members"].get(cid, []):
                t = texts.get(int(m["review_sk"]), {})
                members.append({**m, "reviewText": t.get("reviewText"), "summary": t.get("summary")})
            out[cid] = {"kind": kind, "cluster": cluster, "members": members}
        sizes["duplicates"] += write(f"duplicates/{kind}.json.gz", out)

    # ---------------------------------------------------------------- products
    t0 = time.time()
    prod_rows = table_rows(f"""
        SELECT fp.product_sk, dp.asin, fp.n_reviews, fp.mean_rating, fp.max_daily_z,
               fp.max_7d_z, fp.peak_day, fp.dup_text_rate, fp.rating_shift
        FROM feat_product fp JOIN dim_product dp USING (product_sk)
        WHERE fp.n_reviews >= 10 ORDER BY fp.max_daily_z DESC LIMIT {PRODUCT_LIST}""")
    sizes["lists"] += write("lists/products.json.gz", prod_rows)
    shards = defaultdict(dict)
    for r in prod_rows[:PRODUCT_DETAIL]:
        sk = int(r["product_sk"])
        shards[sk % SHARDS["products"]][sk] = {"detail": api.product_detail(str(sk)),
                                               "ratings": api.product_ratings(str(sk)),
                                               "asin": r["asin"]}
    asin_index = {}
    for k, v in shards.items():
        sizes["products"] += write(f"products/{k:02d}.json.gz", v)
        asin_index.update({entry["asin"]: sk for sk, entry in v.items()})
    sizes["products"] += write("products/asin-index.json.gz", asin_index)
    print(f"[products] {len(prod_rows):,} listed, {PRODUCT_DETAIL} with detail, "
          f"{time.time() - t0:.0f}s")

    # ------------------------------------------------------------------- report
    manifest = {"accounts": len(accounts), "rings": len(ring_rows),
                "dup_detail_per_kind": DUP_DETAIL, "products_listed": len(prod_rows),
                "products_detail": PRODUCT_DETAIL, "shards": SHARDS,
                "built_seconds": round(time.time() - t_all)}
    write("manifest.json.gz", manifest)
    files = list(OUT.rglob("*.gz"))
    total = sum(f.stat().st_size for f in files)
    print("\nsizes (compressed):")
    for k, v in sorted(sizes.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<11} {v / 1e6:7.1f} MB")
    print(f"  {'TOTAL':<11} {total / 1e6:7.1f} MB in {len(files)} files "
          f"({time.time() - t_all:.0f}s)")


if __name__ == "__main__":
    main()
