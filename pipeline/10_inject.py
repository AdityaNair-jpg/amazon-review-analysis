"""Stage 10 -- inject synthetic review campaigns with known ground truth.

This is the only study in the project that yields a real recall number. Every
other measurement is against a proxy; here we know exactly which accounts are
planted, because we planted them.

A campaign is parameterised by:
    G   number of colluding accounts
    P   number of products they all target
    W   width in days of the window they operate in
    rho fraction of campaign reviews that reuse one template verbatim
    camouflage  whether the accounts also post honest reviews to blend in

The grid is deliberately crossed rather than averaged: reporting one mean recall
would hide exactly the configurations the detector misses, which are the
interesting ones. Stage 11 reports recall@k per cell.

Realism decisions worth defending:
  * Text is sampled from REAL reviews in this corpus, so style statistics
    (length, punctuation, capitalisation) are drawn from the true distribution
    rather than from something a generator invented.
  * Every synthetic account also carries honest reviews, because an account with
    three reviews would fail the corpus's own 5-core floor and would be trivially
    separable for the wrong reason.
  * Target products are drawn from the 10-200 review band. A campaign against a
    product with 13,550 reviews is invisible by construction; one against a
    5-review product is trivial. The band is where the question is interesting.

Output feeds a re-run of stages 4-9 under BDA_NAMESPACE=_inj.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xxhash

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

VALIDATE = common.DATA / "validate"
FACT_INJ = VALIDATE / "fact_inj.parquet"
SYNTH_TEXT = VALIDATE / "synth_text.parquet"
SYNTH_BANDS = VALIDATE / "synth_bands.parquet"
CAMPAIGNS = VALIDATE / "campaigns.parquet"
DIM_INJ = common.DATA / "dim" / "dim_reviewer_inj.parquet"

SEED = 20240919
GRID = {
    "G": [5, 10, 25],        # colluding accounts
    "P": [3, 8],             # products targeted
    "W": [7, 30],            # operating window, days
    "rho": [0.0, 0.6, 1.0],  # template reuse rate
    "camouflage": [False, True],
}
CAMPAIGNS_PER_CELL = 5
HONEST_CAMOUFLAGED = 20      # honest reviews when blending in
HONEST_MINIMAL = 4           # honest reviews otherwise (keeps the account above 5-core)
TEXT_POOL = 30_000
TARGET_MIN_REVIEWS, TARGET_MAX_REVIEWS = 10, 200


def norm_hash(text: str) -> int:
    return xxhash.xxh64_intdigest(" ".join(text.lower().split()))


def main() -> None:
    common.guard_disk()
    VALIDATE.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    con = common.connect()

    with common.stage("10_inject: sample source material from the real corpus"):
        pool = con.execute(f"""
            SELECT r.reviewText, r.summary
            FROM read_parquet('{common.RAW_PARQUET.as_posix()}') r
            WHERE r.n_words BETWEEN 30 AND 400
            USING SAMPLE {TEXT_POOL} ROWS (reservoir, {SEED})
        """).fetchall()
        texts = [t for t, _ in pool]
        summaries = [s for _, s in pool]
        print(f"  {len(texts):,} source reviews sampled (30-400 words)")

        targets = con.execute(f"""
            SELECT product_sk FROM '{(common.DATA / 'features' / 'feat_product.parquet').as_posix()}'
            WHERE n_reviews BETWEEN {TARGET_MIN_REVIEWS} AND {TARGET_MAX_REVIEWS}
        """).fetchnumpy()["product_sk"]
        all_products = con.execute(
            f"SELECT product_sk FROM '{common.DIM_PRODUCT.as_posix()}'"
        ).fetchnumpy()["product_sk"]
        print(f"  {len(targets):,} candidate target products "
              f"({TARGET_MIN_REVIEWS}-{TARGET_MAX_REVIEWS} reviews), "
              f"{len(all_products):,} products overall")

        day_lo, day_hi = con.execute(
            f"SELECT min(day), max(day) FROM '{common.FACT_PARQUET.as_posix()}' "
            f"WHERE day IS NOT NULL").fetchone()
        # Honest ratings follow the corpus marginal so camouflage is indistinguishable
        # on rating alone.
        rating_p = np.array([0.0609, 0.0502, 0.0932, 0.2036, 0.5921])
        print(f"  day range {day_lo}-{day_hi}")

    with common.stage("10_inject: generate campaigns"):
        next_reviewer = common.EXPECTED_REVIEWERS
        next_review = common.EXPECTED_ROWS
        fact_rows, text_rows, campaign_rows, membership = [], [], [], []
        campaign_id = 0

        cells = [(g, p, w, rho, cam)
                 for g in GRID["G"] for p in GRID["P"] for w in GRID["W"]
                 for rho in GRID["rho"] for cam in GRID["camouflage"]]
        print(f"  {len(cells)} grid cells x {CAMPAIGNS_PER_CELL} campaigns "
              f"= {len(cells) * CAMPAIGNS_PER_CELL} campaigns")

        for g, p, w, rho, cam in cells:
            for _ in range(CAMPAIGNS_PER_CELL):
                start_day = int(rng.integers(day_lo, day_hi - w))
                products = rng.choice(targets, size=p, replace=False)
                template_idx = int(rng.integers(len(texts)))
                accounts = list(range(next_reviewer, next_reviewer + g))
                next_reviewer += g
                n_honest = HONEST_CAMOUFLAGED if cam else HONEST_MINIMAL

                for reviewer_sk in accounts:
                    used: set[int] = set()
                    # --- promotional reviews: same products, same window --------
                    for product_sk in products:
                        used.add(int(product_sk))
                        use_template = rng.random() < rho
                        idx = template_idx if use_template else int(rng.integers(len(texts)))
                        body = texts[idx]
                        head = summaries[idx]
                        fact_rows.append((
                            next_review, reviewer_sk, int(product_sk),
                            start_day + int(rng.integers(0, w + 1)),
                            int(rng.choice([5, 5, 5, 4])), 0, 0,
                            len(body), len(body.split()),
                            body.count("!"), sum(c.isupper() for c in body),
                            norm_hash(body), xxhash.xxh64_intdigest(head), False))
                        text_rows.append((next_review, f"SYNTH{reviewer_sk:08d}",
                                          f"SYNTHP{int(product_sk):08d}", body, head,
                                          len(body), len(body.split()),
                                          xxhash.xxh64_intdigest(body), norm_hash(body)))
                        next_review += 1

                    # --- honest reviews: random products, spread over time -------
                    honest = rng.choice(all_products, size=n_honest * 2, replace=False)
                    placed = 0
                    for product_sk in honest:
                        if placed >= n_honest:
                            break
                        if int(product_sk) in used:
                            continue
                        used.add(int(product_sk))
                        idx = int(rng.integers(len(texts)))
                        body, head = texts[idx], summaries[idx]
                        fact_rows.append((
                            next_review, reviewer_sk, int(product_sk),
                            int(rng.integers(day_lo, day_hi)),
                            int(rng.choice([1, 2, 3, 4, 5], p=rating_p)), 0, 0,
                            len(body), len(body.split()),
                            body.count("!"), sum(c.isupper() for c in body),
                            norm_hash(body), xxhash.xxh64_intdigest(head), False))
                        text_rows.append((next_review, f"SYNTH{reviewer_sk:08d}",
                                          f"SYNTHP{int(product_sk):08d}", body, head,
                                          len(body), len(body.split()),
                                          xxhash.xxh64_intdigest(body), norm_hash(body)))
                        next_review += 1
                        placed += 1

                    membership.append((reviewer_sk, campaign_id))

                campaign_rows.append((campaign_id, g, p, w, rho, cam, start_day,
                                      f"G{g}_P{p}_W{w}_rho{rho}_{'cam' if cam else 'bare'}"))
                campaign_id += 1

        n_synth_reviewers = next_reviewer - common.EXPECTED_REVIEWERS
        n_synth_reviews = next_review - common.EXPECTED_ROWS
        print(f"  {campaign_id:,} campaigns, {n_synth_reviewers:,} synthetic accounts, "
              f"{n_synth_reviews:,} synthetic reviews "
              f"({100 * n_synth_reviews / common.EXPECTED_ROWS:.3f}% of the corpus)")

    with common.stage("10_inject: write augmented fact, text, dim and campaign tables"):
        fact_schema = pa.schema([
            ("review_sk", pa.int32()), ("reviewer_sk", pa.int32()),
            ("product_sk", pa.int32()), ("day", pa.int32()), ("rating", pa.int8()),
            ("helpful_yes", pa.int32()), ("helpful_total", pa.int32()),
            ("n_chars", pa.int32()), ("n_words", pa.int32()),
            ("n_exclaim", pa.int16()), ("n_upper", pa.int32()),
            ("norm_text_hash", pa.uint64()), ("summary_hash", pa.uint64()),
            ("summary_is_text", pa.bool_())])
        synth_fact = pa.Table.from_arrays(
            [pa.array([r[i] for r in fact_rows], type=fact_schema.field(i).type)
             for i in range(len(fact_schema))], schema=fact_schema)
        con.register("synth_fact", synth_fact)
        con.execute(f"""
            COPY (SELECT * FROM '{common.FACT_PARQUET.as_posix()}'
                  UNION ALL BY NAME SELECT * FROM synth_fact)
            TO '{FACT_INJ.as_posix()}'
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)
        """)

        text_schema = pa.schema([
            ("review_sk", pa.int64()), ("reviewerID", pa.string()), ("asin", pa.string()),
            ("reviewText", pa.string()), ("summary", pa.string()),
            ("n_chars", pa.int32()), ("n_words", pa.int32()),
            ("text_hash", pa.uint64()), ("norm_text_hash", pa.uint64())])
        pq.write_table(pa.Table.from_arrays(
            [pa.array([r[i] for r in text_rows], type=text_schema.field(i).type)
             for i in range(len(text_schema))], schema=text_schema),
            SYNTH_TEXT, compression="zstd")

        con.execute(f"""
            COPY (
                SELECT * FROM '{(common.DATA / 'dim' / 'dim_reviewer.parquet').as_posix()}'
                UNION ALL BY NAME
                SELECT DISTINCT reviewer_sk,
                       'SYNTH' || lpad((reviewer_sk)::VARCHAR, 8, '0') AS reviewerID,
                       'synthetic-' || (reviewer_sk)::VARCHAR          AS reviewer_name,
                       1::SMALLINT                                     AS n_distinct_names
                FROM synth_fact
            ) TO '{DIM_INJ.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        con.execute("CREATE OR REPLACE TEMP TABLE camp (campaign_id INTEGER, g INTEGER, "
                    "p INTEGER, w INTEGER, rho DOUBLE, camouflage BOOLEAN, "
                    "start_day INTEGER, cell VARCHAR)")
        con.executemany("INSERT INTO camp VALUES (?, ?, ?, ?, ?, ?, ?, ?)", campaign_rows)
        con.execute("CREATE OR REPLACE TEMP TABLE memb (reviewer_sk INTEGER, "
                    "campaign_id INTEGER)")
        con.executemany("INSERT INTO memb VALUES (?, ?)", membership)
        con.execute(f"""
            COPY (SELECT m.reviewer_sk, c.* FROM memb m JOIN camp c USING (campaign_id))
            TO '{CAMPAIGNS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

    print("\n[verify]")
    total = con.execute(f"SELECT count(*) FROM '{FACT_INJ.as_posix()}'").fetchone()[0]
    print(f"  augmented fact rows: {total:,} "
          f"(= {common.EXPECTED_ROWS:,} real + {n_synth_reviews:,} synthetic)")
    if total != common.EXPECTED_ROWS + n_synth_reviews:
        raise SystemExit("FAIL: augmented fact row count does not reconcile")
    dupes = con.execute(f"""
        SELECT count(*) FROM (
            SELECT reviewer_sk, product_sk FROM '{FACT_INJ.as_posix()}'
            GROUP BY 1, 2 HAVING count(*) > 1)""").fetchone()[0]
    print(f"  duplicate (reviewer, product) pairs introduced: {dupes:,}")
    if dupes:
        raise SystemExit("FAIL: injection broke the one-review-per-user-per-product invariant")

    for label, path in (("fact_inj", FACT_INJ), ("synth_text", SYNTH_TEXT),
                        ("dim_reviewer_inj", DIM_INJ), ("campaigns", CAMPAIGNS)):
        print(f"  {label:<18} {common.mb(path):8.1f} MB")

    con.close()
    print(f"""
Stage 10 complete. Now re-run the feature/score stages over the augmented data:

  set BDA_NAMESPACE=_inj
  set BDA_FACT={FACT_INJ}
  set BDA_SYNTH_TEXT={SYNTH_TEXT}
  set BDA_SYNTH_BANDS={SYNTH_BANDS}
  python pipeline/06b_minhash_synth.py
  python pipeline/04_features.py && python pipeline/05_duplicates.py
  python pipeline/07_neardup.py && python pipeline/08_graph.py && python pipeline/09_score.py
  python pipeline/11_validate.py
""")


if __name__ == "__main__":
    main()
