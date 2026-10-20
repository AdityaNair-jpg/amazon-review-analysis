"""Stage 2 -- surrogate keys, dimensions, and the narrow fact table.

review_sk is the physical row number in raw/reviews.parquet (DuckDB's
file_row_number), so it is stable forever and lets any query join back to the
wide text columns without storing a second copy of them.

The fact table is deliberately narrow (~54 bytes/row, ~1.4 GB on disk) so that
every downstream aggregation over 41.1M rows runs from RAM. It is written sorted
by (reviewer_sk, day) because most Stage 4 features are per-reviewer windows.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

RAW = f"read_parquet('{common.RAW_PARQUET.as_posix()}', file_row_number=true)"


def main() -> None:
    common.guard_disk()
    for path in (common.DIM_REVIEWER, common.DIM_PRODUCT, common.FACT_PARQUET):
        path.parent.mkdir(parents=True, exist_ok=True)

    con = common.connect()

    with common.stage("02_fact: dimensions"):
        # reviewerName is per-review in the source; a reviewer using several
        # display names is itself worth keeping as a signal.
        con.execute(f"""
            COPY (
                SELECT
                    (row_number() OVER (ORDER BY reviewerID) - 1)::INTEGER AS reviewer_sk,
                    reviewerID,
                    any_value(reviewerName)                   AS reviewer_name,
                    count(DISTINCT reviewerName)::SMALLINT    AS n_distinct_names
                FROM {RAW}
                GROUP BY reviewerID
            ) TO '{common.DIM_REVIEWER.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        con.execute(f"""
            COPY (
                SELECT
                    (row_number() OVER (ORDER BY asin) - 1)::INTEGER AS product_sk,
                    asin
                FROM (SELECT DISTINCT asin FROM {RAW})
            ) TO '{common.DIM_PRODUCT.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

    con.execute(f"CREATE VIEW dim_reviewer AS SELECT * FROM '{common.DIM_REVIEWER.as_posix()}'")
    con.execute(f"CREATE VIEW dim_product  AS SELECT * FROM '{common.DIM_PRODUCT.as_posix()}'")

    with common.stage("02_fact: narrow fact table"):
        con.execute(f"""
            COPY (
                SELECT
                    r.file_row_number::INTEGER                  AS review_sk,
                    dr.reviewer_sk,
                    dp.product_sk,
                    (r.unixReviewTime / 86400)::INTEGER         AS day,
                    r.rating,
                    r.helpful_yes,
                    r.helpful_total,
                    r.n_chars,
                    r.n_words,
                    r.n_exclaim::SMALLINT                       AS n_exclaim,
                    r.n_upper::INTEGER                          AS n_upper,
                    r.norm_text_hash,
                    r.summary_hash,
                    r.summary_is_text
                FROM {RAW} r
                JOIN dim_reviewer dr USING (reviewerID)
                JOIN dim_product  dp USING (asin)
                ORDER BY dr.reviewer_sk, day
            ) TO '{common.FACT_PARQUET.as_posix()}'
            (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3, ROW_GROUP_SIZE 122880)
        """)

    print("\n[verify]")
    for label, path in (("dim_reviewer", common.DIM_REVIEWER),
                        ("dim_product", common.DIM_PRODUCT),
                        ("fact_reviews", common.FACT_PARQUET)):
        print(f"  {label:<13} {common.mb(path):8.1f} MB")

    fact = f"'{common.FACT_PARQUET.as_posix()}'"
    common.expect(con.execute(f"SELECT count(*) FROM {fact}").fetchone()[0],
                  common.EXPECTED_ROWS, "fact rows")
    common.expect(con.execute("SELECT count(*) FROM dim_reviewer").fetchone()[0],
                  common.EXPECTED_REVIEWERS, "dim_reviewer rows")
    common.expect(con.execute("SELECT count(*) FROM dim_product").fetchone()[0],
                  common.EXPECTED_PRODUCTS, "dim_product rows")

    # review_sk must be a perfect bijection onto [0, N) or the join back to the
    # text columns is silently wrong.
    lo, hi, distinct = con.execute(
        f"SELECT min(review_sk), max(review_sk), count(DISTINCT review_sk) FROM {fact}").fetchone()
    common.expect(lo, 0, "min review_sk")
    common.expect(hi, common.EXPECTED_ROWS - 1, "max review_sk")
    common.expect(distinct, common.EXPECTED_ROWS, "distinct review_sk")

    # 5-core invariant: every reviewer and every product has at least 5 reviews.
    min_per_reviewer = con.execute(
        f"SELECT min(n) FROM (SELECT count(*) n FROM {fact} GROUP BY reviewer_sk)").fetchone()[0]
    min_per_product = con.execute(
        f"SELECT min(n) FROM (SELECT count(*) n FROM {fact} GROUP BY product_sk)").fetchone()[0]
    common.expect(min_per_reviewer, 5, "5-core: min reviews per reviewer")
    common.expect(min_per_product, 5, "5-core: min reviews per product")

    # Measured during planning: exactly one review per (reviewer, product).
    common.expect(
        con.execute(f"SELECT count(*) FROM (SELECT DISTINCT reviewer_sk, product_sk FROM {fact})"
                    ).fetchone()[0],
        common.EXPECTED_ROWS, "distinct (reviewer, product) pairs")

    null_days = con.execute(f"SELECT count(*) FROM {fact} WHERE day IS NULL").fetchone()[0]
    common.expect(null_days, 4, "null day (excluded from temporal features)")

    con.close()
    print("\nStage 2 complete.")


if __name__ == "__main__":
    main()
