"""Stage 9 -- cull the feature set, then build the suspicion score.

The score is deliberately NOT a weighted sum of hand-picked coefficients. It is a
rank aggregation over three families that share no features:

    T  text      duplicate and near-duplicate membership, self-reuse, style
    B  behaviour de-trended burst, rating deviation, cadence, tenure
    G  graph     co-review degree, ring membership and density, product centrality

Why this shape:

* Every feature goes through its EMPIRICAL CDF first, so the score is invariant to
  each feature's units and to its base rate. This matters enormously in a corpus
  that is 59.21% five-star -- a raw threshold on "mostly positive" flags three
  fifths of everyone, while its ECDF percentile does not.

* Families are disjoint BY CONTRACT, checked by tests/test_score_contract.py. That
  buys the strongest claim available without labels: if S_T, S_B and S_G -- three
  information sources that share no input -- agree on who is at the top, that
  agreement is evidence. If they were allowed to share features, it would be
  circular.

* Collinear features are culled BEFORE aggregation at |Spearman| > 0.85. Without
  this, "writes a lot" enters the score three times under three names and silently
  triples its own weight.

* NO helpful-vote quantity appears anywhere here. Those are reserved as the
  Stage 10 validation proxy; using them both to score and to validate would make
  the AUC meaningless.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

FEATURES = common.DATA / "features"
GRAPH = common.DATA / "graph"
SCORES = common.DATA / "scores"
OUT_SCORES = common.ns(SCORES / "reviewer_scores.parquet")
OUT_CONTRIB = common.ns(SCORES / "reviewer_contributions.parquet")
OUT_HIST = common.ns(SCORES / "score_histogram.parquet")
OUT_META = common.ns(SCORES / "score_meta.json")

CULL_THRESHOLD = 0.85
HIST_BINS = 200
SAMPLE_FOR_STATS = 300_000

# name -> (family, direction). direction "high" means a large value is the
# suspicious end; "low" means a small value is.
FEATURE_SPEC: dict[str, tuple[str, str]] = {
    # ---- T: text ---------------------------------------------------------
    "self_dup_rate":          ("T", "high"),
    "summary_reuse_rate":     ("T", "high"),
    "summary_is_text_rate":   ("T", "high"),
    "exact_dup_rate":         ("T", "high"),
    "neardup_rate":           ("T", "high"),
    "neardup_max_cluster":    ("T", "high"),
    "mean_words":             ("T", "low"),    # Mukherjee et al. RL
    "words_cv":               ("T", "low"),    # uniform length reads as templated
    "exclaim_rate":           ("T", "high"),
    "upper_rate":             ("T", "high"),
    # ---- B: behaviour ----------------------------------------------------
    "max_per_day":            ("B", "high"),   # Mukherjee et al. MNR
    "max_in_7d":              ("B", "high"),
    "reviews_per_active_day": ("B", "high"),
    "lifespan_days":          ("B", "low"),    # compressed tenure
    "gap_cv":                 ("B", "high"),   # bursty rather than steady
    "rating_entropy":         ("B", "low"),    # does the account discriminate at all
    "loo_rating_dev":         ("B", "high"),   # Mukherjee et al. RD
    "early_tendency":         ("B", "low"),    # arrives early in a product's life
    # ---- G: graph --------------------------------------------------------
    "coreview_degree":        ("G", "high"),
    "coreview_weight":        ("G", "high"),
    "ring_size":              ("G", "high"),
    "ring_density":           ("G", "high"),
    "mean_product_pagerank":  ("G", "high"),
    "max_product_eigen":      ("G", "high"),
}

# Deliberately excluded, and why:
#   frac_5star / frac_extreme / mean_rating -- rating LEVELS; see the hard rule.
#   n_reviews / n_active_days               -- raw volume; already implied by the
#                                              cadence features and would dominate.
#   helpful_ratio / votes_* / frac_zero_votes -- reserved as the validation proxy.
#   n_distinct_names                        -- surfaced in the UI as context, but it
#                                              belongs to no family cleanly.
EXCLUDED = {"frac_5star", "frac_extreme", "mean_rating", "n_reviews", "n_active_days",
            "helpful_ratio", "votes_total", "votes_helpful", "frac_zero_votes",
            "n_distinct_names"}


def ecdf(values: np.ndarray, direction: str) -> np.ndarray:
    """Empirical CDF to [0, 1]. Ties share a percentile, as they should."""
    ranks = rankdata(values, method="average")
    scaled = (ranks - 0.5) / len(values)
    return scaled if direction == "high" else 1.0 - scaled


def build_matrix(con) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Assemble the per-reviewer feature matrix from every upstream stage."""
    con.execute(f"""
        CREATE OR REPLACE VIEW base AS
        WITH
        exact_dup AS (
            SELECT reviewer_sk, count(*)::INTEGER AS n_exact_dup
            FROM '{common.ns(FEATURES / 'dup_members.parquet').as_posix()}' GROUP BY 1
        ),
        nd AS (
            SELECT m.reviewer_sk,
                   count(*)::INTEGER       AS n_neardup,
                   max(c.n_reviews)        AS neardup_max_cluster
            FROM '{common.ns(FEATURES / 'neardup_members.parquet').as_posix()}' m
            JOIN '{common.ns(FEATURES / 'neardup_clusters.parquet').as_posix()}' c
              ON c.config = m.config AND c.cluster_id = m.cluster_id
            WHERE m.config = 'loose'
            GROUP BY 1
        ),
        pgraph AS (
            SELECT f.reviewer_sk,
                   avg(pc.pg_pagerank) AS mean_product_pagerank,
                   max(pc.pg_eigen)    AS max_product_eigen
            FROM '{common.FACT_PARQUET.as_posix()}' f
            JOIN '{common.ns(GRAPH / 'product_centrality.parquet').as_posix()}' pc
              USING (product_sk)
            GROUP BY 1
        )
        SELECT r.reviewer_sk, r.n_reviews,
               r.self_dup_rate, r.summary_reuse_rate, r.summary_is_text_rate,
               coalesce(ed.n_exact_dup, 0)::DOUBLE / r.n_reviews  AS exact_dup_rate,
               coalesce(nd.n_neardup, 0)::DOUBLE / r.n_reviews    AS neardup_rate,
               coalesce(nd.neardup_max_cluster, 0)::DOUBLE        AS neardup_max_cluster,
               r.mean_words, r.words_cv, r.exclaim_rate, r.upper_rate,
               r.max_per_day::DOUBLE      AS max_per_day,
               r.max_in_7d::DOUBLE        AS max_in_7d,
               r.reviews_per_active_day,
               r.lifespan_days::DOUBLE    AS lifespan_days,
               r.gap_cv, r.rating_entropy, r.loo_rating_dev, r.early_tendency,
               coalesce(rm.coreview_degree, 0)::DOUBLE AS coreview_degree,
               coalesce(rm.coreview_weight, 0.0)       AS coreview_weight,
               coalesce(rm.ring_size, 0)::DOUBLE       AS ring_size,
               coalesce(rm.ring_density, 0.0)          AS ring_density,
               coalesce(pg.mean_product_pagerank, 0.0) AS mean_product_pagerank,
               coalesce(pg.max_product_eigen, 0.0)     AS max_product_eigen
        FROM '{common.ns(FEATURES / 'feat_reviewer.parquet').as_posix()}' r
        LEFT JOIN exact_dup ed USING (reviewer_sk)
        LEFT JOIN nd           USING (reviewer_sk)
        LEFT JOIN '{common.ns(GRAPH / 'ring_members.parquet').as_posix()}' rm USING (reviewer_sk)
        LEFT JOIN pgraph pg    USING (reviewer_sk)
        ORDER BY r.reviewer_sk
    """)
    names = list(FEATURE_SPEC)
    data = con.execute(f"SELECT reviewer_sk, {', '.join(names)} FROM base").fetchnumpy()
    reviewer_sk = data["reviewer_sk"].astype(np.int32)
    matrix = np.column_stack([np.nan_to_num(data[n].astype(np.float64), nan=0.0,
                                            posinf=0.0, neginf=0.0) for n in names])
    return matrix, names, reviewer_sk


