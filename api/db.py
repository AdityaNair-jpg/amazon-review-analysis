"""Read-only DuckDB access for the API.

One connection is opened at startup with views over the Parquet artifacts; every
request gets its own cursor off it, which is DuckDB's thread-safe pattern and
lets FastAPI serve blocking queries from its threadpool.

Two guardrails live here rather than in the route handlers, so they cannot be
forgotten when a new endpoint is added:

  * SORTABLE -- a server-side whitelist. User-supplied column names are never
    interpolated into SQL; anything not on the list is rejected.
  * HEAVY -- a single-slot semaphore. The one genuinely expensive query shape
    (scanning the 9.7 GB raw text parquet for review bodies) is serialised, so a
    burst of requests cannot put the whole box into swap.
"""
from __future__ import annotations

import functools
import json
import threading
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Only these columns may be sorted or filtered on, per table. Anything else is a
# 400, not an interpolation.
SORTABLE = {
    "reviewers": {"score", "score_any", "score_text", "score_behaviour", "score_graph", "n_reviews",
                  "max_per_day", "lifespan_days", "mean_rating", "ring_size", "first_day",
                  "last_day"},
    "rings": {"density", "n_members", "n_products", "n_reviews", "span_days",
              "mean_shared", "mean_rating", "first_day"},
    "duplicates": {"n_reviewers", "n_reviews", "n_products", "n_words", "span_days",
                   "mean_rating", "cluster_id"},
    "neardup": {"n_reviewers", "n_reviews", "n_products", "mean_jaccard", "span_days",
                "mean_rating", "cluster_id"},
}

DEFAULT_LIMIT = 50
MAX_LIMIT = 1_000
SNIPPET_CHARS = 160
STATEMENT_TIMEOUT_S = 30

HEAVY = threading.Semaphore(1)

# connect() is called from FastAPI's threadpool, so several requests can race
# into it on the first burst after startup. Without the lock each thread builds
# its own view set and one of them can be observed half-built -- which showed up
# as an intermittent 503 "pipeline artifacts not built: fact" on the very first
# page load, and nowhere else.
_LOCK = threading.Lock()
_connection: duckdb.DuckDBPyConnection | None = None
_views: frozenset[str] | None = None
_meta: dict | None = None


def _view(name: str, path: Path) -> str | None:
    return (f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM '{path.as_posix()}'"
            if path.exists() else None)


def connect() -> duckdb.DuckDBPyConnection:
    """Open the read-only analytical view set. Idempotent and thread-safe."""
    global _connection
    if _connection is not None:
        return _connection
    with _LOCK:
        if _connection is not None:
            return _connection
        _connection = _build()
    return _connection


def _build() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{(DATA / 'tmp').as_posix()}'")
    con.execute("SET memory_limit = '4GB'")   # the API is a reader; the pipeline owns the box
    con.execute("SET threads = 4")
    con.execute("SET preserve_insertion_order = false")

    views = {
        "fact": DATA / "fact" / "fact_reviews.parquet",
        "dim_reviewer": DATA / "dim" / "dim_reviewer.parquet",
        "dim_product": DATA / "dim" / "dim_product.parquet",
        "feat_reviewer": DATA / "features" / "feat_reviewer.parquet",
        "feat_product": DATA / "features" / "feat_product.parquet",
        "baseline": DATA / "features" / "baseline_daily_volume.parquet",
        "dup_clusters": DATA / "features" / "dup_clusters.parquet",
        "dup_members": DATA / "features" / "dup_members.parquet",
        "neardup_clusters": DATA / "features" / "neardup_clusters.parquet",
        "neardup_members": DATA / "features" / "neardup_members.parquet",
        "rings": DATA / "graph" / "rings.parquet",
        "ring_members": DATA / "graph" / "ring_members.parquet",
        "coreview_edges": DATA / "graph" / "coreview_edges.parquet",
        "product_centrality": DATA / "graph" / "product_centrality.parquet",
        "scores": DATA / "scores" / "reviewer_scores.parquet",
        "contributions": DATA / "scores" / "reviewer_contributions.parquet",
        "score_histogram": DATA / "scores" / "score_histogram.parquet",
        # --- inverted index (pipeline/13_index.py) ---
        "postings": DATA / "ir" / "postings.parquet",
        "dictionary": DATA / "ir" / "dictionary.parquet",
        # The Parquet result store from stage 13b. Search does NOT read this any more
        # -- api/docblob.py does, from a flat file -- but it stays registered because
        # it is the SQL-queryable copy of the same rows and the fallback if the blob
        # has not been built. review_sk is a virtual column in `raw` and `fact` is
        # sorted by reviewer_sk, so neither of those can prune on it at all.
        "docstore": DATA / "ir" / "docstore.parquet",
        # --- the suspicious network (pipeline/15_story_network.py) ---
        "group_docs": DATA / "story" / "group_docs.parquet",
    }
    for name, path in views.items():
        statement = _view(name, path)
        if statement:
            con.execute(statement)

    # Document lengths used to be materialised here, because BM25 joined them on every
    # query. They are now folded into the postings' impact column at index time, so this
    # is back to being an ordinary view -- 330 MB of resident memory returned, on a box
    # where that matters.
    doc_stats = DATA / "ir" / "doc_stats.parquet"
    if doc_stats.exists():
        con.execute(f"CREATE OR REPLACE VIEW doc_len AS "
                    f"SELECT doc_id, doc_len FROM '{doc_stats.as_posix()}'")

    raw = DATA / "raw" / "reviews.parquet"
    if raw.exists():
        con.execute(
            f"CREATE OR REPLACE VIEW raw AS SELECT file_row_number::BIGINT AS review_sk, "
            f"reviewerID, asin, reviewerName, reviewText, summary, rating, n_chars, n_words "
            f"FROM read_parquet('{raw.as_posix()}', file_row_number=true)")
    return con


