"""Stage 13b -- a document store keyed by review_sk, for fetching search results.

Search needs to turn ~20 document ids into ~20 documents, and doing that against the
existing artifacts is slow for a specific and fixable reason.

`review_sk` is not a stored column anywhere. In data/raw/reviews.parquet it is DuckDB's
virtual `file_row_number`, and in data/fact/fact_reviews.parquet the file is sorted by
reviewer_sk. Neither carries row-group statistics on review_sk, so a lookup for twenty
ids cannot prune and reads the whole file. Measured: 954 ms against the raw archive,
948 ms against the fact table, and 3.1 s for the full join -- per query, for twenty
rows.

This writes one file that holds everything a result row needs, sorted by review_sk with
an explicit review_sk column and small row groups. Statistics then let DuckDB skip
straight to the handful of row groups that matter.

Row-group size is a two-sided trade, and the first attempt got it wrong. Small groups
mean a lookup decompresses less data -- but every query also parses the Parquet footer,
whose cost is linear in row_groups x columns at a measured 3.7 us per column chunk. At
8,192 rows there were 5,022 groups x 13 columns = 65,286 chunks, so *every* query paid
242 ms of metadata parsing before reading a single byte; `SELECT count(*)`, which reads
no data at all, took 335 ms.

Balancing the two puts the optimum near 1,850 groups, and 20,000 rows per group
measured best: a twenty-document lookup went from 855 ms to 529 ms.

That is as far as Parquet goes, and it is not far enough. A *single*-row lookup still
costs 252 ms, because the fixed metadata cost is paid whether you want one row or a
thousand. Splitting text and metadata into separate files so each could take its own
row-group size was tried and measured worse (769 ms), and `enable_object_cache` made
no difference. Stage 13c stores the same records in a flat file with an offset index,
which has no per-query fixed cost at all, and that is what the API reads.

This file is still built, because it is the SQL-queryable copy of those records and
the source stage 13c streams. `--split` remains for reproducing the negative result.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

DOCSTORE = common.DATA / "ir" / "docstore.parquet"
DOCMETA = common.DATA / "ir" / "docmeta.parquet"
DOCTEXT = common.DATA / "ir" / "doctext.parquet"
ROW_GROUP = 20_000

# --split: an experiment that did not pay off, kept so the result is reproducible.
#
# The reasoning was that footer cost grows with row_groups x columns while per-lookup
# data cost grows with bytes-per-row-group, so text and metadata should each get their
# own row-group size rather than share one compromise. Measured, 20 scattered ids:
#
#   docstore  13 columns, 9.01 GiB, 20,000/group               529-620 ms
#   docmeta   11 columns, 1.04 GiB, 50,000/group               147-198 ms
#   doctext    3 columns, 8.09 GiB,  5,000/group               470-594 ms
#   the two joined, which is what search would do              737-786 ms
#
# Worse than the single file, because the join reintroduces a second fixed metadata
# cost and neither file escapes the one it already had.
META_ROW_GROUP = 50_000
TEXT_ROW_GROUP = 5_000

META_COLUMNS = ("review_sk, reviewer_sk, product_sk, day, reviewerID, asin, "
                "reviewerName, rating, helpful_yes, helpful_total, n_words")
TEXT_COLUMNS = "review_sk, summary, reviewText"


def split(con) -> None:
    """Derive docmeta and doctext from an existing docstore.

    A streaming scan and two writes -- the source is already ordered by review_sk, so
    there is no join and no sort to redo.
    """
    con.execute("SET preserve_insertion_order = true")
    for name, columns, group, target in (
            ("docmeta", META_COLUMNS, META_ROW_GROUP, DOCMETA),
            ("doctext", TEXT_COLUMNS, TEXT_ROW_GROUP, DOCTEXT)):
        staging = target.with_name(f"{name}_staging.parquet")
        with common.stage(f"13b_docstore: {name} at {group:,} rows per group"):
            con.execute(f"""
                COPY (SELECT {columns} FROM '{DOCSTORE.as_posix()}')
                TO '{staging.as_posix()}'
                (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3,
                 ROW_GROUP_SIZE {group})""")
        os.replace(staging, target)


def main() -> None:
    common.guard_disk(min_d_gb=30.0)
    DOCSTORE.parent.mkdir(parents=True, exist_ok=True)

    con = common.connect()
    if "--split" in sys.argv:
        if not DOCSTORE.exists():
            raise SystemExit("--split needs an existing docstore; run without it first.")
        split(con)
        con.close()
        verify(common.connect())
        return
    # Read the archive directly rather than through common.raw_sql(): that helper
    # projects the columns the analysis stages need, and this needs the display ones
    # (reviewerName, rating) too. Everything but the surrogate keys is already there.
    con.execute(f"""
        CREATE VIEW raw AS
        SELECT file_row_number::INTEGER AS review_sk, reviewerID, asin, reviewerName,
               reviewText, summary, rating, helpful_yes, helpful_total, n_words
        FROM read_parquet('{common.RAW_PARQUET.as_posix()}', file_row_number=true)""")
    con.execute(f"CREATE VIEW fact AS SELECT * FROM '{common.FACT_PARQUET.as_posix()}'")

    with common.stage("13b_docstore: one lookup file keyed by review_sk"):
        con.execute(f"""
            COPY (
                SELECT r.review_sk,
                       f.reviewer_sk, f.product_sk, f.day,
                       r.reviewerID, r.asin, r.reviewerName,
                       r.rating, r.helpful_yes, r.helpful_total,
                       r.n_words::INTEGER AS n_words,
                       r.summary, r.reviewText
                FROM raw r
                LEFT JOIN fact f ON f.review_sk = r.review_sk
                ORDER BY r.review_sk
            ) TO '{DOCSTORE.as_posix()}'
            (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3,
             ROW_GROUP_SIZE {ROW_GROUP})
        """)

    verify(con)


def verify(con) -> None:
    print("\n[verify]")
    for name, path in (("docmeta", DOCMETA), ("doctext", DOCTEXT)):
        if not path.exists():
            continue
        con.execute(f"CREATE OR REPLACE VIEW {name} AS "
                    f"SELECT * FROM '{path.as_posix()}'")
        common.expect(con.execute(f"SELECT count(*) FROM {name}").fetchone()[0],
                      common.EXPECTED_ROWS, f"{name} rows")
        lo, hi = con.execute(
            f"SELECT min(review_sk), max(review_sk) FROM {name}").fetchone()
        common.expect(lo, 0, f"{name} min review_sk")
        common.expect(hi, common.EXPECTED_ROWS - 1, f"{name} max review_sk")
        print(f"  {name}: {common.mb(path) / 1024:.2f} GiB")

    # Twenty ids scattered across the corpus: the shape every search result page uses.
    ids = list(range(1_000_000, 41_000_000, 2_000_000))[:20]
    keys = ",".join(str(i) for i in ids)
    for label, sql in (
            ("docmeta lookup", f"SELECT * FROM docmeta WHERE review_sk IN ({keys})"),
            ("doctext lookup", f"SELECT * FROM doctext WHERE review_sk IN ({keys})"),
            ("joined, as search fetches it",
             f"SELECT m.*, t.summary, t.reviewText FROM docmeta m "
             f"JOIN doctext t USING (review_sk) WHERE m.review_sk IN ({keys})")):
        con.execute(sql).fetchall()
        t0 = time.time()
        rows = con.execute(sql).fetchall()
        print(f"  {label:<30} {(time.time() - t0) * 1000:7.0f} ms  ({len(rows)} rows)")

    con.close()
    print("\nStage 13b complete.")
    print("data/ir/docstore.parquet is now redundant; the API prefers the split files.")


if __name__ == "__main__":
    main()
