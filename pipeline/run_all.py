"""Build everything from the source .gz, in order, with timings.

Cold build is roughly 35 minutes on the reference machine (Ryzen 5 5600H, 6C/12T,
15.4 GB RAM). Stages 1 and 6 dominate and are the only two that touch the full
text; everything after stage 2 re-runs in minutes.

Each stage asserts its own outputs against measured corpus totals and stops the
build on a mismatch, so a partial or corrupted artifact cannot silently propagate
into the dashboard.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

STAGES = [
    ("00_verify_env.py", "check imports, DuckDB settings and free disk", "~1s"),
    ("01_ingest.py", "gzip -> Parquet, the ONE pass over the source", "~5 min"),
    ("02_fact.py", "surrogate keys, dimensions, narrow fact table", "~2 min"),
    ("03_quality.py", "data-quality report and de-trending baseline", "~15s"),
    ("04_features.py", "reviewer and product features", "~1 min"),
    ("05_duplicates.py", "exact duplicate clusters", "~30s"),
    ("06_minhash.py", "MinHash + LSH band hashes (8 processes)", "~19 min"),
    ("07_neardup.py", "verified near-duplicate clusters", "~4 min"),
    ("08_graph.py", "co-review graph, rings, product centrality", "~14 min"),
    ("09_score.py", "feature cull, ECDF, rank aggregation", "~20s"),
]


def main() -> None:
    only = sys.argv[1:] or None
    started = time.time()
    timings = []
    for script, description, expected in STAGES:
        if only and not any(script.startswith(prefix) for prefix in only):
            continue
        print(f"\n{'=' * 78}\n  {script}  --  {description}   (expect {expected})"
              f"\n{'=' * 78}", flush=True)
        t0 = time.time()
        result = subprocess.run([sys.executable, "-u", str(HERE / script)], cwd=ROOT)
        elapsed = time.time() - t0
        timings.append((script, elapsed, result.returncode))
        if result.returncode != 0:
            print(f"\nBUILD FAILED at {script} after {elapsed:.0f}s "
                  f"(exit {result.returncode})")
            raise SystemExit(result.returncode)

    print(f"\n{'=' * 78}\n  BUILD COMPLETE in {(time.time() - started) / 60:.1f} min"
          f"\n{'=' * 78}")
    for script, elapsed, _ in timings:
        print(f"  {script:<24} {elapsed:8.1f}s")
    print("""
Next:
  python pipeline/run_injection.py    measure recall on planted campaigns (~25 min)
  python pipeline/12_scaling.py       the 1M/5M/10M/41M scaling table
  python -m pytest tests/ -q          contract and API tests
  python run.py                       build anything else missing, open the dashboard
""")


if __name__ == "__main__":
    main()
