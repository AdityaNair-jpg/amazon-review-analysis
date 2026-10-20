"""Local FastAPI service over the precomputed analysis. Binds to 127.0.0.1 only.

Design rule: the API never scans the 41.1M-row fact table or the 9.7 GB raw text
parquet to answer a list query. Every list and every chart reads a precomputed
table. The raw parquet is touched only to fetch the text of a specific, bounded
set of reviews, and those requests pass through a single-slot semaphore.

Start with:  uvicorn api.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import sys
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api import charts, db, search, story  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    present = db.available()
    print(f"[api] {len(present)} views: {', '.join(sorted(present))}")
    yield


app = FastAPI(title="Suspicious Review Detection", version="1.0.0",
              description="Local analysis of 41,135,700 Amazon reviews (2014 5-core).",
              lifespan=lifespan)
app.include_router(charts.router)
app.include_router(search.router)
app.include_router(story.router)


def _require(*views: str) -> None:
    missing = [v for v in views if v not in db.available()]
    if missing:
        raise HTTPException(503, f"pipeline artifacts not built: {', '.join(missing)}")


# --------------------------------------------------------------------- meta
@app.get("/health")
def health() -> dict:
    return {"ok": True, "views": sorted(db.available())}


@app.get("/meta")
@db.memo
def score_meta() -> dict:
    """Which features survived the cull, which family each sits in, and why."""
    return db.meta()


@app.get("/overview")
@db.memo
def overview() -> dict:
    _require("fact", "scores", "score_histogram")
    corpus = db.one("""
        SELECT count(*) AS n_reviews,
               count(DISTINCT reviewer_sk) AS n_reviewers,
               count(DISTINCT product_sk) AS n_products,
               min(day) AS first_day, max(day) AS last_day
        FROM fact""")
    ratings = db.rows("SELECT rating, count(*) AS n FROM fact GROUP BY 1 ORDER BY 1")
    histogram = db.rows("SELECT family, bin_lo, bin_hi, n FROM score_histogram "
                        "ORDER BY family, bin_lo")
    clusters = db.one("""
        SELECT (SELECT count(*) FROM dup_clusters WHERE is_cross_reviewer
                  AND is_substantive) AS exact_cross_reviewer,
               (SELECT count(*) FROM dup_clusters) AS exact_total,
               (SELECT count(*) FROM neardup_clusters WHERE config = 'loose')
                 AS neardup_loose,
               (SELECT count(*) FROM neardup_clusters WHERE config = 'tight')
                 AS neardup_tight,
               (SELECT count(*) FROM rings) AS rings
    """) if {"dup_clusters", "neardup_clusters", "rings"} <= db.available() else {}
    return {"corpus": corpus, "ratings": ratings, "histogram": histogram,
            "clusters": clusters}


@app.get("/timeline")
@db.memo
def global_timeline(bucket: int = Query(30, ge=1, le=365)) -> dict:
    """Global review volume, bucketed. This is the de-trending baseline."""
    _require("baseline")
    return {"bucket_days": bucket, "series": db.rows(f"""
        SELECT (day / {bucket})::INTEGER * {bucket} AS day,
               sum(n_reviews)::BIGINT AS n_reviews,
               sum(n_products)::BIGINT AS n_products
        FROM baseline GROUP BY 1 ORDER BY 1""")}


# ---------------------------------------------------------------- reviewers
@app.get("/reviewers")
def reviewers(limit: int = Query(db.DEFAULT_LIMIT), offset: int = Query(0),
              sort: str | None = None, dir: str | None = "desc",
              min_score: float = Query(0.0, ge=0.0, le=1.0),
              max_score: float = Query(1.0, ge=0.0, le=1.0),
              min_reviews: int = Query(0, ge=0),
              in_ring: bool | None = None, q: str | None = None) -> dict:
    _require("scores")
    limit, offset = db.clamp(limit, offset)
    where = ["score BETWEEN ? AND ?", "n_reviews >= ?"]
    params: list = [min_score, max_score, min_reviews]
    if in_ring is True:
        where.append("ring_size > 0")
    elif in_ring is False:
        where.append("ring_size = 0")
    if q:
        where.append("(reviewerID ILIKE ? OR reviewer_name ILIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    clause = " AND ".join(where)
    total = db.one(f"SELECT count(*) AS n FROM scores WHERE {clause}", params)["n"]
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": db.rows(
            f"SELECT * FROM scores WHERE {clause} "
            f"{db.order_by('reviewers', sort, dir, 'score')} LIMIT {limit} OFFSET {offset}",
            params),
    }


@app.get("/reviewers/{reviewer_sk}")
def reviewer_detail(reviewer_sk: int, reviews: int = Query(25, ge=1, le=200)) -> dict:
    _require("scores", "feat_reviewer", "contributions")
    profile = db.one("SELECT * FROM scores WHERE reviewer_sk = ?", [reviewer_sk])
    if profile is None:
        raise HTTPException(404, "reviewer not found")
    features = db.one("SELECT * FROM feat_reviewer WHERE reviewer_sk = ?", [reviewer_sk])
    contribution = db.one("SELECT * FROM contributions WHERE reviewer_sk = ?", [reviewer_sk])
    contribution = {k: v for k, v in (contribution or {}).items() if k != "reviewer_sk"}
    families = db.meta().get("families", {})
    # Pick the reviews first, then fetch text for just those: see db.raw_text.
    recent = db.rows(f"""
        SELECT f.review_sk, f.day, f.rating, f.n_words, f.helpful_yes, f.helpful_total,
               p.asin
        FROM fact f
        JOIN dim_product p USING (product_sk)
        WHERE f.reviewer_sk = ?
        ORDER BY f.day DESC LIMIT {reviews}""", [reviewer_sk])
    texts = db.raw_text([r["review_sk"] for r in recent])
    for r in recent:
        t = texts.get(r["review_sk"]) or {}
        r["snippet"] = (t.get("reviewText") or "").replace("\n", " ")[:db.SNIPPET_CHARS]
        r["summary"] = t.get("summary")
    return {"profile": profile, "features": features,
            "contributions": [{"feature": k, "percentile": v,
                               "family": next((f for f, m in families.items() if k in m), "?")}
                              for k, v in sorted(contribution.items(),
                                                 key=lambda kv: -(kv[1] or 0))],
            "recent_reviews": recent}


@app.get("/reviewers/{reviewer_sk}/timeline")
def reviewer_timeline(reviewer_sk: int) -> dict:
    """Every dated review by this account: when, what rating, how long.

    Reads the fact table only -- no text -- so it stays cheap even for the
    23,851-review account.
    """
    _require("fact")
    return {"points": db.rows("""
        SELECT f.day, f.rating, f.n_words, f.helpful_yes, f.helpful_total,
               p.asin, f.product_sk
        FROM fact f JOIN dim_product p USING (product_sk)
        WHERE f.reviewer_sk = ? AND f.day IS NOT NULL
        ORDER BY f.day""", [reviewer_sk])}


# -------------------------------------------------------------------- rings
@app.get("/rings")
def ring_list(limit: int = Query(db.DEFAULT_LIMIT), offset: int = Query(0),
              sort: str | None = None, dir: str | None = "desc",
              min_members: int = Query(3, ge=2)) -> dict:
    _require("rings")
    limit, offset = db.clamp(limit, offset)
    total = db.one("SELECT count(*) AS n FROM rings WHERE n_members >= ?",
                   [min_members])["n"]
    return {"total": total, "limit": limit, "offset": offset,
            "items": db.rows(
                f"SELECT * FROM rings WHERE n_members >= ? "
                f"{db.order_by('rings', sort, dir, 'density')} "
                f"LIMIT {limit} OFFSET {offset}", [min_members])}


@app.get("/rings/{ring_id}")
def ring_detail(ring_id: int, max_nodes: int = Query(200, ge=2, le=500)) -> dict:
    """Members plus the induced subgraph, capped so the browser can draw it."""
    _require("rings", "ring_members", "coreview_edges")
    ring = db.one("SELECT * FROM rings WHERE ring_id = ?", [ring_id])
    if ring is None:
        raise HTTPException(404, "ring not found")
    members = db.rows(f"""
        SELECT m.reviewer_sk, d.reviewerID, d.reviewer_name, m.coreview_degree,
               m.coreview_weight, s.score, s.score_text, s.score_behaviour, s.score_graph,
               r.n_reviews, r.max_per_day, r.lifespan_days, r.mean_rating
        FROM ring_members m
        JOIN dim_reviewer d USING (reviewer_sk)
        LEFT JOIN scores s USING (reviewer_sk)
        LEFT JOIN feat_reviewer r USING (reviewer_sk)
        WHERE m.ring_id = ? ORDER BY m.coreview_weight DESC LIMIT {max_nodes}""", [ring_id])
    ids = [m["reviewer_sk"] for m in members]
    edges = db.rows(
        f"SELECT r1, r2, shared FROM coreview_edges WHERE r1 IN ({','.join('?' * len(ids))}) "
        f"AND r2 IN ({','.join('?' * len(ids))})", ids + ids) if ids else []
    shared_products = db.rows(f"""
        SELECT p.asin, f.product_sk, count(*)::INTEGER AS n_ring_reviews,
               avg(f.rating::DOUBLE) AS mean_rating, min(f.day) AS first_day,
               max(f.day) AS last_day
        FROM fact f JOIN dim_product p USING (product_sk)
        WHERE f.reviewer_sk IN ({','.join('?' * len(ids))})
        GROUP BY 1, 2 HAVING count(*) > 1
        ORDER BY n_ring_reviews DESC LIMIT 50""", ids) if ids else []
    return {"ring": ring, "members": members, "edges": edges,
            "shared_products": shared_products,
            "truncated": ring["n_members"] > len(members)}


@app.get("/rings/{ring_id}/convergence")
def ring_convergence(ring_id: int, max_products: int = Query(40, ge=5, le=120)) -> dict:
    """When each ring member reviewed each shared product.

    This is the exhibit: one row per product, one dot per member review. A ring
    shows up as vertical stacks -- many accounts hitting the same product within
    days -- which no table of aggregates conveys as directly.
    """
    _require("rings", "ring_members", "fact")
    if db.one("SELECT 1 AS x FROM rings WHERE ring_id = ?", [ring_id]) is None:
        raise HTTPException(404, "ring not found")
    products = db.rows(f"""
        SELECT f.product_sk, p.asin,
               count(*)::INTEGER AS n_reviews,
               count(DISTINCT f.reviewer_sk)::INTEGER AS n_members,
               min(f.day) AS first_day, max(f.day) AS last_day,
               avg(f.rating::DOUBLE) AS mean_rating
        FROM ring_members m
        JOIN fact f USING (reviewer_sk)
        JOIN dim_product p USING (product_sk)
        WHERE m.ring_id = ? AND f.day IS NOT NULL
        GROUP BY 1, 2 HAVING count(DISTINCT f.reviewer_sk) > 1
        ORDER BY n_members DESC, (max(f.day) - min(f.day)) ASC
        LIMIT {max_products}""", [ring_id])
    if not products:
        return {"products": [], "reviews": [], "members": []}
    ids = [p["product_sk"] for p in products]
    reviews = db.rows(f"""
        SELECT f.product_sk, f.reviewer_sk, f.day, f.rating
        FROM ring_members m JOIN fact f USING (reviewer_sk)
        WHERE m.ring_id = ? AND f.product_sk IN ({','.join('?' * len(ids))})
          AND f.day IS NOT NULL
        ORDER BY f.day""", [ring_id, *ids])
    members = db.rows("""
        SELECT m.reviewer_sk, d.reviewerID
        FROM ring_members m JOIN dim_reviewer d USING (reviewer_sk)
        WHERE m.ring_id = ? ORDER BY m.reviewer_sk""", [ring_id])
    return {"products": products, "reviews": reviews, "members": members}


# --------------------------------------------------------------- duplicates
@app.get("/duplicates")
def duplicate_clusters(kind: str = Query("exact", pattern="^(exact|loose|tight)$"),
                       limit: int = Query(db.DEFAULT_LIMIT), offset: int = Query(0),
                       sort: str | None = None, dir: str | None = "desc",
                       cross_reviewer: bool = True, substantive: bool = True) -> dict:
    limit, offset = db.clamp(limit, offset)
    if kind == "exact":
        _require("dup_clusters")
        where = ["true"]
        if cross_reviewer:
            where.append("is_cross_reviewer")
        if substantive:
            where.append("is_substantive")
        clause = " AND ".join(where)
        total = db.one(f"SELECT count(*) AS n FROM dup_clusters WHERE {clause}")["n"]
        items = db.rows(f"SELECT * FROM dup_clusters WHERE {clause} "
                        f"{db.order_by('duplicates', sort, dir, 'n_reviewers')} "
                        f"LIMIT {limit} OFFSET {offset}")
    else:
        _require("neardup_clusters")
        where = ["config = ?"]
        params = [kind]
        if cross_reviewer:
            where.append("n_reviewers > 1")
        clause = " AND ".join(where)
        total = db.one(f"SELECT count(*) AS n FROM neardup_clusters WHERE {clause}",
                       params)["n"]
        items = db.rows(f"SELECT * FROM neardup_clusters WHERE {clause} "
                        f"{db.order_by('neardup', sort, dir, 'n_reviewers')} "
                        f"LIMIT {limit} OFFSET {offset}", params)
    return {"kind": kind, "total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/duplicates/{kind}/{cluster_id}")
def duplicate_detail(kind: str, cluster_id: int, limit: int = Query(40, ge=2, le=200)) -> dict:
    """The full text of every member, for side-by-side comparison."""
    if kind not in ("exact", "loose", "tight"):
        raise HTTPException(400, "kind must be exact, loose or tight")
    # Members first from the small cluster tables, then text for just those reviews.
    if kind == "exact":
        _require("dup_clusters", "dup_members")
        cluster = db.one("SELECT * FROM dup_clusters WHERE cluster_id = ?", [cluster_id])
        members = db.rows(f"""
            SELECT m.review_sk, m.reviewer_sk, d.reviewerID, d.reviewer_name,
                   p.asin, m.day, m.rating, 1.0 AS jaccard
            FROM dup_members m
            JOIN dim_reviewer d USING (reviewer_sk)
            JOIN dim_product p USING (product_sk)
            WHERE m.cluster_id = ? ORDER BY m.day LIMIT {limit}""", [cluster_id])
    else:
        _require("neardup_clusters", "neardup_members")
        cluster = db.one("SELECT * FROM neardup_clusters WHERE config = ? "
                         "AND cluster_id = ?", [kind, cluster_id])
        members = db.rows(f"""
            SELECT m.review_sk, m.reviewer_sk, d.reviewerID, d.reviewer_name,
                   p.asin, m.day, m.rating, m.jaccard
            FROM neardup_members m
            JOIN dim_reviewer d USING (reviewer_sk)
            JOIN dim_product p USING (product_sk)
            WHERE m.config = ? AND m.cluster_id = ?
            ORDER BY m.jaccard DESC LIMIT {limit}""", [kind, cluster_id])
    texts = db.raw_text([m["review_sk"] for m in members])
    for m in members:
        t = texts.get(m["review_sk"]) or {}
        m["reviewText"] = t.get("reviewText")
        m["summary"] = t.get("summary")
    if cluster is None:
        raise HTTPException(404, "cluster not found")
    return {"kind": kind, "cluster": cluster, "members": members}


# ----------------------------------------------------------------- products
@app.get("/products/{key}")
def product_detail(key: str) -> dict:
    """`key` is a product_sk, or an ASIN -- links arrive in both forms."""
    _require("feat_product", "baseline")
    by_asin = not key.isdigit()
    product = db.one(f"""
        SELECT fp.*, dp.asin, pc.pg_degree, pc.pg_pagerank, pc.pg_eigen
        FROM feat_product fp JOIN dim_product dp USING (product_sk)
        LEFT JOIN product_centrality pc USING (product_sk)
        WHERE {'dp.asin' if by_asin else 'fp.product_sk'} = ?""",
                     [key if by_asin else int(key)])
    if product is None:
        raise HTTPException(404, "product not found")
    product_sk = int(product["product_sk"])
    total = db.one("SELECT sum(n_reviews) AS n FROM baseline")["n"]
    # Daily counts alongside the de-trended expectation, so the chart can draw the
    # baseline underneath the observed series rather than asserting a burst.
    series = db.rows(f"""
        WITH d AS (SELECT day, count(*)::INTEGER AS c, avg(rating::DOUBLE) AS mean_rating
                   FROM fact WHERE product_sk = ? AND day IS NOT NULL GROUP BY 1)
        SELECT d.day, d.c AS n_reviews, d.mean_rating,
               greatest({product['n_reviews']} * b.n_reviews::DOUBLE / {total}, 1.0)
                 AS expected,
               (d.c - greatest({product['n_reviews']} * b.n_reviews::DOUBLE / {total}, 1.0))
                 / sqrt(greatest({product['n_reviews']} * b.n_reviews::DOUBLE / {total}, 1.0))
                 AS z
        FROM d JOIN baseline b USING (day) ORDER BY d.day""", [product_sk])
    return {"product": product, "series": series}


@app.get("/products/{key}/ratings")
def product_ratings(key: str) -> dict:
    """Rating histogram for one product, for the donut."""
    _require("fact")
    by_asin = not key.isdigit()
    column = "p.asin" if by_asin else "f.product_sk"
    return {"ratings": db.rows(f"""
        SELECT f.rating, count(*)::BIGINT AS n
        FROM fact f JOIN dim_product p USING (product_sk)
        WHERE {column} = ?
        GROUP BY 1 ORDER BY 1""", [key if by_asin else int(key)])}


@app.get("/products")
def product_list(limit: int = Query(db.DEFAULT_LIMIT), offset: int = Query(0),
                 min_reviews: int = Query(10, ge=1)) -> dict:
    _require("feat_product")
    limit, offset = db.clamp(limit, offset)
    total = db.one("SELECT count(*) AS n FROM feat_product WHERE n_reviews >= ?",
                   [min_reviews])["n"]
    return {"total": total, "limit": limit, "offset": offset, "items": db.rows(f"""
        SELECT fp.product_sk, dp.asin, fp.n_reviews, fp.mean_rating, fp.max_daily_z,
               fp.max_7d_z, fp.peak_day, fp.dup_text_rate, fp.rating_shift
        FROM feat_product fp JOIN dim_product dp USING (product_sk)
        WHERE fp.n_reviews >= ? ORDER BY fp.max_daily_z DESC
        LIMIT {limit} OFFSET {offset}""", [min_reviews])}


@app.exception_handler(HTTPException)
def _http_error(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
