"""Stage 6b -- MinHash band hashes for the synthetic injected documents only.

Reuses the exact permutations, shingle size and band layout from stage 6 (they
are module constants seeded from a fixed value), so the synthetic bands live in
the same hash space as the real ones and collide with them correctly. Running
the full stage 6 again over 41M documents to add ~70k would be absurd.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

spec = importlib.util.spec_from_file_location("minhash", HERE / "06_minhash.py")
minhash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(minhash)


def main() -> None:
    synth_text = os.environ.get("BDA_SYNTH_TEXT")
    out = os.environ.get("BDA_SYNTH_BANDS")
    if not synth_text or not out:
        raise SystemExit("Set BDA_SYNTH_TEXT and BDA_SYNTH_BANDS first (see stage 10).")

    con = common.connect()
    rows = con.execute(
        f"SELECT review_sk, reviewText FROM '{Path(synth_text).as_posix()}' "
        f"WHERE n_words >= {common.MIN_WORDS_FOR_NEARDUP} ORDER BY review_sk").fetchall()
    con.close()
    print(f"{len(rows):,} synthetic documents with >= {common.MIN_WORDS_FOR_NEARDUP} words")

    with common.stage("06b_minhash_synth: synthetic band hashes"):
        review_sk = np.array([r[0] for r in rows], dtype=np.int32)
        sigs = np.empty((len(rows), minhash.N_PERMS), dtype=np.uint64)
        for i, (_, text) in enumerate(rows):
            sigs[i] = minhash.signature(text)
        arrays = [pa.array(review_sk)] + [pa.array(c) for c in minhash.band_hashes(sigs)]
        pq.write_table(pa.Table.from_arrays(arrays, schema=minhash.SCHEMA), out,
                       compression="zstd", compression_level=3)

    print(f"  wrote {out} ({common.mb(Path(out)):.1f} MB)")


if __name__ == "__main__":
    main()