MIN_ACTIVE_FOR_CULL = 2_000


def cull(matrix: np.ndarray, names: list[str], rng):
    """Drop the weaker half of any near-collinear pair, within family.

    Correlation is measured on the ACTIVE subset -- rows where at least one of the
    pair is non-zero -- not on the whole population. Most graph and duplicate
    features are zero for well over 99% of accounts, and a Spearman computed over
    that mass of ties comes back at exactly 1.000 for any two sparse features,
    which would cull genuinely different signals. `ring_size` and `ring_density`
    are a real example: identical on the 99.99% of accounts in no ring, and
    completely different on the accounts that matter.
    """
    idx = rng.choice(len(matrix), size=min(SAMPLE_FOR_STATS, len(matrix)), replace=False)
    sample = matrix[idx]
    spread = sample.std(axis=0)

    # The full pairwise matrix, measured exactly the way the cull measures it, is
    # persisted so the dashboard's heatmap and this cull can never disagree. A
    # heatmap computed independently over the whole population would report 1.000
    # for every pair of sparse features and would accuse this cull of a bug.
    size = len(names)
    matrix: list[list[float | None]] = [[None] * size for _ in range(size)]
    active_counts = [[0] * size for _ in range(size)]

    dropped, kept, notes = set(), [], []
    for i, name in enumerate(names):
        for j in range(i, size):
            other = names[j]
            if i == j:
                matrix[i][j] = 1.0
                active_counts[i][j] = len(sample)
                continue
            a, b = sample[:, i], sample[:, j]
            active = (a != 0) | (b != 0)
            n_active = int(active.sum())
            active_counts[i][j] = active_counts[j][i] = n_active
            if n_active >= MIN_ACTIVE_FOR_CULL:
                r = spearmanr(a[active], b[active]).statistic
                if np.isfinite(r):
                    matrix[i][j] = matrix[j][i] = round(float(r), 4)

    for i, name in enumerate(names):
        if name in dropped:
            continue
        for j in range(i + 1, size):
            other = names[j]
            if other in dropped or FEATURE_SPEC[other][0] != FEATURE_SPEC[name][0]:
                continue
            r = matrix[i][j]
            if r is not None and abs(r) > CULL_THRESHOLD:
                loser = other if spread[j] <= spread[i] else name
                winner = name if loser == other else other
                dropped.add(loser)
                notes.append((loser, winner, round(float(r), 3), active_counts[i][j]))
                if loser == name:
                    break
        if name not in dropped:
            kept.append(name)
    return kept, notes, matrix, active_counts


