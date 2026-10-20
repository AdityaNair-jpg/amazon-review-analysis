"""Aggregate endpoints that exist purely to feed charts.

Every one of these returns a bounded number of points -- at most a few thousand --
because the browser cannot usefully draw more and shipping more would only make
the page slower. Where a chart needs to represent 3M accounts, the reduction
happens in DuckDB (binning, stratified sampling) rather than in React.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api import db, docblob

router = APIRouter(prefix="/charts")

SCATTER_POINTS = 4_000
HEATMAP_SAMPLE = 1_000_000
# Below this many active rows a pair's correlation is noise; the cell is returned
# as null and drawn as "not measurable" rather than as a number.
MIN_ACTIVE_FOR_CORRELATION = 2_000


@router.get("/volume")
@db.memo
def corpus_volume(bucket: int = Query(90, ge=7, le=365)) -> dict:
    """Corpus review volume over time, split by rating.

    This is the chart that justifies de-trending: 2013 alone carries 14.79M of the
    41.1M reviews, so any raw burst detector is really a 2013 detector.
    """
    db_views = db.available()
    if "fact" not in db_views:
        raise HTTPException(503, "fact table not built")
    return {"bucket_days": bucket, "series": db.rows(f"""
        SELECT (day / {bucket})::INTEGER * {bucket} AS day,
               count(*) FILTER (WHERE rating = 1)::INTEGER AS r1,
               count(*) FILTER (WHERE rating = 2)::INTEGER AS r2,
               count(*) FILTER (WHERE rating = 3)::INTEGER AS r3,
               count(*) FILTER (WHERE rating = 4)::INTEGER AS r4,
               count(*) FILTER (WHERE rating = 5)::INTEGER AS r5,
               count(*)::INTEGER AS total,
               avg(rating::DOUBLE) AS mean_rating
        FROM fact WHERE day IS NOT NULL GROUP BY 1 ORDER BY 1""")}


@router.get("/rating-by-decile")
@db.memo
def rating_by_decile() -> dict:
    """Rating mix within each suspicion decile.

    If flagged accounts really do skew positive, it shows here -- and if they do
    not, that is worth knowing too, since no rating level enters the score.
    """
    return {"deciles": db.rows("""
        WITH d AS (
            SELECT s.reviewer_sk, ntile(10) OVER (ORDER BY s.score) AS decile
            FROM scores s
        )
        SELECT d.decile,
               count(*)::BIGINT AS n_reviews,
               avg(f.rating::DOUBLE) AS mean_rating,
               count(*) FILTER (WHERE f.rating = 5)::DOUBLE / count(*) AS frac_5,
               count(*) FILTER (WHERE f.rating = 1)::DOUBLE / count(*) AS frac_1,
               count(*) FILTER (WHERE f.rating IN (1, 5))::DOUBLE / count(*) AS frac_extreme
        FROM d JOIN fact f USING (reviewer_sk)
        GROUP BY 1 ORDER BY 1""")}


@router.get("/family-composition")
@db.memo
def family_composition(k: int = Query(10_000, ge=100, le=500_000)) -> dict:
    """A three-way Venn breakdown of each family's own top-k accounts.

    Answers the question the whole score design rests on: is there ONE population
    of suspicious accounts that all three families see, or three largely separate
    ones? Measured here, it is closer to three -- which is why this is a chart on
    the front page rather than a footnote in the methodology.
    """
    rows = db.rows(f"""
        WITH r AS (
            SELECT row_number() OVER (ORDER BY score_text DESC)      AS rt,
                   row_number() OVER (ORDER BY score_behaviour DESC) AS rb,
                   row_number() OVER (ORDER BY score_graph DESC)     AS rg
            FROM scores
        )
        SELECT (rt <= {k})::INTEGER AS t, (rb <= {k})::INTEGER AS b,
               (rg <= {k})::INTEGER AS g, count(*)::BIGINT AS n
        FROM r WHERE rt <= {k} OR rb <= {k} OR rg <= {k}
        GROUP BY 1, 2, 3""")
    label = {(1, 0, 0): "Text only", (0, 1, 0): "Behaviour only", (0, 0, 1): "Graph only",
             (1, 1, 0): "Text + Behaviour", (1, 0, 1): "Text + Graph",
             (0, 1, 1): "Behaviour + Graph", (1, 1, 1): "All three"}
    segments = [{"label": label[(r["t"], r["b"], r["g"])], "n": r["n"],
                 "families": r["t"] + r["b"] + r["g"]}
                for r in rows if (r["t"], r["b"], r["g"]) in label]
    union = sum(s["n"] for s in segments)
    return {"k": k, "union": union,
            "expected_if_identical": k,
            "expected_if_independent": 3 * k - union if union else None,
            "segments": sorted(segments, key=lambda s: (-s["families"], -s["n"]))}


@router.get("/reviewer-scatter")
@db.memo
def reviewer_scatter(min_reviews: int = Query(5, ge=5)) -> dict:
    """Burst intensity against rating deviation, stratified across score bands.

    A plain random sample would be 99% ordinary accounts and would hide the tail
    entirely, so points are drawn evenly from ten score bands and the band is
    carried through so the chart can colour by it.
    """
    per_band = SCATTER_POINTS // 10
    return {"points": db.rows(f"""
        WITH j AS (
            SELECT s.reviewer_sk, s.score,
                   r.max_in_7d, r.loo_rating_dev, r.n_reviews, r.lifespan_days,
                   least(9, (s.score * 10)::INTEGER) AS band,
                   row_number() OVER (PARTITION BY least(9, (s.score * 10)::INTEGER)
                                      ORDER BY hash(s.reviewer_sk)) AS rn
            FROM scores s JOIN feat_reviewer r USING (reviewer_sk)
            WHERE r.n_reviews >= {min_reviews}
        )
        SELECT reviewer_sk, band,
               round(score, 3)          AS score,
               max_in_7d,
               round(loo_rating_dev, 3) AS loo_rating_dev,
               n_reviews, lifespan_days
        FROM j WHERE rn <= {per_band}""")}


@router.get("/ring-scatter")
@db.memo
def ring_scatter() -> dict:
    """Every ring as a point: members against density, sized by review count."""
    return {"rings": db.rows("""
        SELECT ring_id, n_members, density, n_reviews, n_products, span_days,
               mean_rating, mean_shared, first_day
        FROM rings ORDER BY n_members DESC""")}


@router.get("/cluster-sizes")
@db.memo
def cluster_sizes() -> dict:
    """Size distribution of duplicate and near-duplicate clusters, log-binned."""
    out: dict[str, list] = {}
    sources = [("exact", "SELECT n_reviewers AS k FROM dup_clusters"),
               ("loose", "SELECT n_reviewers AS k FROM neardup_clusters WHERE config='loose'"),
               ("tight", "SELECT n_reviewers AS k FROM neardup_clusters WHERE config='tight'")]
    for name, sql in sources:
        if (name == "exact" and "dup_clusters" not in db.available()) or \
           (name != "exact" and "neardup_clusters" not in db.available()):
            continue
        out[name] = db.rows(
            f"SELECT k AS accounts, count(*)::BIGINT AS n FROM ({sql}) "
            f"GROUP BY 1 ORDER BY 1")
    jaccard = db.rows("""
        SELECT config, round(mean_jaccard, 2) AS j, count(*)::BIGINT AS n
        FROM neardup_clusters GROUP BY 1, 2 ORDER BY 1, 2
    """) if "neardup_clusters" in db.available() else []
    return {"sizes": out, "jaccard": jaccard}


@router.get("/correlation")
@db.memo
def correlation() -> dict:
    """The feature correlation matrix, served straight from the cull that used it.

    This is deliberately NOT recomputed here. pipeline/09_score.py persists the
    exact matrix its collinearity cull acted on, and the chart reads that, so the
    two can never disagree.

    Recomputing it in the API looks harmless and is not. The cull measures each
    pair on its ACTIVE SUBSET -- rows where at least one of the two raw features
    is non-zero -- because most graph and duplicate features are zero for well
    over 99% of accounts, and a correlation taken across that mass of shared
    zeros returns 1.000 for any two sparse features whether or not they carry the
    same signal. An independent recomputation over the stored percentile columns
    cannot reproduce that filter at all, because the ECDF maps a raw zero to a
    non-zero percentile. The first version of this endpoint did exactly that and
    the resulting chart accused the cull of a bug it does not have.
    """
    meta = db.meta()
    stored = meta.get("correlation")
    if not stored:
        raise HTTPException(
            503, "correlation matrix not in score_meta.json -- re-run pipeline/09_score.py")

    kept = meta.get("kept_features", [])
    names = stored["features"]
    keep_index = [names.index(f) for f in kept if f in names]
    features = [names[i] for i in keep_index]
    matrix = [[stored["matrix"][i][j] for j in keep_index] for i in keep_index]
    active = [[stored["active_rows"][i][j] for j in keep_index] for i in keep_index]

    return {"features": features,
            "families": {f: next((k for k, v in meta["families"].items() if f in v), "?")
                         for f in features},
            "matrix": matrix,
            "active_rows": active,
            "sample": stored.get("sample_rows"),
            "min_active": meta.get("min_active_for_cull", 2_000)}


@router.get("/agreement")
@db.memo
def agreement() -> dict:
    """Observed vs chance-expected three-family overlap at several cut-offs."""
    a = db.meta().get("agreement", {})
    rows = []
    for k in (1_000, 10_000, 100_000, 300_000):
        for label, key in (("T & B", "TB"), ("T & G", "TG"), ("B & G", "BG"),
                           ("all three", "TBG")):
            observed = a.get(f"overlap_{key}_at_{k}")
            expected = a.get(f"overlap_{key}_at_{k}_expected")
            if observed is None or expected is None:
                continue
            rows.append({"k": k, "pair": label, "observed": observed,
                         "expected": expected,
                         "lift": round(observed / expected, 2) if expected else None,
                         "informative": expected >= 5})
    return {"rows": rows,
            "spearman": {k: a[k] for k in ("spearman_TB", "spearman_TG", "spearman_BG")
                         if k in a}}


# Amazon's own "how to write a review" help text, which a dozen unrelated people
# pasted in as their review. These are the LARGEST cross-account text clusters in
# the corpus and they are not campaigns -- see docs/findings.md section 2. They
# are matched in Python against a handful of fetched exemplars rather than in SQL,
# because a LIKE over reviewText forces a read of all 9.7 GB (measured: 128s).
BOILERPLATE_PHRASES = (
    "do explain why you liked",
    "be detailed and specific",
    "what would you have wanted to know",
    "do compare to similar products",
    "make it fun! who says",
    "do identify specific attributes",
)

_highlights: dict | None = None


def _looks_like_boilerplate(text: str | None) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in BOILERPLATE_PHRASES)


@router.get("/highlights")
@db.memo
def highlights() -> dict:
    """The three clearest real examples in the corpus, chosen by query not by hand.

    The landing page leads with these rather than with methodology, because a
    first-time reader needs to see one concrete case before any of the machinery
    means anything. They are picked dynamically so they survive a rebuild -- ring
    ids and cluster ids change every time the pipeline runs -- and then cached,
    because they cannot change while the process is up.
    """
    global _highlights
    if _highlights is not None:
        return _highlights

    views = db.available()
    out: dict = {}

    # A tight, dense, uniformly-positive group: the clearest "these accounts move
    # together" case. Small enough to grasp, fully interlinked, short window.
    out["ring"] = db.one("""
        SELECT ring_id, n_members, n_products, n_reviews, density, mean_shared,
               span_days, mean_rating, first_day
        FROM rings
        WHERE n_members BETWEEN 5 AND 12 AND density >= 0.99
          AND span_days <= 200 AND mean_rating >= 4.8 AND n_products >= 8
        ORDER BY n_members DESC, n_products DESC, span_days ASC
        LIMIT 1""") if "rings" in views else None

    # Candidate text clusters, chosen on numbers only -- no text predicate, so this
    # reads the small cluster table and never touches the review archive.
    cluster = None
    if {"neardup_clusters", "raw"} <= views:
        candidates = db.rows("""
            SELECT cluster_id, config, n_reviewers, n_reviews, n_products,
                   mean_jaccard, span_days, mean_rating, exemplar_sk
            FROM neardup_clusters
            WHERE config = 'loose' AND n_reviewers >= 3 AND mean_jaccard >= 0.9
              AND mean_rating >= 4.5 AND span_days <= 400
            ORDER BY n_reviewers DESC, mean_jaccard DESC
            LIMIT 40""")
        if candidates:
            ids = [c["exemplar_sk"] for c in candidates]
            # review_sk is a virtual row number in `raw`, so DuckDB cannot prune on it
            # and this used to scan the whole 9.7 GB archive. The blob store from
            # stage 13c is a seek per document; `raw` remains only as the fallback.
            if docblob.available():
                texts = docblob.fetch(ids)
            else:
                with db.HEAVY:
                    texts = {
                        r["review_sk"]: r for r in db.rows(
                            f"SELECT review_sk, reviewText, summary, n_words FROM raw "
                            f"WHERE review_sk IN ({','.join('?' * len(ids))})", ids)
                    }
            for candidate in candidates:
                body = texts.get(candidate["exemplar_sk"])
                if not body or (body.get("n_words") or 0) < 60:
                    continue
                if _looks_like_boilerplate(body.get("reviewText")):
                    continue
                cluster = {**candidate,
                           "sample_text": body.get("reviewText"),
                           "sample_summary": body.get("summary")}
                break
    out["cluster"] = cluster

    # The starkest burst: an account whose entire history happened in one day.
    out["burst"] = db.one("""
        SELECT s.reviewer_sk, s.reviewerID, s.reviewer_name, s.score,
               r.n_reviews, r.max_per_day, r.lifespan_days, r.mean_rating
        FROM scores s JOIN feat_reviewer r USING (reviewer_sk)
        WHERE r.lifespan_days = 0 AND r.n_reviews >= 20
        ORDER BY r.n_reviews DESC LIMIT 1""") if "scores" in views else None

    out["totals"] = db.one("""
        SELECT (SELECT count(*) FROM rings)                                    AS rings,
               (SELECT sum(n_members) FROM rings)                              AS ring_accounts,
               (SELECT count(*) FROM rings WHERE density >= 0.999)             AS perfect_rings,
               (SELECT count(*) FROM neardup_clusters WHERE config = 'loose'
                  AND n_reviewers > 1)                                         AS copy_groups,
               (SELECT count(*) FROM scores WHERE score >= 0.99)               AS top_consensus,
               (SELECT count(*) FROM scores WHERE score_any >= 0.99)           AS top_any
    """) if {"rings", "neardup_clusters", "scores"} <= views else {}

    _highlights = out
    return out
