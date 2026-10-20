"""Stage 5 -- exact duplicate clusters on the normalised text hash.

Cheap (seconds) and the most legible exhibit in the project: identical review
text posted by different accounts on different products, shown side by side.

Normalisation (lowercase + whitespace-collapse) matters a lot here. Measured on
the full corpus: the raw hash finds 12,101 clusters covering 70,509 reviews,
the normalised hash finds 26,354 clusters covering 106,373 -- 2.2x more.

A cluster is only interesting if it spans MULTIPLE reviewers. One person
reposting their own text across their own reviews is a different (and much
weaker) signal than several accounts posting the same words, so the two are
separated rather than pooled.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

DUP_CLUSTERS = common.ns(common.DATA / "features" / "dup_clusters.parquet")
DUP_MEMBERS = common.ns(common.DATA / "features" / "dup_members.parquet")

# Short text collides by coincidence, not by copying: "Great product!" is not
# evidence of anything. Clusters are reported in two tiers so the short-text
# noise never contaminates the substantive findings.
SUBSTANTIVE_WORDS = common.MIN_WORDS_FOR_NEARDUP


def main() -> None:
    con = common.connect()
    con.execute(f"CREATE VIEW f AS SELECT * FROM '{common.FACT_PARQUET.as_posix()}'")
    con.execute(f"CREATE VIEW raw AS {common.raw_sql()}")

    with common.stage("05_duplicates: exact clusters on normalised text"):
        con.execute(f"""
            CREATE OR REPLACE TABLE dup_clusters AS
            WITH grp AS (
                SELECT norm_text_hash,
                       count(*)::INTEGER                       AS n_reviews,
                       count(DISTINCT reviewer_sk)::INTEGER    AS n_reviewers,
                       count(DISTINCT product_sk)::INTEGER     AS n_products,
                       min(n_words)::INTEGER                   AS n_words,
                       min(day)                                AS first_day,
                       max(day)                                AS last_day,
                       min(review_sk)                          AS exemplar_sk,
                       avg(rating::DOUBLE)                     AS mean_rating
                FROM f
                WHERE n_chars > 0
                GROUP BY norm_text_hash
                HAVING count(*) > 1
            )
            SELECT (row_number() OVER (ORDER BY n_reviewers DESC, n_reviews DESC,
                                       norm_text_hash) - 1)::INTEGER AS cluster_id,
                   norm_text_hash, n_reviews, n_reviewers, n_products, n_words,
                   first_day, last_day, exemplar_sk, mean_rating,
                   (last_day - first_day)                        AS span_days,
                   (n_words >= {SUBSTANTIVE_WORDS})              AS is_substantive,
                   (n_reviewers > 1)                             AS is_cross_reviewer
            FROM grp
        """)
        con.execute("""
            CREATE OR REPLACE TABLE dup_members AS
            SELECT f.review_sk, c.cluster_id, f.reviewer_sk, f.product_sk, f.day, f.rating
            FROM f JOIN dup_clusters c USING (norm_text_hash)
        """)
        con.execute(f"COPY dup_clusters TO '{DUP_CLUSTERS.as_posix()}' "
                    f"(FORMAT PARQUET, COMPRESSION ZSTD)")
        con.execute(f"COPY dup_members TO '{DUP_MEMBERS.as_posix()}' "
                    f"(FORMAT PARQUET, COMPRESSION ZSTD)")

    print("\n[breakdown]")
    for label, predicate in (
            ("all clusters", "true"),
            ("cross-reviewer (>1 account)", "is_cross_reviewer"),
            (f"substantive (>= {SUBSTANTIVE_WORDS} words)", "is_substantive"),
            ("cross-reviewer AND substantive", "is_cross_reviewer AND is_substantive"),
            ("cross-reviewer, substantive, >= 3 accounts", "is_cross_reviewer AND "
             "is_substantive AND n_reviewers >= 3")):
        clusters, reviews, accounts = con.execute(
            f"SELECT count(*), coalesce(sum(n_reviews), 0), coalesce(max(n_reviewers), 0) "
            f"FROM dup_clusters WHERE {predicate}").fetchone()
        print(f"  {label:<44} {clusters:>7,} clusters  {reviews:>9,} reviews  "
              f"(largest spans {accounts:,} accounts)")

    print("\n[top cross-reviewer substantive clusters]")
    rows = con.execute(f"""
        SELECT c.cluster_id, c.n_reviewers, c.n_products, c.n_words, c.span_days,
               round(c.mean_rating, 2), left(replace(r.reviewText, chr(10), ' '), 90)
        FROM dup_clusters c
        JOIN raw r ON r.review_sk = c.exemplar_sk
        WHERE c.is_cross_reviewer AND c.is_substantive
        ORDER BY c.n_reviewers DESC, c.n_words DESC
        LIMIT 12
    """).fetchall()
    print(f"  {'id':>7} {'accts':>6} {'prods':>6} {'words':>6} {'days':>6} {'rating':>6}  text")
    for cid, nrev, nprod, nw, span, rating, text in rows:
        print(f"  {cid:>7} {nrev:>6} {nprod:>6} {nw:>6} {span:>6} {rating:>6}  {text}")

    total = con.execute("SELECT count(*) FROM dup_members").fetchone()[0]
    print(f"\n  dup_members rows: {total:,}")
    con.close()
    print("Stage 5 complete.")


if __name__ == "__main__":
    main()
