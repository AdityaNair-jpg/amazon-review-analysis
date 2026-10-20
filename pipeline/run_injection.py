"""Run the whole synthetic-injection validation end to end.

Generates planted campaigns, re-runs every feature and scoring stage over the
augmented corpus under the `_inj` namespace, then measures recall.

The re-run is the point: the injected accounts go through exactly the same SQL,
the same MinHash permutations, the same graph caps and the same rank aggregation
as the real ones. Nothing about the scoring pipeline knows they are synthetic, so
the recall number it produces is a measurement rather than an assertion.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VALIDATE = ROOT / "data" / "validate"

STAGES = [
    ("10_inject.py", "generate planted campaigns", False),
    ("06b_minhash_synth.py", "MinHash the synthetic text", True),
    ("04_features.py", "recompute reviewer and product features", True),
    ("05_duplicates.py", "recompute exact duplicate clusters", True),
    ("07_neardup.py", "recompute near-duplicate clusters", True),
    ("08_graph.py", "recompute both graph projections", True),
    ("09_score.py", "rescore every account", True),
    ("11_validate.py", "measure V1, V2 and V4", False),
]


def main() -> None:
    env = dict(os.environ)
    injected = {
        "BDA_NAMESPACE": "_inj",
        "BDA_FACT": str(VALIDATE / "fact_inj.parquet"),
        "BDA_SYNTH_TEXT": str(VALIDATE / "synth_text.parquet"),
        "BDA_SYNTH_BANDS": str(VALIDATE / "synth_bands.parquet"),
    }
    # 06b needs the synth paths but must NOT be namespaced -- it writes one file
    # whose path is given explicitly.
    synth_only = {k: v for k, v in injected.items() if k != "BDA_NAMESPACE"}

    started = time.time()
    for script, description, namespaced in STAGES:
        stage_env = dict(env)
        if script == "06b_minhash_synth.py":
            stage_env.update(synth_only)
        elif namespaced:
            stage_env.update(injected)
        elif script == "10_inject.py":
            pass  # reads the REAL corpus; must not be namespaced
        print(f"\n{'#' * 74}\n# {script}  --  {description}"
              f"{'  [namespace _inj]' if namespaced else ''}\n{'#' * 74}", flush=True)
        result = subprocess.run([sys.executable, "-u", str(HERE / script)],
                                cwd=ROOT, env=stage_env)
        if result.returncode != 0:
            raise SystemExit(f"\nFAILED at {script} (exit {result.returncode})")

    print(f"\nInjection validation complete in {(time.time() - started) / 60:.1f} min.")
    print("Report: docs/validation.md")


if __name__ == "__main__":
    main()
