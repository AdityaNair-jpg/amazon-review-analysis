"""Stage 13 -- build an inverted index over all 41,135,700 review texts.

This is the retrieval half of the project. A `LIKE` over reviewText reads the whole
9.7 GB archive and takes 128 seconds (measured, and noted in api/charts.py), so an
index is not an optimisation here -- it is the only way search is possible at all.

Construction follows SPIMI (Manning, Introduction to Information Retrieval, sec 4.3):
each worker builds an in-memory block for its slice of the corpus, sorts it, and
streams it to disk; the blocks are then merged into one term-ordered file.

Three decisions worth stating, because each avoids a real failure:

* ONE tokenisation pass, not two. Workers emit a 64-bit hash of the stem rather
  than a dense term id, so no worker needs the global vocabulary and nothing has to
  be broadcast. Dense ids are assigned once, centrally, during the merge. A second
  pass would have cost another ~4 minutes of tokenising for nothing.

* Stemming is memoised per worker. Porter runs at ~68k stems/s, which against 4.09
  billion tokens would be 17 hours. Against 3.8M *unique* terms it is about a
  minute. Same output, three orders of magnitude cheaper.

* Workers stream to their block writer per row group instead of accumulating.
  pipeline/06_minhash.py records what happens otherwise: workers climbed to 1.3 GB
  each and free memory fell to 772 MB before that was fixed.

Outputs under data/ir/:
    postings.parquet    1.87B rows   term_id, doc_id, impact  (sorted by term_id)
    dictionary.parquet  4.58M rows   term_id, term, df
    doc_stats.parquet   41.1M rows   doc_id, doc_len
    index_meta.json                  N, avg_dl, BM25 params, config, timings

`impact` is the length-normalised BM25 term contribution, precomputed:

    impact(t,d) = tf(t,d) * (k1 + 1) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))

so scoring a query is just SUM(idf(t) * impact(t,d)). Measured: with raw tf stored
instead, every query had to join its postings against all 41.1M document lengths and
a four-term query took 2.0 s; precomputing the impact removes the join entirely.

Re-running: if data/ir/blocks already holds the tokenised blocks, pass --merge-only
to skip the 22-minute tokenisation pass and rebuild just the index from them.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xxhash

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

IR = common.DATA / "ir"
BLOCKS = IR / "blocks"
VOCAB = IR / "vocab"
DOCS = IR / "docs"
POSTINGS = IR / "postings.parquet"
DICTIONARY = IR / "dictionary.parquet"
DOC_STATS = IR / "doc_stats.parquet"
META = IR / "index_meta.json"

TOKEN = re.compile(r"[a-z0-9']+")
MIN_TERM_LEN = 2
MAX_TERM_LEN = 32

# Caps the per-worker stem and hash caches. Word frequency is Zipfian, so this size
# still absorbs the great majority of tokens while keeping a worker's footprint
# bounded -- see the note in _worker about what unbounded growth cost.
STEM_CACHE_MAX = 300_000

# Documents buffered before a batch is flushed. See the note in _worker:
# a whole row group's worth of Python integers is what made this page.
DOC_CHUNK = 8_192

# BM25 parameters, baked into the index. See the note on the merge step: storing the
# length-normalised impact instead of the raw term frequency removes a join against
# 41.1M document lengths from every single query. The cost is that changing k1 or b
# means re-running the merge, which is ten minutes and is worth it.
BM25_K1 = 1.2
BM25_B = 0.75

# A short, classic stopword list. Kept deliberately small: every term removed here
# is a term that can never be searched for, and the index is affordable without
# aggressive pruning. These are the ones whose posting lists would otherwise run to
# tens of millions of entries and dominate query latency.
STOPWORDS = frozenset("""
a an and are as at be but by for from has have i in is it its of on or that the
to was were will with this these those they them i'm it's don't you your my me we
he she his her not no so if then than there here what when which who how all any
been being had do does did can could would should
""".split())

BLOCK_SCHEMA = pa.schema([
    ("stem_hash", pa.uint64()),
    ("doc_id", pa.int32()),
    ("tf", pa.int16()),
])
VOCAB_SCHEMA = pa.schema([("stem_hash", pa.uint64()), ("term", pa.string())])
DOCS_SCHEMA = pa.schema([("doc_id", pa.int32()), ("doc_len", pa.int32())])


def _worker(job) -> tuple[int, int, int, int, float]:
    """Tokenise one worker's row groups into a sorted SPIMI block.

    Memory is the binding constraint, not CPU. The first version of this let two
    per-worker dictionaries grow to the whole vocabulary a worker had seen; with
    eight workers that reached 1.1 GB each, free memory fell to 646 MB, CPU dropped
    to 56% and the build ran six times slower than it should have. Everything below
    is bounded:

      * `seen_terms` is flushed to the worker's vocab shard after every row group and
        cleared. DuckDB dedupes it later with a GROUP BY, so repeats cost nothing.
      * `stem_cache` is capped. Word frequencies are Zipfian, so a few hundred
        thousand entries still absorb the overwhelming majority of tokens; past the
        cap it is cleared rather than grown.
      * `hash_cache` is new, and is the CPU fix: hashing was being done once per
        POSTING (1.87 billion calls) when it only needs doing once per unique term.
    """
    from nltk.stem import PorterStemmer

    worker_id, row_groups, raw_path = job
    stemmer = PorterStemmer()
    stem_cache: dict[str, str] = {}
    hash_cache: dict[str, int] = {}
    seen_terms: dict[int, str] = {}

    reader = pq.ParquetFile(raw_path)
    started = time.time()
    block_w = vocab_w = docs_w = None
    n_docs = n_postings = 0

    vocab_w = pq.ParquetWriter(str(VOCAB / f"part-{worker_id:03d}.parquet"),
                               VOCAB_SCHEMA, compression="zstd")

    def flush_vocab() -> None:
        if not seen_terms:
            return
        vocab_w.write_table(pa.Table.from_arrays(
            [pa.array(np.array(list(seen_terms.keys()), dtype=np.uint64)),
             pa.array(list(seen_terms.values()))], schema=VOCAB_SCHEMA))
        seen_terms.clear()

    def stem_of(word: str) -> str:
        cached = stem_cache.get(word)
        if cached is None:
            cached = stemmer.stem(word)
            if len(stem_cache) >= STEM_CACHE_MAX:
                stem_cache.clear()
            stem_cache[word] = cached
        return cached

    try:
        for row_group, offset in row_groups:
            table = reader.read_row_group(row_group, columns=["reviewText", "summary"])
            bodies = table.column("reviewText").to_pylist()
            titles = table.column("summary").to_pylist()
            lengths = np.zeros(len(bodies), dtype=np.int32)

            # A row group holds 122,880 documents, which is ~6.4M postings. Buffering
            # those as Python lists costs about 540 MB -- three lists of PyLong objects
            # at ~40 bytes each -- and with several workers doing it at once the box
            # pages and CPU collapses to 11%. Measured, twice. So the row group is
            # walked in small slices and each slice is flushed to the writer.
            for base in range(0, len(bodies), DOC_CHUNK):
                stop = min(base + DOC_CHUNK, len(bodies))
                hashes: list[int] = []
                doc_ids: list[int] = []
                tfs: list[int] = []

                for i in range(base, stop):
                    # Title and body are one field: a review's headline is part of
                    # what it is about, and splitting them would need BM25F for
                    # little gain.
                    text = f"{titles[i] or ''} {bodies[i] or ''}".lower()
                    counts: Counter[str] = Counter()
                    total = 0
                    for word in TOKEN.findall(text):
                        if len(word) < MIN_TERM_LEN or len(word) > MAX_TERM_LEN:
                            continue
                        if word in STOPWORDS:
                            continue
                        total += 1
                        counts[stem_of(word)] += 1
                    lengths[i] = total
                    doc_id = offset + i
                    for stem, tf in counts.items():
                        h = hash_cache.get(stem)
                        if h is None:
                            h = xxhash.xxh64_intdigest(stem)
                            if len(hash_cache) >= STEM_CACHE_MAX:
                                hash_cache.clear()
                            hash_cache[stem] = h
                            seen_terms[h] = stem
                        hashes.append(h)
                        doc_ids.append(doc_id)
                        tfs.append(tf if tf < 32767 else 32767)

                n_postings += len(hashes)
                if hashes:
                    h_arr = np.fromiter(hashes, dtype=np.uint64, count=len(hashes))
                    d_arr = np.fromiter(doc_ids, dtype=np.int32, count=len(doc_ids))
                    t_arr = np.fromiter(tfs, dtype=np.int16, count=len(tfs))
                    order = np.argsort(h_arr, kind="stable")   # the SPIMI block sort
                    if block_w is None:
                        block_w = pq.ParquetWriter(
                            str(BLOCKS / f"part-{worker_id:03d}.parquet"), BLOCK_SCHEMA,
                            compression="zstd", compression_level=1)
                    block_w.write_table(pa.Table.from_arrays(
                        [pa.array(h_arr[order]), pa.array(d_arr[order]),
                         pa.array(t_arr[order])], schema=BLOCK_SCHEMA))
                    del h_arr, d_arr, t_arr, order
                hashes.clear(); doc_ids.clear(); tfs.clear()

            n_docs += len(bodies)
            doc_batch = pa.Table.from_arrays(
                [pa.array(np.arange(offset, offset + len(bodies), dtype=np.int32)),
                 pa.array(lengths)], schema=DOCS_SCHEMA)
            if docs_w is None:
                docs_w = pq.ParquetWriter(str(DOCS / f"part-{worker_id:03d}.parquet"),
                                          DOCS_SCHEMA, compression="zstd")
            docs_w.write_table(doc_batch)
            flush_vocab()
            del table, bodies, titles
    finally:
        flush_vocab()
        for writer in (block_w, docs_w, vocab_w):
            if writer is not None:
                writer.close()

    return worker_id, n_docs, n_postings, len(hash_cache), time.time() - started


def main() -> None:
    common.guard_disk(min_d_gb=40.0)
    for d in (IR, BLOCKS, VOCAB, DOCS):
        d.mkdir(parents=True, exist_ok=True)

    # --merge-only rebuilds the index from blocks that are already on disk, which is
    # what you want after changing a BM25 parameter: ten minutes instead of thirty.
    merge_only = "--merge-only" in sys.argv
    if merge_only and not any(BLOCKS.glob("*.parquet")):
        raise SystemExit("--merge-only needs data/ir/blocks; run without it first.")
    if not merge_only:
        for stale in list(BLOCKS.glob("*.parquet")) + list(VOCAB.glob("*.parquet")) \
                + list(DOCS.glob("*.parquet")):
            stale.unlink()

    raw_path = str(common.RAW_PARQUET)
    reader = pq.ParquetFile(raw_path)
    offsets, running = [], 0
    for i in range(reader.metadata.num_row_groups):
        offsets.append((i, running))
        running += reader.metadata.row_group(i).num_rows
    common.expect(running, common.EXPECTED_ROWS, "row groups cover the corpus")

    n_workers = min(5, max(1, mp.cpu_count() // 2))
    jobs = [(w, offsets[w::n_workers], raw_path) for w in range(n_workers)]
    print(f"{len(offsets)} row groups, {running:,} documents, {n_workers} workers")
    print(f"stopwords: {len(STOPWORDS)}, term length {MIN_TERM_LEN}-{MAX_TERM_LEN}, "
          f"Porter stemming (memoised)")

    timings: dict[str, float] = {}
    total_docs = total_postings = 0

    if merge_only:
        print("--merge-only: reusing the blocks already on disk "
              f"({sum(common.mb(p) for p in BLOCKS.glob('*.parquet')) / 1024:.2f} GiB)")
    else:
        t0 = time.time()
        with common.stage("13_index: tokenise + SPIMI blocks"):
            with mp.Pool(n_workers) as pool:
                for wid, docs, postings, terms, elapsed in pool.imap_unordered(
                        _worker, jobs):
                    total_docs += docs
                    total_postings += postings
                    print(f"  worker {wid}: {docs:,} docs, {postings:,} postings, "
                          f"{terms:,} cached terms, {elapsed:.0f}s "
                          f"({docs / max(elapsed, 1e-9):,.0f} docs/s)", flush=True)
        timings["tokenise_s"] = round(time.time() - t0, 1)
        common.expect(total_docs, common.EXPECTED_ROWS, "documents tokenised")
        print(f"  {total_postings:,} postings, "
              f"{sum(common.mb(p) for p in BLOCKS.glob('*.parquet')) / 1024:.2f} GiB "
              f"of blocks")

    con = common.connect()
    con.execute(f"CREATE VIEW blocks AS SELECT * FROM '{(BLOCKS / '*.parquet').as_posix()}'")
    con.execute(f"CREATE VIEW vocab  AS SELECT * FROM '{(VOCAB / '*.parquet').as_posix()}'")

    t0 = time.time()
    with common.stage("13_index: dictionary"):
        # df is just the number of postings for a term, because a block holds one row
        # per (term, document). Dense ids are assigned here and nowhere else.
        con.execute(f"""
            COPY (
                SELECT (row_number() OVER (ORDER BY f.stem_hash) - 1)::INTEGER AS term_id,
                       v.term, f.stem_hash, f.df
                FROM (SELECT stem_hash, count(*)::INTEGER AS df FROM blocks GROUP BY 1) f
                JOIN (SELECT stem_hash, any_value(term) AS term,
                             count(DISTINCT term)::INTEGER AS n_terms
                      FROM vocab GROUP BY 1) v USING (stem_hash)
            ) TO '{DICTIONARY.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
    timings["dictionary_s"] = round(time.time() - t0, 1)
    con.execute(f"CREATE VIEW dictionary AS SELECT * FROM '{DICTIONARY.as_posix()}'")

    # A 64-bit hash collision would silently merge two terms' posting lists, so check
    # rather than assume. Expected collisions for 3.8M terms in 2^64: about 4e-7.
    collisions = con.execute(
        "SELECT count(*) FROM (SELECT stem_hash FROM vocab GROUP BY 1 "
        "HAVING count(DISTINCT term) > 1)").fetchone()[0]
    common.expect(collisions, 0, "stem-hash collisions")

    n_terms = con.execute("SELECT count(*) FROM dictionary").fetchone()[0]
    print(f"  {n_terms:,} distinct terms")

    t0 = time.time()
    with common.stage("13_index: document statistics"):
        con.execute(f"""
            COPY (SELECT doc_id, doc_len FROM '{(DOCS / '*.parquet').as_posix()}'
                  ORDER BY doc_id)
            TO '{DOC_STATS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
    timings["doc_stats_s"] = round(time.time() - t0, 1)
    con.execute(f"CREATE VIEW doc_stats AS SELECT * FROM '{DOC_STATS.as_posix()}'")
    avgdl = con.execute("SELECT avg(doc_len) FROM doc_stats").fetchone()[0]

    t0 = time.time()
    with common.stage("13_index: merge blocks into the term-ordered index"):
        # The SPIMI merge, with two things folded in.
        #
        # Sorting by term_id makes every posting list contiguous, so the row-group
        # statistics turn a term lookup into a read of a few row groups rather than a
        # scan of 1.87 billion rows. Measured: ~90 ms to read a posting list of any
        # size from 1,190 entries to 2 million.
        #
        # And the BM25 length normalisation is applied HERE, once, instead of at query
        # time. Storing raw tf meant every query joined its postings against all 41.1M
        # document lengths: a four-term query cost 2.0 s, of which 1.6 s was that join.
        # Storing the finished impact makes scoring a multiply and a sum.
        con.execute(f"""
            COPY (
                SELECT d.term_id, b.doc_id,
                       (b.tf::DOUBLE * ({BM25_K1} + 1.0)
                        / (b.tf::DOUBLE + {BM25_K1}
                           * (1.0 - {BM25_B}
                              + {BM25_B} * dl.doc_len::DOUBLE / {avgdl})))::FLOAT
                         AS impact
                FROM blocks b
                JOIN dictionary d USING (stem_hash)
                JOIN doc_stats dl ON dl.doc_id = b.doc_id
                ORDER BY d.term_id, b.doc_id
            ) TO '{POSTINGS.as_posix()}'
            (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3,
             ROW_GROUP_SIZE 1000000)
        """)
    timings["merge_s"] = round(time.time() - t0, 1)

    print("\n[verify]")
    n_postings = con.execute(f"SELECT count(*) FROM '{POSTINGS.as_posix()}'").fetchone()[0]
    sum_df = con.execute("SELECT sum(df) FROM dictionary").fetchone()[0]
    common.expect(n_postings, sum_df, "postings == sum(df)")
    common.expect(
        con.execute(f"SELECT count(*) FROM '{DOC_STATS.as_posix()}'").fetchone()[0],
        common.EXPECTED_ROWS, "doc_stats rows")

    n_docs, avg_dl, max_dl = con.execute(
        "SELECT count(*), avg(doc_len), max(doc_len) FROM doc_stats").fetchone()
    print(f"  average document length: {avg_dl:.2f} terms (max {max_dl:,})")
    for label, path in (("postings", POSTINGS), ("dictionary", DICTIONARY),
                        ("doc_stats", DOC_STATS)):
        print(f"  {label:<12} {common.mb(path) / 1024:7.2f} GiB")

    print("\n  longest posting lists (the terms that decide query latency):")
    for term, df in con.execute(
            "SELECT term, df FROM dictionary ORDER BY df DESC LIMIT 12").fetchall():
        print(f"    {term:<16} df = {df:>10,}")

    META.write_text(json.dumps({
        "n_docs": int(n_docs),
        "n_terms": int(n_terms),
        "n_postings": int(n_postings),
        "avg_doc_len": round(float(avg_dl), 4),
        "max_doc_len": int(max_dl),
        "tokenizer": TOKEN.pattern,
        "min_term_len": MIN_TERM_LEN,
        "max_term_len": MAX_TERM_LEN,
        "stemmer": "porter",
        "bm25_k1": BM25_K1,
        "bm25_b": BM25_B,
        "impact_precomputed": True,
        "stopwords": sorted(STOPWORDS),
        "timings": timings,
    }, indent=2), encoding="utf-8")

    con.close()
    print(f"\nStage 13 complete. Index metadata: {META}")
    print("The block/vocab/doc shards under data/ir/{blocks,vocab,docs} are now "
          "redundant and can be deleted to reclaim space.")


if __name__ == "__main__":
    main()
