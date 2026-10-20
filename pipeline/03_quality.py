"""Stage 3 -- data-quality report and the global baselines every later stage needs.

Two outputs:
  docs/data_quality.md                          the report
  data/features/baseline_daily_volume.parquet   reviews per day across the whole corpus

The baseline is not optional. 2013 alone holds 14.79M of the 41.1M reviews while
1997 holds 2,707, so any burst detector that does not de-trend against this
series is just rediscovering Amazon's growth curve.

It also counts how many reviewers clear >=50 total helpful votes, which is what
determines whether the Stage 9 held-out-AUC study has any statistical power.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

BASELINE = common.DATA / "features" / "baseline_daily_volume.parquet"
REPORT = common.DOCS / "data_quality.md"


def table(rows, headers) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(out)


def main() -> None:
    con = common.connect()
    fact = f"'{common.FACT_PARQUET.as_posix()}'"
    raw = f"'{common.RAW_PARQUET.as_posix()}'"
    con.execute(f"CREATE VIEW f AS SELECT * FROM {fact}")
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    with common.stage("03_quality: report and baselines"):
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        REPORT.parent.mkdir(parents=True, exist_ok=True)

        emit("# Data quality report\n")
        emit("Source: `kcore_5.json.gz` - McAuley/UCSD Amazon product data, 2014 release, "
             "complete review data, 5-core.\n")

        # ---- shape ---------------------------------------------------------
        rows, reviewers, products = con.execute(
            "SELECT count(*), count(DISTINCT reviewer_sk), count(DISTINCT product_sk) FROM f"
        ).fetchone()
        emit("## Shape\n")
        emit(table([("Reviews", f"{rows:,}"), ("Reviewers", f"{reviewers:,}"),
                    ("Products", f"{products:,}"),
                    ("Reviews per reviewer (mean)", f"{rows / reviewers:.2f}"),
                    ("Reviews per product (mean)", f"{rows / products:.2f}")],
                   ["Measure", "Value"]))
        emit()

        # ---- 5-core invariant ----------------------------------------------
        rmin, rmax = con.execute(
            "SELECT min(n), max(n) FROM (SELECT count(*) n FROM f GROUP BY reviewer_sk)").fetchone()
        pmin, pmax = con.execute(
            "SELECT min(n), max(n) FROM (SELECT count(*) n FROM f GROUP BY product_sk)").fetchone()
        emit("## 5-core invariant\n")
        emit(f"- Reviews per reviewer: min **{rmin}**, max **{rmax:,}**")
        emit(f"- Reviews per product: min **{pmin}**, max **{pmax:,}**")
        emit(f"- Invariant holds: **{rmin >= 5 and pmin >= 5}**\n")
        emit("> Consequence: there are no singleton reviewers, so every method that targets "
             "them (Xie et al. KDD 2012; SpEagle's ISR feature) has an empty target population "
             "in this corpus by construction.\n")

        # ---- completeness ---------------------------------------------------
        null_name, empty_text, null_day = con.execute(f"""
            SELECT (SELECT count(*) FROM {raw} WHERE reviewerName IS NULL),
                   (SELECT count(*) FROM {raw} WHERE n_chars = 0),
                   (SELECT count(*) FROM f WHERE day IS NULL)
        """).fetchone()
        emit("## Completeness\n")
        emit(table([("`reviewerName` null", f"{null_name:,}", f"{100 * null_name / rows:.2f}%"),
                    ("`reviewText` empty", f"{empty_text:,}", f"{100 * empty_text / rows:.4f}%"),
                    ("`unixReviewTime` null", f"{null_day:,}", f"{100 * null_day / rows:.6f}%")],
                   ["Field", "Missing", "Share"]))
        emit("\nEmpty review text and null timestamps are excluded from text and temporal "
             "features respectively, rather than imputed.\n")

        # ---- ratings ---------------------------------------------------------
        emit("## Rating distribution\n")
        emit(table([(r, f"{c:,}", f"{100 * c / rows:.2f}%")
                    for r, c in con.execute(
                        "SELECT rating, count(*) FROM f GROUP BY 1 ORDER BY 1").fetchall()],
                   ["Stars", "Reviews", "Share"]))
        emit("\n> The corpus is 59.21% five-star. Any feature that flags 'mostly positive' as "
             "a level therefore flags three fifths of everyone. Rating features enter the score "
             "**only** as a deviation from the product's own distribution, or as an "
             "empirical-CDF percentile.\n")

        # ---- text length ------------------------------------------------------
        pcts = con.execute("""
            SELECT quantile_cont(n_words, [0.01, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99]),
                   avg(n_words), avg(n_chars)
            FROM f WHERE n_chars > 0""").fetchone()
        emit("## Review length (words)\n")
        emit(table([("p1", f"{pcts[0][0]:.0f}"), ("p10", f"{pcts[0][1]:.0f}"),
                    ("p25", f"{pcts[0][2]:.0f}"), ("median", f"{pcts[0][3]:.0f}"),
                    ("p75", f"{pcts[0][4]:.0f}"), ("p90", f"{pcts[0][5]:.0f}"),
                    ("p99", f"{pcts[0][6]:.0f}"), ("mean words", f"{pcts[1]:.0f}"),
                    ("mean chars", f"{pcts[2]:.0f}")], ["Percentile", "Words"]))
        short = con.execute(
            f"SELECT count(*) FROM f WHERE n_words < {common.MIN_WORDS_FOR_NEARDUP}").fetchone()[0]
        emit(f"\nDocuments under {common.MIN_WORDS_FOR_NEARDUP} words: **{short:,}** "
             f"({100 * short / rows:.2f}%). These are excluded from near-duplicate detection - "
             "short text collides by chance, not by copying.\n")

        # ---- temporal ----------------------------------------------------------
        emit("## Temporal coverage\n")
        emit(table([(year, f"{count:,}", f"{100 * count / rows:.2f}%")
                    for year, count in con.execute("""
                        SELECT year(to_timestamp(day * 86400)) y, count(*)
                        FROM f WHERE day IS NOT NULL GROUP BY 1 ORDER BY 1""").fetchall()],
                   ["Year", "Reviews", "Share"]))
        emit("\nTimestamps are day-granular (midnight UTC), so no intra-day timing signal "
             "exists; burst detection operates at day resolution or coarser.\n")

        con.execute(f"""
            COPY (
                SELECT day,
                       count(*)::INTEGER AS n_reviews,
                       count(DISTINCT reviewer_sk)::INTEGER AS n_reviewers,
                       count(DISTINCT product_sk)::INTEGER AS n_products
                FROM f WHERE day IS NOT NULL GROUP BY day ORDER BY day
            ) TO '{BASELINE.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        n_days, busiest_n = con.execute(
            f"SELECT count(*), max(n_reviews) FROM '{BASELINE.as_posix()}'").fetchone()
        emit(f"Baseline series written: **{n_days:,} distinct days**. Busiest day carries "
             f"**{busiest_n:,}** reviews. Every temporal feature de-trends against this series "
             "using `E[c] = n_p * daily_volume(d) / 41,135,700` and `z = (c - E) / sqrt(E)`.\n")

        # ---- duplicates ---------------------------------------------------------
        emit("## Duplicate text\n")
        dup_rows = []
        for label, column, source, predicate in (
                ("Raw exact", "text_hash", raw, "n_chars > 0"),
                ("Normalised (lowercased, whitespace-collapsed)", "norm_text_hash", fact,
                 "n_chars > 0"),
                (f"Normalised, >= {common.MIN_WORDS_FOR_NEARDUP} words", "norm_text_hash", fact,
                 f"n_words >= {common.MIN_WORDS_FOR_NEARDUP}")):
            groups, covered, biggest = con.execute(f"""
                SELECT count(*), coalesce(sum(n), 0), coalesce(max(n), 0) FROM (
                    SELECT count(*) n FROM {source} WHERE {predicate}
                    GROUP BY {column} HAVING count(*) > 1)""").fetchone()
            dup_rows.append((label, f"{groups:,}", f"{covered:,}",
                             f"{100 * covered / rows:.3f}%", f"{biggest:,}"))
        emit(table(dup_rows, ["Key", "Clusters", "Reviews covered", "Share", "Largest cluster"]))
        emit("\n> Exact duplication is rare here. Jindal & Liu (WSDM 2008) built their "
             "pseudo-labels from a much denser duplicate population; in this corpus duplicate "
             "seeds are a small, high-precision set, **not** the backbone of the score. "
             "Near-duplicate detection (Stage 6) carries the text signal.\n")

        # ---- helpful votes / V2 statistical power ---------------------------------
        emit("## Helpfulness votes - and the power of the Stage 9 AUC study\n")
        with_votes, total_votes, helpful_votes = con.execute(
            "SELECT count(*) FILTER (WHERE helpful_total > 0), sum(helpful_total), "
            "sum(helpful_yes) FROM f").fetchone()
        emit(f"- Reviews with at least one vote: **{with_votes:,}** "
             f"({100 * with_votes / rows:.1f}%)")
        emit(f"- Total votes cast: **{total_votes:,}**, of which helpful: **{helpful_votes:,}** "
             f"({100 * helpful_votes / total_votes:.1f}%)\n")
        power = con.execute("""
            WITH r AS (
                SELECT reviewer_sk, sum(helpful_total) v, sum(helpful_yes) y
                FROM f GROUP BY reviewer_sk)
            SELECT count(*) FILTER (WHERE v >= 50),
                   count(*) FILTER (WHERE v >= 50 AND y::DOUBLE / v >= 0.75),
                   count(*) FILTER (WHERE v >= 50 AND y::DOUBLE / v <= 0.25)
            FROM r""").fetchone()
        emit(table([("Reviewers with >= 50 total votes", f"{power[0]:,}"),
                    ("  of which benign proxy (>= 0.75 helpful)", f"{power[1]:,}"),
                    ("  of which suspicious proxy (<= 0.25 helpful)", f"{power[2]:,}")],
                   ["Cohort", "Count"]))
        verdict = ("sufficient" if power[2] >= 1000 else
                   "THIN - report with an explicit caveat" if power[2] >= 200 else
                   "TOO THIN - V2 cannot support an AUC claim")
        emit(f"\n**Statistical power for V2: {verdict}.** The minority class "
             f"({power[2]:,} reviewers) bounds what the held-out AUC study can claim.\n")
        emit("> This is a *proxy*, not ground truth: helpful votes measure perceived usefulness "
             "and are themselves gameable. It is named as a proxy everywhere it is reported. "
             "No helpful-vote quantity enters the suspicion score - a unit test enforces this.\n")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {REPORT} and {BASELINE.name}")
    con.close()


if __name__ == "__main__":
    main()
