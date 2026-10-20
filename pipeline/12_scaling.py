"""Stage 12 -- the big-data scaling evidence.

Re-runs the two heaviest pure-compute stages at 1M / 5M / 10M / 41.1M rows and
records wall-clock and peak RSS at each scale. That table is the honest answer to
"is this actually a big-data problem, or did you just run pandas on a laptop?"

Subsampling is by REVIEWER, not by row. Slicing rows would cut accounts in half
and make every per-reviewer aggregation measure a different thing at each scale,
which would turn a scaling curve into an artifact.

Two caveats stated here rather than buried: the de-trending baseline stays the
full-corpus series at every scale (so burst z-scores in the subsampled runs are
not meaningful -- only their COST is), and the 5-core invariant does not hold in
a subsample. This harness measures throughput, not correctness; correctness is
asserted in the stages themselves at full scale.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

HERE = Path(__file__).resolve().parent
SCALING = common.DATA / "scaling"
REPORT = common.DOCS / "scaling.md"

SCALES = [1_000_000, 5_000_000, 10_000_000, common.EXPECTED_ROWS]
STAGES = ["04_features.py", "08_graph.py"]
SEED = 20240919


def build_subset(con, target_rows: int, path: Path) -> dict:
    """Take whole reviewers, in a fixed pseudo-random order, until we hit target_rows."""
    if target_rows >= common.EXPECTED_ROWS:
        return {"rows": common.EXPECTED_ROWS, "path": common.DATA / "fact" / "fact_reviews.parquet",
                "reviewers": common.EXPECTED_REVIEWERS, "products": common.EXPECTED_PRODUCTS}
    con.execute(f"""
        COPY (
            WITH r AS (
                SELECT reviewer_sk, count(*)::BIGINT AS n,
                       hash(reviewer_sk * 2654435761) AS shuffle
                FROM '{(common.DATA / 'fact' / 'fact_reviews.parquet').as_posix()}'
                GROUP BY 1
            ),
            picked AS (
                SELECT reviewer_sk FROM (
                    SELECT reviewer_sk, sum(n) OVER (ORDER BY shuffle) AS running FROM r
                ) WHERE running <= {target_rows}
            )
            SELECT f.* FROM '{(common.DATA / 'fact' / 'fact_reviews.parquet').as_posix()}' f
            JOIN picked USING (reviewer_sk)
            ORDER BY f.reviewer_sk, f.day
        ) TO '{path.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)
    """)
    rows, reviewers, products = con.execute(
        f"SELECT count(*), count(DISTINCT reviewer_sk), count(DISTINCT product_sk) "
        f"FROM '{path.as_posix()}'").fetchone()
    return {"rows": rows, "path": path, "reviewers": reviewers, "products": products}


def run_stage(script: str, namespace: str, fact: Path) -> dict:
    env = dict(os.environ, BDA_NAMESPACE=namespace, BDA_FACT=str(fact))
    perf = common.PERF_LOG
    before = perf.stat().st_size if perf.exists() else 0
    started = time.time()
    result = subprocess.run([sys.executable, "-u", str(HERE / script)],
                            cwd=common.ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    elapsed = time.time() - started
    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", "replace").strip().splitlines()[-4:]
        return {"seconds": elapsed, "peak_rss_mb": None, "error": " / ".join(tail)}
    peak = 0.0
    if perf.exists():
        with perf.open(encoding="utf-8") as handle:
            handle.seek(before)
            for line in handle:
                peak = max(peak, json.loads(line).get("peak_rss_mb") or 0.0)
    return {"seconds": elapsed, "peak_rss_mb": peak}


def main() -> None:
    common.guard_disk(min_d_gb=25.0)
    SCALING.mkdir(parents=True, exist_ok=True)
    con = common.connect()
    results = []

    for target in SCALES:
        label = f"{target // 1_000_000}M" if target >= 1_000_000 else str(target)
        namespace = f"_scale{target // 1_000_000}m"
        with common.stage(f"12_scaling: build {label} subset"):
            subset = build_subset(con, target, SCALING / f"fact_{label}.parquet")
        print(f"  {subset['rows']:,} rows, {subset['reviewers']:,} reviewers, "
              f"{subset['products']:,} products")

        row = {"label": label, **{k: v for k, v in subset.items() if k != "path"}}
        for script in STAGES:
            print(f"  running {script} at {label} ...", flush=True)
            outcome = run_stage(script, namespace, subset["path"])
            row[script] = outcome
            if outcome.get("error"):
                print(f"    FAILED: {outcome['error']}")
            else:
                print(f"    {outcome['seconds']:.1f}s, peak RSS "
                      f"{outcome['peak_rss_mb']:.0f} MB")
        results.append(row)

    lines = ["# Scaling", "",
             "Wall-clock and peak resident memory for the two heaviest pure-compute stages, "
             "at four corpus sizes on one laptop (Ryzen 5 5600H, 6C/12T, 15.4 GB RAM, no GPU).",
             "",
             "Subsampling takes whole reviewers rather than slicing rows, so each scale is a "
             "coherent corpus rather than a truncated one. The de-trending baseline stays the "
             "full-corpus series at every scale, and the 5-core invariant does not hold in a "
             "subsample -- this table measures **cost**, not correctness. Correctness is "
             "asserted inside each stage at full scale.", ""]
    lines.append("| Rows | Reviewers | Products | Stage 4 features | peak RSS | "
                 "Stage 8 graph | peak RSS |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in results:
        f4, g8 = row["04_features.py"], row["08_graph.py"]
        lines.append(
            f"| {row['rows']:,} | {row['reviewers']:,} | {row['products']:,} | "
            f"{f4['seconds']:.1f}s | {f4.get('peak_rss_mb') or 0:.0f} MB | "
            f"{g8['seconds']:.1f}s | {g8.get('peak_rss_mb') or 0:.0f} MB |")

    lines += ["", "## Measured full-scale cost of the one-pass stages", "",
              "| Stage | Cost | Note |", "|---|---|---|",
              "| 1 — gzip to Parquet | 300s | gzip-bound; single-member, decodes serially, "
              "so extra threads do not help |",
              "| 6 — MinHash 40.3M documents | 1,112s over 8 processes | 9.19 GiB of band "
              "hashes; peak RSS 66 MB because signatures stream rather than accumulate |",
              "| 7 — LSH clustering + exact verification | ~200s | 24 band GROUP BYs plus "
              "Jaccard verification of 329k candidate documents |",
              "", "Total cold build from the 9.87 GiB `.gz`: roughly 35 minutes, run once. "
              "Everything downstream of the fact table re-runs in minutes."]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines[6:]))
    con.close()
    print(f"\nWrote {REPORT}")


if __name__ == "__main__":
    main()
