"""Full-text search over all 41,135,700 reviews, with the spam signals attached.

Ranking is BM25 (Robertson/Sparck Jones; Manning IIR ch. 11) evaluated in DuckDB over
the inverted index built by pipeline/13_index.py:

    score(q,d) = SUM_t  idf(t) * tf(t,d) * (k1 + 1)
                        ----------------------------------------
                        tf(t,d) + k1 * (1 - b + b * |d| / avgdl)

    idf(t)     = ln( 1 + (N - df(t) + 0.5) / (df(t) + 0.5) )

The whole right-hand factor is precomputed and stored per posting as `impact`, so what
runs here is SUM_t idf(t) * impact(t,d). That is not a shortcut: with raw term
frequencies stored instead, every query had to join its postings against all 41.1M
document lengths, and a four-term query spent 1.6 of its 2.0 seconds doing it.

The query is tokenised, stopped and Porter-stemmed with exactly the same code path the
index was built with -- a mismatch there is the classic way a search engine silently
returns nothing, so the constants are imported from the indexer rather than restated.

What makes this project's search different from a generic one: every hit is joined to
what the spam analysis already concluded about its author, and `demote` re-ranks to push
suspected coordinated reviews down. Ranking in the presence of parties gaming the
ranking is its own IR problem (IIR ch. 19), and here both halves are in one query.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from api import db, docblob

router = APIRouter(prefix="/search")

ROOT = Path(__file__).resolve().parent.parent
IR = ROOT / "data" / "ir"

# k1 and b are not applied here: the length normalisation they control is baked into
# the `impact` column at index time (pipeline/13_index.py). The values used are recorded
# in data/ir/index_meta.json, and changing them means re-running the merge.
CANDIDATE_DEPTH = 1_000     # BM25 shortlist before reranking or demotion
COMMON_TERM_FRACTION = 0.15  # a stem in more than this share of the corpus is ignored
RERANK_DEPTH = 50           # how many BM25 hits the cross-encoder re-reads
DEMOTE_DEPTH = 100          # how deep the spam penalty looks before cutting the page
GROUPS = ("core", "packs")  # search scopes, from pipeline/15_story_network.py
MAX_QUERY_TERMS = 12
SNIPPET_WINDOW = 320

_indexer = None
_meta: dict | None = None
_stemmer = None
_stem_cache: dict[str, str] = {}


def _load_indexer():
    """Import pipeline/13_index.py so the query uses the indexer's own tokeniser."""
    global _indexer
    if _indexer is None:
        path = ROOT / "pipeline" / "13_index.py"
        spec = importlib.util.spec_from_file_location("bda_indexer", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["bda_indexer"] = module
        spec.loader.exec_module(module)
        _indexer = module
    return _indexer


def meta() -> dict:
    global _meta
    if _meta is None:
        path = IR / "index_meta.json"
        if not path.exists():
            raise HTTPException(503, "search index not built -- run pipeline/13_index.py")
        _meta = json.loads(path.read_text(encoding="utf-8"))
    return _meta


def _stem(word: str) -> str:
    global _stemmer
    cached = _stem_cache.get(word)
    if cached is None:
        if _stemmer is None:
            from nltk.stem import PorterStemmer
            _stemmer = PorterStemmer()
        cached = _stemmer.stem(word)
        _stem_cache[word] = cached
    return cached


def analyse(query: str) -> list[str]:
    """Query analysis, identical to the index-time pipeline."""
    idx = _load_indexer()
    out, seen = [], set()
    for word in idx.TOKEN.findall((query or "").lower()):
        if len(word) < idx.MIN_TERM_LEN or len(word) > idx.MAX_TERM_LEN:
            continue
        if word in idx.STOPWORDS:
            continue
        stem = _stem(word)
        if stem not in seen:
            seen.add(stem)
            out.append(stem)
        if len(out) >= MAX_QUERY_TERMS:
            break
    return out


def _require_index() -> None:
    # doc_len is deliberately not required: the length normalisation it used to supply
    # at query time now lives in the postings' impact column.
    missing = [v for v in ("postings", "dictionary") if v not in db.available()]
    if missing:
        raise HTTPException(503, "search index not built -- run pipeline/13_index.py")


def resolve(stems: list[str]) -> list[dict]:
    """Look each stem up in the dictionary and attach its IDF."""
    if not stems:
        return []
    n = meta()["n_docs"]
    placeholders = ",".join("?" * len(stems))
    found = db.rows(
        f"SELECT term_id, term, df, ln(1 + ({n}::DOUBLE - df + 0.5) / (df + 0.5)) AS idf "
        f"FROM dictionary WHERE term IN ({placeholders})", stems)
    by_term = {r["term"]: r for r in found}
    return [by_term[s] for s in stems if s in by_term]


def split_by_selectivity(terms: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separate terms that narrow the search from terms that only cost time.

    23 stems appear in more than 15% of the corpus -- great, one, like, good, veri,
    love, book, time, work -- and between them they account for 10.9% of all 1.87
    billion postings. They are what makes a slow query slow: profiling a four-term
    query showed 201 ms of I/O and 878 ms building a hash table over 15.6 million
    candidate documents, 13.1 million of which matched only the word "great".

    Their idf is 1.14 to 1.89, against 3 to 8 for an ordinary content word, so they
    also contribute least to the ranking. Dropping them costs little and saves a lot.

    A term is only dropped if a selective one survives, so a search for "great" alone
    still searches for "great".

    Note on what was tried instead: champion lists (IIR 7.1.2) -- keeping each term's
    top-N postings by impact -- do not work on this corpus. Reviews average 58 terms,
    so tf is 1 for almost every posting, which makes "highest impact" mean "shortest
    document" rather than "most relevant". Measured on a four-term query, restricting
    candidate generation that way agreed with exact BM25 on 0 of the top 20.
    """
    if not terms:
        return [], []
    cut = meta()["n_docs"] * COMMON_TERM_FRACTION
    selective = [t for t in terms if t["df"] <= cut]
    if not selective:                       # every term is common: keep the rarest
        rarest = min(terms, key=lambda t: t["df"])
        return [rarest], [t for t in terms if t is not rarest]
    return selective, [t for t in terms if t["df"] > cut]


def bm25(terms: list[dict], depth: int, group: str | None = None) -> list[dict]:
    """Score the posting lists for these terms and return the top `depth` documents.

    `group` restricts scoring to the reviews written by one set of accounts -- the core
    or the packs of the suspicious network. The restriction is applied inside the
    scoring query rather than to its output: filtering the corpus-wide top 1,000
    afterwards would leave almost nothing, since the two groups wrote only 674k of the
    41.1M reviews (1.6%) -- the packs just 49k of them.
    """
    if not terms:
        return []
    ids = [t["term_id"] for t in terms]
    scope = ""
    if group is not None:
        if group not in GROUPS:
            raise HTTPException(400, f"group must be one of {', '.join(GROUPS)}")
        # Whitelisted above, so safe to interpolate.
        scope = (f" AND doc_id IN (SELECT review_sk FROM group_docs "
                 f"WHERE grp = '{group}')")
    # The index stores the length-normalised impact, not the raw term frequency, so
    # scoring is a multiply and a sum. Keeping tf here instead meant joining every
    # query's postings against all 41.1M document lengths: 2.0 s for four terms, of
    # which 1.6 s was the join. See the merge step in pipeline/13_index.py.
    #
    # Literals are cast explicitly: DuckDB reads a bare `1.234` as DECIMAL, and
    # DECIMAL(18) overflowed on the first multiplication when this was written
    # without the casts.
    if len(terms) == 1:
        # One term means one posting per document, so there is nothing to group. The
        # generic query below would still build a hash table over every document
        # containing the word -- 13.1 million of them for "great" -- purely to sum
        # one value each. Skipping it takes a single-word search from ~1,800 ms to
        # the cost of reading the posting list.
        term = terms[0]
        return db.rows(f"""
            SELECT doc_id,
                   {float(term['idf'])!r}::DOUBLE * impact::DOUBLE AS score,
                   1::INTEGER AS matched_terms
            FROM postings WHERE term_id = ?{scope}
            ORDER BY score DESC LIMIT {depth}""", [term["term_id"]])

    idf_rows = ", ".join(
        f"({t['term_id']}::INTEGER, {float(t['idf'])!r}::DOUBLE)" for t in terms)
    placeholders = ",".join("?" * len(ids))
    return db.rows(f"""
        WITH q(term_id, idf) AS (VALUES {idf_rows})
        SELECT p.doc_id,
               sum(q.idf * p.impact::DOUBLE) AS score,
               count(*)::INTEGER             AS matched_terms
        FROM postings p
        JOIN q USING (term_id)
        WHERE p.term_id IN ({placeholders}){scope.replace("doc_id", "p.doc_id")}
        GROUP BY p.doc_id
        ORDER BY score DESC
        LIMIT {depth}""", ids)


def hydrate(hits: list[dict], stems: list[str]) -> list[dict]:
    """Fetch text and the spam context for a bounded set of documents.

    Two steps rather than one wide join, for a measured reason. Fetching by review_sk
    from `raw` and `fact` cannot prune -- review_sk is a virtual row number in one and
    the other is sorted by reviewer_sk -- so a twenty-row lookup read whole files:
    954 ms, 948 ms, and 3.1 s once the spam tables were joined on top.

    Step one reads the documents themselves. That goes through the flat blob store from
    stage 13c when it exists -- a seek and a short read per document, against a ~250 ms
    floor for the same fetch in Parquet -- and falls back to the Parquet store built by
    stage 13b otherwise. Step two looks the spam context up by the few dozen keys step
    one returned, so DuckDB never builds a hash table over all of `scores` (3.0M rows)
    just to decorate twenty results.
    """
    if not hits:
        return []
    by_doc = {h["doc_id"]: h for h in hits}
    ids = list(by_doc)
    placeholders = ",".join("?" * len(ids))
    have = db.available()

    if docblob.available():
        found = docblob.fetch(ids)
        rows = [{"doc_id": doc_id, **record} for doc_id, record in found.items()]
        _attach_context(rows)
    elif "docstore" in have:
        rows = db.rows(f"""
            SELECT review_sk AS doc_id, reviewerID, reviewerName, asin,
                   summary, reviewText, rating, n_words,
                   helpful_yes, helpful_total, reviewer_sk, product_sk, day
            FROM docstore WHERE review_sk IN ({placeholders})""", ids)
        _attach_context(rows)
    else:
        # Before stage 13b has run. Correct, just slow.
        with db.HEAVY:
            rows = db.rows(f"""
                SELECT r.review_sk AS doc_id, r.reviewerID, r.reviewerName, r.asin,
                       r.summary, r.reviewText, r.rating, r.n_words,
                       f.helpful_yes, f.helpful_total,
                       f.reviewer_sk, f.product_sk, f.day,
                       s.score AS suspicion, s.score_text, s.score_behaviour,
                       s.score_graph, rm.ring_id, rm.ring_size,
                       nd.cluster_id AS neardup_cluster, nd.jaccard AS neardup_jaccard
                FROM raw r
                LEFT JOIN fact f  ON f.review_sk = r.review_sk
                LEFT JOIN scores s ON s.reviewer_sk = f.reviewer_sk
                LEFT JOIN ring_members rm ON rm.reviewer_sk = f.reviewer_sk
                LEFT JOIN (SELECT review_sk, cluster_id, jaccard FROM neardup_members
                           WHERE config = 'loose') nd ON nd.review_sk = r.review_sk
                WHERE r.review_sk IN ({placeholders})""", ids)

    out = []
    for row in rows:
        hit = by_doc[row["doc_id"]]
        text = row.pop("reviewText") or ""
        row["snippet"], row["matched"] = snippet(text, stems)
        row["n_chars"] = len(text)
        row["score"] = hit["score"]
        row["matched_terms"] = hit["matched_terms"]
        out.append(row)
    out.sort(key=lambda r: -r["score"])
    return out


CONTEXT_DEFAULTS = {
    "suspicion": None, "score_text": None, "score_behaviour": None,
    "score_graph": None, "ring_id": None, "ring_size": None,
    "neardup_cluster": None, "neardup_jaccard": None,
}


def _attach_context(rows: list[dict]) -> None:
    """Add the spam verdict to each row, looked up by the keys the rows carry.

    Three small lookups against three small tables, driven by at most a few dozen
    keys, instead of three LEFT JOINs that make DuckDB build hash tables over all of
    scores (3.0M rows) and neardup_members for every query.
    """
    for row in rows:
        row.update(CONTEXT_DEFAULTS)
    reviewers = sorted({r["reviewer_sk"] for r in rows if r["reviewer_sk"] is not None})
    docs = sorted({r["doc_id"] for r in rows})
    have = db.available()

    if reviewers:
        keys = ",".join(str(int(v)) for v in reviewers)

        if "scores" in have:
            score_by = {r["reviewer_sk"]: r for r in db.rows(
                f"SELECT reviewer_sk, score, score_text, score_behaviour, score_graph "
                f"FROM scores WHERE reviewer_sk IN ({keys})")}
            for row in rows:
                found = score_by.get(row["reviewer_sk"])
                if found:
                    row["suspicion"] = found["score"]
                    row["score_text"] = found["score_text"]
                    row["score_behaviour"] = found["score_behaviour"]
                    row["score_graph"] = found["score_graph"]

        if "ring_members" in have:
            ring_by = {r["reviewer_sk"]: r for r in db.rows(
                f"SELECT reviewer_sk, ring_id, ring_size FROM ring_members "
                f"WHERE reviewer_sk IN ({keys})")}
            for row in rows:
                ring = ring_by.get(row["reviewer_sk"])
                if ring:
                    row["ring_id"] = ring["ring_id"]
                    row["ring_size"] = ring["ring_size"]

    if docs and "neardup_members" in have:
        keys = ",".join(str(int(v)) for v in docs)
        dup_by = {r["review_sk"]: r for r in db.rows(
            f"SELECT review_sk, cluster_id, jaccard FROM neardup_members "
            f"WHERE config = 'loose' AND review_sk IN ({keys})")}
        for row in rows:
            dup = dup_by.get(row["doc_id"])
            if dup:
                row["neardup_cluster"] = dup["cluster_id"]
                row["neardup_jaccard"] = dup["jaccard"]


def snippet(text: str, stems: list[str]) -> tuple[str, list[str]]:
    """A window around the first query-term match, with the matches marked.

    Done at display time over ~20 documents rather than with a positional index,
    which would roughly double the size of a two-billion-posting file to support it.
    """
    if not text:
        return "", []
    idx = _load_indexer()
    words = list(idx.TOKEN.finditer(text.lower()))
    wanted = set(stems)
    positions = [m for m in words if _stem(m.group()) in wanted]
    matched = sorted({_stem(m.group()) for m in positions})

    if not positions:
        return text[:SNIPPET_WINDOW].strip(), matched
    centre = positions[0].start()
    start = max(0, centre - SNIPPET_WINDOW // 3)
    end = min(len(text), start + SNIPPET_WINDOW)
    window = text[start:end]

    # Mark matches with sentinels the client turns into <mark>; doing it here keeps
    # the offsets consistent with the stemming the ranking used.
    marks = [(m.start() - start, m.end() - start) for m in positions
             if start <= m.start() and m.end() <= end]
    for a, b in reversed(marks):
        window = f"{window[:a]}\x02{window[a:b]}\x03{window[b:]}"
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{window.strip()}{suffix}", matched


@router.get("")
def search(
    q: str = Query("", description="free-text query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    demote: bool = Query(False, description="push suspected coordinated reviews down"),
    rerank: bool = Query(False, description="neural cross-encoder over the top 50"),
    min_rating: int = Query(0, ge=0, le=5),
    group: str | None = Query(None, pattern="^(core|packs)$",
                              description="only reviews by one group of suspicious accounts"),
) -> dict:
    _require_index()
    if group is not None and "group_docs" not in db.available():
        raise HTTPException(503, "group search needs pipeline/15_story_network.py")
    started = time.time()
    stems = analyse(q)
    resolved = resolve(stems)
    terms, ignored = split_by_selectivity(resolved)

    if not terms:
        return {"query": q, "terms": [], "unknown": stems, "ignored": [], "total": 0,
                "limit": limit, "offset": offset, "items": [], "group": group,
                "timing_ms": {}, "reranked": False, "demoted": demote}

    t0 = time.time()
    hits = bm25(terms, CANDIDATE_DEPTH, group)
    bm25_ms = (time.time() - t0) * 1000

    # How much of the BM25 ranking to fetch before reordering. This used to be just
    # the page itself, which made demotion close to a no-op: a flagged review could
    # slide from 1st to 10th but could never leave the page, because the reviews
    # that should replace it had never been fetched. Reordering has to look past
    # the cut it is trying to change.
    window = limit + offset
    if rerank:
        window = max(window, RERANK_DEPTH)
    if demote:
        window = max(window, DEMOTE_DEPTH)
    page = hydrate(hits[:window], stems)

    rerank_ms = 0.0
    reranked = False
    if rerank and page:
        from api import rerank as rr
        if rr.available():
            t0 = time.time()
            page = rr.rerank(q, page, depth=RERANK_DEPTH)
            rerank_ms = (time.time() - t0) * 1000
            reranked = True

    if demote:
        # Relevance is preserved but scaled by how independent the author looks. A
        # multiplicative penalty keeps a highly relevant suspicious hit visible rather
        # than censoring it -- the point is to reorder, not to hide.
        for row in page:
            penalty = 1.0 - 0.8 * float(row.get("suspicion") or 0.0)
            row["final_score"] = row.get("rerank_score", row["score"]) * penalty
        page.sort(key=lambda r: -r["final_score"])
    else:
        for row in page:
            row["final_score"] = row.get("rerank_score", row["score"])

    if min_rating:
        page = [r for r in page if (r.get("rating") or 0) >= min_rating]

    items = page[offset:offset + limit]
    flagged = sum(1 for r in page[:10] if (r.get("suspicion") or 0) >= 0.9)

    return {
        "query": q,
        "terms": [{"term": t["term"], "df": t["df"], "idf": round(t["idf"], 4)}
                  for t in terms],
        "unknown": [s for s in stems if s not in {t["term"] for t in resolved}],
        "ignored": [{"term": t["term"], "df": t["df"]} for t in ignored],
        "total": len(hits),
        "limit": limit,
        "offset": offset,
        "items": items,
        "reranked": reranked,
        "demoted": demote,
        "group": group,
        "flagged_in_top10": flagged,
        "timing_ms": {
            "bm25": round(bm25_ms, 1),
            "rerank": round(rerank_ms, 1),
            "total": round((time.time() - started) * 1000, 1),
        },
    }


@router.get("/similar/{doc_id}")
def similar(doc_id: int, limit: int = Query(20, ge=1, le=100)) -> dict:
    """Near-duplicates of one review, from the LSH index built in stage 6.

    This reuses the shipped near-duplicate clusters rather than re-hashing: if the
    document is in a verified cluster, its cluster-mates are the answer and their
    similarity was already measured exactly.
    """
    _require_index()
    # Same order of preference as hydrate: blob, then Parquet store, then `raw`, which
    # cannot prune on review_sk at all and is only there so nothing breaks without the
    # stage-13 artifacts.
    have = db.available()
    if docblob.available():
        record = docblob.fetch([doc_id]).get(doc_id)
        source = None if record is None else {
            "doc_id": doc_id, "reviewerID": record["reviewerID"],
            "asin": record["asin"], "summary": record["summary"],
            "reviewText": record["reviewText"], "rating": record["rating"]}
    elif "docstore" in have:
        source = db.one("SELECT review_sk AS doc_id, reviewerID, asin, summary, "
                        "reviewText, rating FROM docstore WHERE review_sk = ?", [doc_id])
    else:
        with db.HEAVY:
            source = db.one("SELECT review_sk AS doc_id, reviewerID, asin, summary, "
                            "reviewText, rating FROM raw WHERE review_sk = ?", [doc_id])
    if source is None:
        raise HTTPException(404, "review not found")

    members = db.rows(f"""
        SELECT m2.review_sk AS doc_id, m2.jaccard, m2.rating, m2.day,
               d.reviewerID, p.asin, s.score AS suspicion
        FROM neardup_members m1
        JOIN neardup_members m2
          ON m2.config = m1.config AND m2.cluster_id = m1.cluster_id
         AND m2.review_sk <> m1.review_sk
        LEFT JOIN dim_reviewer d ON d.reviewer_sk = m2.reviewer_sk
        LEFT JOIN dim_product  p ON p.product_sk  = m2.product_sk
        LEFT JOIN scores s ON s.reviewer_sk = m2.reviewer_sk
        WHERE m1.review_sk = ? AND m1.config = 'loose'
        ORDER BY m2.jaccard DESC LIMIT {limit}""", [doc_id])

    if members:
        ids = [m["doc_id"] for m in members]
        if docblob.available():
            texts = docblob.fetch(ids)
        else:
            table = "docstore" if "docstore" in have else "raw"
            with (db.HEAVY if table == "raw" else contextlib.nullcontext()):
                texts = {r["review_sk"]: r for r in db.rows(
                    f"SELECT review_sk, summary, reviewText FROM {table} "
                    f"WHERE review_sk IN ({','.join('?' * len(ids))})", ids)}
        for m in members:
            body = (texts.get(m["doc_id"]) or {}).get("reviewText") or ""
            m["summary"] = (texts.get(m["doc_id"]) or {}).get("summary")
            m["snippet"] = body[:SNIPPET_WINDOW].strip()

    source["snippet"] = (source.pop("reviewText") or "")[:SNIPPET_WINDOW * 2]
    return {"source": source, "items": members,
            "note": "verified near-duplicates from the LSH index (exact Jaccard >= 0.707)"}


@router.get("/meta")
def index_meta() -> dict:
    """Index statistics, and the most expensive terms in it."""
    _require_index()
    m = dict(meta())
    m["top_terms"] = db.rows(
        "SELECT term, df FROM dictionary ORDER BY df DESC LIMIT 20")
    m["rerank_available"] = False
    try:
        from api import rerank as rr
        m["rerank_available"] = rr.available()
        m["rerank_model"] = rr.MODEL_NAME
    except Exception:
        pass
    return m
