"""Stage 1 -- the ONE pass over kcore_5.json.gz. Never read the .gz again.

Gzip is a single member, so it decodes serially at ~170-220 MB/s regardless of
thread count; that is the hard ceiling on this stage. Every per-row text counter
is therefore computed inline here, while the text is already decompressed --
benchmarked at 2M rows, the counters add under 5% on top of the decode cost.

Output: data/raw/reviews.parquet, ZSTD-3, ~14 GB, in source order (sorted by asin),
which gives row-group pruning on asin for the API's text lookups.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

COLUMNS = ("{reviewerID:'VARCHAR', asin:'VARCHAR', reviewerName:'VARCHAR', "
           "helpful:'INT[]', reviewText:'VARCHAR', overall:'FLOAT', "
           "summary:'VARCHAR', unixReviewTime:'BIGINT', reviewTime:'VARCHAR'}")

# reviewTime is dropped: it is a string rendering of unixReviewTime and carries
# no extra information (verified over all 41.1M rows during planning).
SELECT_SQL = f"""
SELECT
    reviewerID,
    asin,
    reviewerName,
    COALESCE(helpful[1], 0)::INTEGER                    AS helpful_yes,
    COALESCE(helpful[2], 0)::INTEGER                    AS helpful_total,
    reviewText,
    summary,
    overall::TINYINT                                    AS rating,
    unixReviewTime,

    -- exact-duplicate keys
    hash(reviewText)                                    AS text_hash,
    hash(summary)                                       AS summary_hash,
    -- normalised duplicate key: lowercased, whitespace-collapsed. Catches
    -- trivially-reformatted copies that a raw hash misses.
    hash(regexp_replace(lower(trim(reviewText)), '\s+', ' ', 'g')) AS norm_text_hash,

    -- style counters (the "shoutiness" factor plus length)
    length(reviewText)                                                  AS n_chars,
    length(reviewText) - length(replace(reviewText, ' ', '')) + 1       AS n_words,
    length(reviewText) - length(replace(reviewText, '!', ''))           AS n_exclaim,
    length(reviewText) - length(regexp_replace(reviewText, '[A-Z]', '', 'g')) AS n_upper,
    (lower(trim(summary)) = lower(trim(reviewText)))                    AS summary_is_text
FROM read_ndjson(
    '{common.SOURCE_GZ.as_posix()}',
    columns={COLUMNS},
    ignore_errors=true
)
"""


def main() -> None:
    common.guard_disk(min_d_gb=40.0)
    common.RAW_PARQUET.parent.mkdir(parents=True, exist_ok=True)

    con = common.connect()
    # Order matters here: the source is sorted by asin and keeping that order
    # gives the output parquet tight asin row-group statistics, which is what
    # makes the API's "fetch the text for this product" query cheap. The stage
    # is a pure streaming scan->write with no blocking operator, so preserving
    # order costs only a few buffered row groups.
    con.execute("SET preserve_insertion_order = true")

    with common.stage("01_ingest: kcore_5.json.gz -> raw/reviews.parquet"):
        con.execute(f"""
            COPY ({SELECT_SQL})
            TO '{common.RAW_PARQUET.as_posix()}'
            (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3, ROW_GROUP_SIZE 122880)
        """)

    print(f"\n[verify] {common.RAW_PARQUET.name}  {common.mb(common.RAW_PARQUET)/1024:.2f} GiB")
    src = f"'{common.RAW_PARQUET.as_posix()}'"

    rows = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    common.expect(rows, common.EXPECTED_ROWS, "row count")

    reviewers, products = con.execute(
        f"SELECT count(DISTINCT reviewerID), count(DISTINCT asin) FROM {src}").fetchone()
    common.expect(reviewers, common.EXPECTED_REVIEWERS, "distinct reviewers")
    common.expect(products, common.EXPECTED_PRODUCTS, "distinct products")

    print("  rating histogram:")
    for rating, count in con.execute(
            f"SELECT rating, count(*) FROM {src} GROUP BY 1 ORDER BY 1").fetchall():
        common.expect(count, common.EXPECTED_RATING_COUNTS[rating], f"    {rating}-star")

    lo, hi, null_time = con.execute(
        f"SELECT min(unixReviewTime), max(unixReviewTime), "
        f"count(*) FILTER (WHERE unixReviewTime IS NULL) FROM {src}").fetchone()
    common.expect(lo, common.UNIX_MIN, "min unixReviewTime")
    common.expect(hi, common.UNIX_MAX, "max unixReviewTime")
    common.expect(null_time, 4, "null unixReviewTime")

    null_name, empty_text = con.execute(
        f"SELECT count(*) FILTER (WHERE reviewerName IS NULL), "
        f"count(*) FILTER (WHERE n_chars = 0) FROM {src}").fetchone()
    common.expect(null_name, 932_551, "null reviewerName")
    common.expect(empty_text, 8_704, "empty reviewText")

    # asin ordering is what makes the API's text lookups cheap -- assert it held.
    inversions = con.execute(f"""
        SELECT count(*) FROM (
            SELECT asin, lag(asin) OVER () AS prev FROM {src}
        ) WHERE prev IS NOT NULL AND asin < prev
    """).fetchone()[0]
    if inversions:
        print(f"  WARN: output is NOT sorted by asin ({inversions:,} inversions). "
              f"API text lookups will scan more row groups than necessary.")
    else:
        print("  OK asin ordering preserved (0 inversions)")

    con.close()
    print("\nStage 1 complete. The .gz is never read again.")


if __name__ == "__main__":
    main()