def main() -> None:
    SCORES.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20240919)
    con = common.connect()

    with common.stage("09_score: assemble feature matrix"):
        matrix, names, reviewer_sk = build_matrix(con)
        common.expect(len(reviewer_sk), common.EXPECTED_REVIEWERS, "reviewers in matrix")
        overlap = set(names) & EXCLUDED
        if overlap:
            raise SystemExit(f"FAIL: excluded features leaked into the score: {overlap}")
        print(f"  {matrix.shape[0]:,} reviewers x {matrix.shape[1]} candidate features")

    with common.stage(f"09_score: collinearity cull at |rho| > {CULL_THRESHOLD}"):
        kept, notes, corr_matrix, corr_active = cull(matrix, names, rng)
        for loser, winner, r, active in notes:
            print(f"  drop {loser:<24} (Spearman {r:+.3f} with {winner}, "
                  f"measured on {active:,} active rows)")
        print(f"  {len(kept)}/{len(names)} features survive")
        for family in ("T", "B", "G"):
            members = [n for n in kept if FEATURE_SPEC[n][0] == family]
            print(f"    {family}: {len(members):>2}  {', '.join(members)}")
        if not all(any(FEATURE_SPEC[n][0] == fam for n in kept) for fam in "TBG"):
            raise SystemExit("FAIL: a family was culled to nothing.")

    with common.stage("09_score: ECDF transform and rank aggregation"):
        column = {n: i for i, n in enumerate(names)}
        percentiles = {n: ecdf(matrix[:, column[n]], FEATURE_SPEC[n][1]) for n in kept}
        family_scores = {}
        for family in ("T", "B", "G"):
            members = [n for n in kept if FEATURE_SPEC[n][0] == family]
            family_scores[family] = np.mean([percentiles[n] for n in members], axis=0)
        # Aggregate ACROSS families by rank again, so a family with a heavy-tailed
        # internal distribution cannot dominate the other two.
        family_ranks = {f: (rankdata(v, method="average") - 0.5) / len(v)
                        for f, v in family_scores.items()}
        stacked = np.vstack(list(family_ranks.values()))
        # Two aggregations, because they answer different questions and the
        # measured family agreement is weak (Spearman 0.03-0.16 between families):
        #   score      consensus -- high only if SEVERAL independent families agree.
        #                           High precision, low recall, and the defensible one.
        #   score_any  max       -- high if ANY single family screams. Higher recall,
        #                           weaker evidence. Exposed so the dashboard can
        #                           switch between "strongest evidence" and "widest net".
        score = stacked.mean(axis=0)
        score_any = stacked.max(axis=0)

    with common.stage("09_score: family agreement against a permutation null"):
        idx = rng.choice(len(score), size=min(SAMPLE_FOR_STATS, len(score)), replace=False)
        agreement = {}
        for a, b in (("T", "B"), ("T", "G"), ("B", "G")):
            agreement[f"spearman_{a}{b}"] = round(
                float(spearmanr(family_scores[a][idx], family_scores[b][idx]).statistic), 4)
        n = len(score)
        print(f"  {'k':>9} {'pair T&B':>18} {'pair T&G':>18} {'pair B&G':>18} "
              f"{'all three':>18}")
        for k in (1_000, 10_000, 100_000, 300_000):
            tops = {f: set(np.argpartition(-v, k)[:k]) for f, v in family_scores.items()}
            cells = []
            for label, members in (("TB", ("T", "B")), ("TG", ("T", "G")),
                                   ("BG", ("B", "G")), ("TBG", ("T", "B", "G"))):
                hit = len(set.intersection(*(tops[m] for m in members)))
                exp = k * (k / n) ** (len(members) - 1)
                agreement[f"overlap_{label}_at_{k}"] = hit
                agreement[f"overlap_{label}_at_{k}_expected"] = round(exp, 2)
                cells.append(f"{hit:,} vs {exp:,.1f}" if exp >= 5 else f"{hit:,} (n/a)")
            print(f"  {k:>9,} " + " ".join(f"{c:>18}" for c in cells))
        print("  observed vs chance-expected counts; 'n/a' = chance expectation below 5, "
              "where the comparison carries no information")
        for key in ("spearman_TB", "spearman_TG", "spearman_BG"):
            print(f"  {key} = {agreement[key]:+.4f}")

    with common.stage("09_score: write scores, contributions and histogram"):
        con.execute("CREATE OR REPLACE TEMP TABLE s (reviewer_sk INTEGER, score DOUBLE, "
                    "score_text DOUBLE, score_behaviour DOUBLE, score_graph DOUBLE)")
        con.register("s_df", {"reviewer_sk": reviewer_sk, "score": score,
                              "score_any": score_any,
                              "score_text": family_scores["T"],
                              "score_behaviour": family_scores["B"],
                              "score_graph": family_scores["G"]})
        con.execute(f"""
            COPY (
                SELECT d.reviewer_sk, d.reviewerID, d.reviewer_name,
                       s.score, s.score_any, s.score_text, s.score_behaviour, s.score_graph,
                       r.n_reviews, r.first_day, r.last_day, r.mean_rating,
                       r.max_per_day, r.lifespan_days,
                       coalesce(rm.ring_id, -1)    AS ring_id,
                       coalesce(rm.ring_size, 0)   AS ring_size
                FROM s_df s
                JOIN '{common.DIM_REVIEWER.as_posix()}' d USING (reviewer_sk)
                JOIN '{common.ns(FEATURES / 'feat_reviewer.parquet').as_posix()}' r USING (reviewer_sk)
                LEFT JOIN '{common.ns(GRAPH / 'ring_members.parquet').as_posix()}' rm USING (reviewer_sk)
            ) TO '{OUT_SCORES.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        # Per-feature percentile for the dashboard's explain panel.
        contrib = {"reviewer_sk": reviewer_sk}
        contrib.update({n: percentiles[n] for n in kept})
        con.register("c_df", contrib)
        con.execute(f"COPY c_df TO '{OUT_CONTRIB.as_posix()}' "
                    f"(FORMAT PARQUET, COMPRESSION ZSTD)")

        # Precomputed histogram so the dashboard's threshold slider costs no queries.
        edges = np.linspace(0.0, 1.0, HIST_BINS + 1)
        rows = [{"bin_lo": edges[i], "bin_hi": edges[i + 1],
                 "n": int(c), "family": "all"}
                for i, c in enumerate(np.histogram(score, bins=edges)[0])]
        rows += [{"bin_lo": edges[i], "bin_hi": edges[i + 1], "n": int(c), "family": "any"}
                 for i, c in enumerate(np.histogram(score_any, bins=edges)[0])]
        for family, values in family_scores.items():
            rows += [{"bin_lo": edges[i], "bin_hi": edges[i + 1], "n": int(c),
                      "family": family}
                     for i, c in enumerate(np.histogram(values, bins=edges)[0])]
        con.register("h_df", {k: np.array([r[k] for r in rows]) for k in rows[0]})
        con.execute(f"COPY h_df TO '{OUT_HIST.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")

    OUT_META.write_text(json.dumps({
        "n_reviewers": int(len(score)),
        "candidate_features": names,
        "kept_features": kept,
        "culled": [{"dropped": d, "kept": k, "spearman": r, "active_rows": a}
                   for d, k, r, a in notes],
        "families": {f: [n for n in kept if FEATURE_SPEC[n][0] == f] for f in "TBG"},
        "excluded_by_contract": sorted(EXCLUDED),
        "cull_threshold": CULL_THRESHOLD,
        "min_active_for_cull": MIN_ACTIVE_FOR_CULL,
        "correlation": {
            "features": names,
            "matrix": corr_matrix,
            "active_rows": corr_active,
            "sample_rows": int(min(SAMPLE_FOR_STATS, len(score))),
        },
        "agreement": agreement,
    }, indent=2), encoding="utf-8")

    print("\n[top 15 by suspicion score]")
    rows = con.execute(f"""
        SELECT reviewerID, coalesce(reviewer_name, '(none)') AS name, round(score, 4),
               round(score_text, 3), round(score_behaviour, 3), round(score_graph, 3),
               n_reviews, max_per_day, lifespan_days, ring_size
        FROM '{OUT_SCORES.as_posix()}' ORDER BY score DESC LIMIT 15""").fetchall()
    print(f"  {'reviewerID':<16} {'name':<20} {'score':>7} {'T':>6} {'B':>6} {'G':>6} "
          f"{'revs':>6} {'max/d':>6} {'span':>6} {'ring':>5}")
    for row in rows:
        print(f"  {row[0]:<16} {str(row[1])[:20]:<20} {row[2]:>7} {row[3]:>6} {row[4]:>6} "
              f"{row[5]:>6} {row[6]:>6} {row[7]:>6} {row[8]:>6} {row[9]:>5}")

    con.close()
    print(f"\nStage 9 complete. Metadata: {OUT_META}")


if __name__ == "__main__":
    main()