def available() -> frozenset[str]:
    """Which relations exist, views and tables alike.

    Both, because an earlier version listed only views while doc_len was materialised
    as a table, and every search request was rejected with "index not built" while the
    index sat right there on disk. Nothing is materialised at the moment, but the
    failure was quiet enough to be worth not re-enabling by accident.

    Cached, because the artifact set cannot change at runtime and this is called on
    nearly every request.
    """
    global _views
    if _views is None:
        con = connect()
        with _LOCK:
            _views = frozenset(r[0] for r in con.execute(
                "SELECT view_name AS name FROM duckdb_views() WHERE internal = false "
                "UNION ALL "
                "SELECT table_name FROM duckdb_tables() WHERE internal = false").fetchall())
    return _views


def meta() -> dict:
    """Score metadata written by pipeline/09_score.py."""
    global _meta
    if _meta is None:
        path = DATA / "scores" / "score_meta.json"
        _meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _meta


def memo(fn):
    """Cache an endpoint's result for the life of the process, computed once per key.

    Every chart and overview endpoint is a fixed aggregate over artifacts that cannot
    change while the API is up, yet each one was recomputed on every page render.
    That turned out to matter: a harness health-checking `HEAD /` every few seconds
    re-rendered the homepage each time, each render queued several chart queries,
    and the API climbed to 4.5 GB and stopped answering even /health.

    The per-key lock is the important part. A plain cache still lets a burst of
    identical first requests all miss and all compute; here the first computes and
    the rest wait for its answer.
    """
    results: dict = {}
    locks: dict = {}
    guard = threading.Lock()

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        key = (args, tuple(sorted(kwargs.items())))
        if key in results:
            return results[key]
        with guard:
            lock = locks.setdefault(key, threading.Lock())
        with lock:
            if key not in results:
                if len(results) >= 512:        # parameters are bounded; this is a backstop
                    results.clear()
                results[key] = fn(*args, **kwargs)
        return results[key]

    return wrapper


def raw_text(review_sks: list[int]) -> dict[int, dict]:
    """Summary and full text for specific reviews, fetched by id after they are chosen.

    The pages that show review text used to JOIN the 9.7 GB archive straight onto their
    row list. DuckDB then matched every review in the archive before applying the
    LIMIT, which took 24-40 s for one account page. Choosing the rows first from the
    small tables and fetching text for just those ids takes about 2 s. review_sk is a
    virtual row number in `raw`, so even this cannot skip row groups; it is the HEAVY
    semaphore's job to keep two of these from running at once.
    """
    ids = sorted({int(v) for v in review_sks})
    if not ids or "raw" not in available():
        return {}
    with HEAVY:
        found = rows(f"SELECT review_sk, summary, reviewText FROM raw "
                     f"WHERE review_sk IN ({','.join(str(i) for i in ids)})")
    return {r["review_sk"]: r for r in found}


def cursor():
    return connect().cursor()


def rows(sql: str, params: list | None = None) -> list[dict]:
    """Run a query and return a list of dicts, with numpy scalars made JSON-safe."""
    cur = cursor()
    cur.execute(sql, params or [])
    columns = [d[0] for d in cur.description]
    out = []
    for record in cur.fetchall():
        out.append({c: (v.item() if hasattr(v, "item") else v)
                    for c, v in zip(columns, record)})
    return out


def one(sql: str, params: list | None = None) -> dict | None:
    result = rows(sql, params)
    return result[0] if result else None


def clamp(limit: int | None, offset: int | None) -> tuple[int, int]:
    return (min(max(int(limit or DEFAULT_LIMIT), 1), MAX_LIMIT), max(int(offset or 0), 0))


def order_by(table: str, sort: str | None, direction: str | None, fallback: str) -> str:
    """Validate a sort request against the whitelist and build the ORDER BY clause."""
    column = sort if sort in SORTABLE.get(table, set()) else fallback
    return f"ORDER BY {column} {'ASC' if (direction or 'desc').lower() == 'asc' else 'DESC'}"
