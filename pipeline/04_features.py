"""Stage 4 -- Tier-1 reviewer and product features, in pure SQL over the fact table.

Two hard rules are enforced here rather than left to discipline:

1. No rating feature enters as a LEVEL. 59.21% of this corpus is five-star, so
   "mostly positive" flags three fifths of everyone. Ratings appear only as a
   leave-one-out deviation from the product's own mean, or as a within-reviewer
   distribution shape (entropy).

2. Every temporal feature is DE-TRENDED against the global daily volume series
   from Stage 3. Expected count E = n_p * daily_volume(d) / N, z = (c - E)/sqrt(E).
   Without this, "burst" is just a synonym for "2013" -- that year holds 14.79M of
   the 41.1M reviews. E is floored at 1.0 so that a product with five reviews on a
   near-empty 1997 day does not produce an absurd z.

Memory discipline: every step COPIES straight to Parquet and is then re-read as a
view. Materialising these as in-memory DuckDB tables exhausts the 9.3 GiB budget --
the reviewer aggregation alone peaks near 9 GiB on its own. COUNT(DISTINCT) over
3M groups is likewise avoided in favour of two-level GROUP BY.

Helpful-vote aggregates ARE computed here, but they are written to a SEPARATE
file (feat_reviewer_votes.parquet) and are reserved for Stage 9 validation. They
must never enter the suspicion score -- tests/test_score_contract.py enforces it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

FEATURES = common.DATA / "features"
FEAT_REVIEWER = common.ns(FEATURES / "feat_reviewer.parquet")
FEAT_PRODUCT = common.ns(FEATURES / "feat_product.parquet")
FEAT_VOTES = common.ns(FEATURES / "feat_reviewer_votes.parquet")
BASELINE = FEATURES / "baseline_daily_volume.parquet"
TMP = FEATURES / "_tmp"


def main() -> None:
    common.guard_disk()
    TMP.mkdir(parents=True, exist_ok=True)

    con = common.connect()
    con.execute(f"CREATE VIEW f AS SELECT * FROM '{common.FACT_PARQUET.as_posix()}'")
    con.execute(f"CREATE VIEW baseline AS SELECT * FROM '{BASELINE.as_posix()}'")
    con.execute(f"CREATE VIEW dim_reviewer AS SELECT * FROM '{common.DIM_REVIEWER.as_posix()}'")
    total = con.execute("SELECT count(*) FROM f").fetchone()[0]

    def copy_to(name: str, query: str) -> Path:
        """Run a query straight to Parquet and expose it as a view of the same name."""
        path = common.ns(TMP / f"{name}.parquet")
        con.execute(f"COPY ({query}) TO '{path.as_posix()}' "
                    f"(FORMAT PARQUET, COMPRESSION ZSTD)")
        con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM '{path.as_posix()}'")
        print(f"    {name:<16} {common.mb(path):7.1f} MB")
        return path

    # ------------------------------------------------------------------ products
    with common.stage("04_features: product features"):
        # per-product/day counts de-trended against the global daily volume
        copy_to("p_burst", f"""
            WITH pd AS (
                SELECT product_sk, day, count(*)::INTEGER AS c
                FROM f WHERE day IS NOT NULL GROUP BY 1, 2
            ),
            np AS (SELECT product_sk, count(*)::INTEGER AS n FROM f GROUP BY 1),
            e AS (
                SELECT pd.product_sk, pd.day, pd.c,
                       greatest(np.n * b.n_reviews::DOUBLE / {total}, 1.0) AS e
                FROM pd JOIN np USING (product_sk) JOIN baseline b USING (day)
            ),
            z AS (
                SELECT product_sk, day, c,
                       (c - e) / sqrt(e) AS z_day,
                       (sum(c) OVER w - sum(e) OVER w) / sqrt(sum(e) OVER w) AS z_7d
                FROM e
                WINDOW w AS (PARTITION BY product_sk ORDER BY day
                             RANGE BETWEEN 6 PRECEDING AND CURRENT ROW)
            )
            SELECT product_sk, max(z_day) AS max_daily_z, max(z_7d) AS max_7d_z,
                   arg_max(day, z_day) AS peak_day, max(c)::INTEGER AS max_reviews_one_day
            FROM z GROUP BY 1
        """)

        copy_to("p_shape", """
            SELECT product_sk,
                   -sum(p * ln(p)) / ln(5) AS rating_entropy
            FROM (SELECT product_sk,
                         count(*)::DOUBLE / sum(count(*)) OVER (PARTITION BY product_sk) AS p
                  FROM f GROUP BY product_sk, rating)
            GROUP BY 1
        """)

        copy_to("p_shift", """
            SELECT product_sk,
                   abs(avg(CASE WHEN h = 1 THEN rating::DOUBLE END)
                       - avg(CASE WHEN h = 2 THEN rating::DOUBLE END)) AS rating_shift
            FROM (SELECT product_sk, rating,
                         ntile(2) OVER (PARTITION BY product_sk ORDER BY day, review_sk) AS h
                  FROM f WHERE day IS NOT NULL)
            GROUP BY 1
        """)

        copy_to("p_dup", f"""
            SELECT product_sk,
                   sum(CASE WHEN c > 1 THEN c ELSE 0 END)::DOUBLE / sum(c) AS dup_text_rate
            FROM (SELECT product_sk, norm_text_hash, count(*) AS c
                  FROM f WHERE n_words >= {common.MIN_WORDS_FOR_NEARDUP} GROUP BY 1, 2)
            GROUP BY 1
        """)

        con.execute(f"""
            COPY (
                SELECT b.product_sk, b.n_reviews, b.mean_rating, b.sd_rating,
                       b.frac_5star, b.frac_extreme, s.rating_entropy,
                       b.first_day, b.last_day, (b.last_day - b.first_day) AS lifespan_days,
                       coalesce(z.max_daily_z, 0.0)          AS max_daily_z,
                       coalesce(z.max_7d_z, 0.0)             AS max_7d_z,
                       z.peak_day,
                       coalesce(z.max_reviews_one_day, 0)    AS max_reviews_one_day,
                       coalesce(h.rating_shift, 0.0)         AS rating_shift,
                       coalesce(d.dup_text_rate, 0.0)        AS dup_text_rate
                FROM (
                    SELECT product_sk,
                           count(*)::INTEGER                                     AS n_reviews,
                           avg(rating::DOUBLE)                                   AS mean_rating,
                           stddev_pop(rating::DOUBLE)                            AS sd_rating,
                           avg(CASE WHEN rating = 5 THEN 1.0 ELSE 0.0 END)       AS frac_5star,
                           avg(CASE WHEN rating IN (1, 5) THEN 1.0 ELSE 0.0 END) AS frac_extreme,
                           min(day) AS first_day, max(day) AS last_day
                    FROM f GROUP BY 1
                ) b
                LEFT JOIN p_shape s USING (product_sk)
                LEFT JOIN p_burst z USING (product_sk)
                LEFT JOIN p_shift h USING (product_sk)
                LEFT JOIN p_dup   d USING (product_sk)
            ) TO '{FEAT_PRODUCT.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        con.execute(f"CREATE VIEW feat_product AS SELECT * FROM '{FEAT_PRODUCT.as_posix()}'")

    # ----------------------------------------------------------------- reviewers
    with common.stage("04_features: reviewer features"):
        # Leave-one-out deviation: how far this review sits from what everyone ELSE
        # said about the same product. n_p >= 5, so the denominator is always safe.
        copy_to("r_loo", """
            WITH p AS (SELECT product_sk, sum(rating::DOUBLE) s, count(*) n FROM f GROUP BY 1)
            SELECT f.reviewer_sk,
                   avg(abs(f.rating - (p.s - f.rating) / (p.n - 1))) AS loo_rating_dev,
                   avg(f.rating - (p.s - f.rating) / (p.n - 1))      AS loo_rating_bias
            FROM f JOIN p USING (product_sk) GROUP BY 1
        """)

        # Per-reviewer/day activity: active-day count, daily peak, 7-day peak, and
        # the coefficient of variation of the gaps between active days.
        copy_to("r_time", """
            WITH rd AS (
                SELECT reviewer_sk, day, count(*)::INTEGER AS c
                FROM f WHERE day IS NOT NULL GROUP BY 1, 2
            ),
            w AS (
                SELECT reviewer_sk, day, c,
                       sum(c) OVER (PARTITION BY reviewer_sk ORDER BY day
                                    RANGE BETWEEN 6 PRECEDING AND CURRENT ROW) AS c7,
                       (day - lag(day) OVER (PARTITION BY reviewer_sk ORDER BY day))::DOUBLE AS g
                FROM rd
            )
            SELECT reviewer_sk,
                   count(*)::INTEGER       AS n_active_days,
                   max(c)                  AS max_per_day,
                   max(c7)                 AS max_in_7d,
                   arg_max(day, c)         AS busiest_day,
                   CASE WHEN avg(g) > 0 THEN stddev_pop(g) / avg(g) ELSE 0.0 END AS gap_cv
            FROM w GROUP BY 1
        """)

        # How early in a product's life this reviewer tends to arrive. This is the
        # only step that needs a full re-sort by product_sk, so it stands alone.
        copy_to("r_early", """
            SELECT reviewer_sk, avg(pr) AS early_tendency
            FROM (SELECT reviewer_sk,
                         percent_rank() OVER (PARTITION BY product_sk ORDER BY day, review_sk) AS pr
                  FROM f WHERE day IS NOT NULL)
            GROUP BY 1
        """)

        # Self-reuse of text and of summary lines. Two-level GROUP BY rather than
        # COUNT(DISTINCT), which blows up over 3M groups.
        copy_to("r_reuse", f"""
            WITH t AS (
                SELECT reviewer_sk,
                       sum(CASE WHEN c > 1 THEN c ELSE 0 END)::DOUBLE / sum(c) AS self_dup_rate
                FROM (SELECT reviewer_sk, norm_text_hash, count(*) AS c
                      FROM f WHERE n_words >= {common.MIN_WORDS_FOR_NEARDUP} GROUP BY 1, 2)
                GROUP BY 1
            ),
            s AS (
                SELECT reviewer_sk, 1.0 - count(*)::DOUBLE / sum(c) AS summary_reuse_rate
                FROM (SELECT reviewer_sk, summary_hash, count(*) AS c FROM f GROUP BY 1, 2)
                GROUP BY 1
            )
            SELECT reviewer_sk, coalesce(t.self_dup_rate, 0.0) AS self_dup_rate,
                   s.summary_reuse_rate
            FROM s LEFT JOIN t USING (reviewer_sk)
        """)

        copy_to("r_shape", """
            SELECT reviewer_sk, -sum(p * ln(p)) / ln(5) AS rating_entropy
            FROM (SELECT reviewer_sk,
                         count(*)::DOUBLE / sum(count(*)) OVER (PARTITION BY reviewer_sk) AS p
                  FROM f GROUP BY reviewer_sk, rating)
            GROUP BY 1
        """)

        # n_products is deliberately absent: (reviewer, product) is unique across all
        # 41.1M rows (measured in Stage 2), so it is identical to n_reviews.
        copy_to("r_base", """
            SELECT reviewer_sk,
                   count(*)::INTEGER                                     AS n_reviews,
                   min(day) AS first_day, max(day) AS last_day,
                   avg(rating::DOUBLE)                                   AS mean_rating,
                   avg(CASE WHEN rating = 5 THEN 1.0 ELSE 0.0 END)       AS frac_5star,
                   avg(CASE WHEN rating IN (1, 5) THEN 1.0 ELSE 0.0 END) AS frac_extreme,
                   avg(n_words::DOUBLE)                                  AS mean_words,
                   CASE WHEN avg(n_words) > 0
                        THEN stddev_pop(n_words::DOUBLE) / avg(n_words::DOUBLE)
                        ELSE 0.0 END                                     AS words_cv,
                   avg(n_exclaim::DOUBLE / greatest(n_words, 1))         AS exclaim_rate,
                   avg(n_upper::DOUBLE / greatest(n_chars, 1))           AS upper_rate,
                   avg(CASE WHEN summary_is_text THEN 1.0 ELSE 0.0 END)  AS summary_is_text_rate
            FROM f GROUP BY 1
        """)

        con.execute(f"""
            COPY (
                SELECT b.reviewer_sk, b.n_reviews,
                       coalesce(t.n_active_days, 0)                        AS n_active_days,
                       b.first_day, b.last_day,
                       (b.last_day - b.first_day)                          AS lifespan_days,
                       b.n_reviews::DOUBLE / greatest(t.n_active_days, 1)  AS reviews_per_active_day,
                       b.mean_rating, b.frac_5star, b.frac_extreme,
                       sh.rating_entropy, l.loo_rating_dev, l.loo_rating_bias,
                       coalesce(t.max_per_day, 0)                          AS max_per_day,
                       coalesce(t.max_in_7d, 0)                            AS max_in_7d,
                       t.busiest_day,
                       coalesce(t.gap_cv, 0.0)                             AS gap_cv,
                       coalesce(e.early_tendency, 0.5)                     AS early_tendency,
                       coalesce(u.self_dup_rate, 0.0)                      AS self_dup_rate,
                       coalesce(u.summary_reuse_rate, 0.0)                 AS summary_reuse_rate,
                       b.mean_words, b.words_cv, b.exclaim_rate, b.upper_rate,
                       b.summary_is_text_rate,
                       coalesce(dr.n_distinct_names, 1)                    AS n_distinct_names
                FROM r_base b
                LEFT JOIN r_shape sh USING (reviewer_sk)
                LEFT JOIN r_loo   l  USING (reviewer_sk)
                LEFT JOIN r_time  t  USING (reviewer_sk)
                LEFT JOIN r_early e  USING (reviewer_sk)
                LEFT JOIN r_reuse u  USING (reviewer_sk)
                LEFT JOIN dim_reviewer dr USING (reviewer_sk)
            ) TO '{FEAT_REVIEWER.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        con.execute(f"CREATE VIEW feat_reviewer AS SELECT * FROM '{FEAT_REVIEWER.as_posix()}'")

    # --------------------------------------------- validation-only vote features
    with common.stage("04_features: helpful-vote aggregates (VALIDATION ONLY)"):
        con.execute(f"""
            COPY (
                SELECT reviewer_sk,
                       sum(helpful_total)::INTEGER                            AS votes_total,
                       sum(helpful_yes)::INTEGER                              AS votes_helpful,
                       CASE WHEN sum(helpful_total) > 0
                            THEN sum(helpful_yes)::DOUBLE / sum(helpful_total)
                            END                                               AS helpful_ratio,
                       avg(CASE WHEN helpful_total = 0 THEN 1.0 ELSE 0.0 END) AS frac_zero_votes
                FROM f GROUP BY 1
            ) TO '{FEAT_VOTES.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

    # -------------------------------------------------------------- verification
    print("\n[verify]")
    common.expect(con.execute("SELECT count(*) FROM feat_reviewer").fetchone()[0],
                  common.EXPECTED_REVIEWERS, "feat_reviewer rows")
    common.expect(con.execute("SELECT count(*) FROM feat_product").fetchone()[0],
                  common.EXPECTED_PRODUCTS, "feat_product rows")

    # No NaN / Inf anywhere -- they poison the empirical-CDF transform in Stage 8.
    for table_name in ("feat_reviewer", "feat_product"):
        cols = [r[0] for r in con.execute(f"DESCRIBE {table_name}").fetchall()
                if r[1] in ("DOUBLE", "FLOAT")]
        bad = con.execute(
            f"SELECT count(*) FROM {table_name} WHERE "
            + " OR ".join(f"NOT isfinite({c})" for c in cols)).fetchone()[0]
        common.expect(bad, 0, f"{table_name}: non-finite values")

    # De-trending check: if max_daily_z still tracks calendar year, it is measuring
    # Amazon's growth curve rather than anomalous activity.
    corr = con.execute("""
        SELECT corr(max_daily_z, year(to_timestamp(peak_day * 86400)))
        FROM feat_product WHERE peak_day IS NOT NULL""").fetchone()[0]
    print(f"  corr(max_daily_z, calendar year) = {corr:+.4f}")
    print("  OK de-trending holds (|corr| <= 0.30)" if abs(corr) <= 0.30 else
          "  WARN: burst score still tracks calendar year -- de-trending is not working.")

    for label, path in (("feat_reviewer", FEAT_REVIEWER), ("feat_product", FEAT_PRODUCT),
                        ("feat_reviewer_votes", FEAT_VOTES)):
        print(f"  {label:<20} {common.mb(path):8.1f} MB")

    con.close()
    print("\nStage 4 complete.  (intermediates left in data/features/_tmp for inspection)")


if __name__ == "__main__":
    main()
