"""Stage 6 -- MinHash signatures and LSH band hashes for near-duplicate detection.

The longest job in the pipeline, and the last one that touches the full text.

Design notes that matter:

* The full 128-permutation signature matrix is 41.1M x 128 x 4 B = 19.6 GiB and is
  NEVER materialised. Only the 24 band hashes are written (~7 GB), which is enough
  to recover candidate pairs at either threshold.

* Two LSH configurations are computed from the SAME 128 permutations, so one pass
  supports a sensitivity toggle in the UI:
      loose  b=16, r=8   ->  J ~ (1/16)^(1/8)  = 0.707
      tight  b=8,  r=16  ->  J ~ (1/8)^(1/16)  = 0.878

* Hashing uses multiply-shift universal hashing ((a*x+b) >> 32) rather than the
  textbook Mersenne-prime modulus. Benchmarked on real review text, that is 2.6x
  faster (9,710 vs 3,670 docs/s) for identical collision behaviour at this scale.

* Shingles are built by hashing each WORD once and combining k consecutive word
  hashes with a rolling polynomial, instead of materialising k-word strings.

* Documents under MIN_WORDS_FOR_NEARDUP words are skipped entirely. Short text
  collides by coincidence; "Great product!" is not evidence of anything.

Verified behaviour on held-out strings: identical text agrees on 128/128
permutations, a one-token edit on 109/128, unrelated text on 0/128.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xxhash

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

BANDS_DIR = common.DATA / "minhash"
N_PERMS = common.MINHASH_PERMS
K = common.SHINGLE_K
MIN_WORDS = common.MIN_WORDS_FOR_NEARDUP
SEED = 20240919

# (name, n_bands, n_rows) -- n_bands * n_rows must equal N_PERMS
BAND_SPECS = [("loose", *common.LSH_CONFIGS["loose"]), ("tight", *common.LSH_CONFIGS["tight"])]
BAND_COLUMNS = [f"{name}_{i:02d}" for name, nb, _ in BAND_SPECS for i in range(nb)]

_POLY = np.uint64(1099511628211)
_SHIFT = np.uint64(32)


def _permutations() -> tuple[np.ndarray, np.ndarray]:
    """Fixed multiply-shift coefficients. Seeded so the build is reproducible."""
    rng = np.random.default_rng(SEED)
    a = rng.integers(1, 1 << 62, size=N_PERMS, dtype=np.uint64) | np.uint64(1)
    b = rng.integers(0, 1 << 62, size=N_PERMS, dtype=np.uint64)
    return a, b


A, B = _permutations()
PW_SHINGLE = _POLY ** np.arange(K, dtype=np.uint64)
PW_BAND = {rows: _POLY ** np.arange(rows, dtype=np.uint64) for _, _, rows in BAND_SPECS}


def signature(text: str) -> np.ndarray:
    """128 MinHash values for one document, as uint64 in [0, 2**32)."""
    words = text.lower().split()
    word_hashes = np.fromiter(map(xxhash.xxh64_intdigest, words),
                              dtype=np.uint64, count=len(words))
    if len(word_hashes) < K:
        shingles = word_hashes[:1]
    else:
        shingles = (np.lib.stride_tricks.sliding_window_view(word_hashes, K)
                    * PW_SHINGLE).sum(axis=1)
    return ((A[None, :] * shingles[:, None] + B[None, :]) >> _SHIFT).min(axis=0)


def band_hashes(signatures: np.ndarray) -> list[np.ndarray]:
    """Fold a (n, 128) signature matrix into the 24 band-hash columns."""
    out = []
    for _, n_bands, n_rows in BAND_SPECS:
        folded = signatures.reshape(len(signatures), n_bands, n_rows)
        combined = (folded * PW_BAND[n_rows]).sum(axis=2)
        out.extend(combined[:, i] for i in range(n_bands))
    return out


SCHEMA = pa.schema([("review_sk", pa.int32())] + [(c, pa.uint64()) for c in BAND_COLUMNS])


def _worker(job) -> tuple[int, int, int, float]:
    """Hash one worker's row groups, writing each group's bands out immediately.

    Streaming the write is the whole point: accumulating signatures across row
    groups would rebuild the 19.6 GiB signature matrix in 8 pieces and exhaust
    RAM (measured: workers reached 1.3 GB each and still climbing, with free
    memory down to 772 MB, before this was fixed). Peak per worker is now one
    row group -- roughly 126 MB of signatures plus 66 MB of text.
    """
    worker_id, row_groups, raw_path, out_path = job
    reader = pq.ParquetFile(raw_path)
    started = time.time()
    writer, seen, kept = None, 0, 0

    try:
        for row_group, offset in row_groups:
            table = reader.read_row_group(row_group, columns=["reviewText", "n_words"])
            n_words = table.column("n_words").to_numpy(zero_copy_only=False)
            selected = np.nonzero(n_words >= MIN_WORDS)[0]
            seen += len(n_words)
            if not len(selected):
                continue

            texts = table.column("reviewText").to_pylist()
            sigs = np.empty((len(selected), N_PERMS), dtype=np.uint64)
            for row, local in enumerate(selected):
                sigs[row] = signature(texts[local])

            arrays = ([pa.array((offset + selected).astype(np.int32))]
                      + [pa.array(col) for col in band_hashes(sigs)])
            if writer is None:
                writer = pq.ParquetWriter(out_path, SCHEMA, compression="zstd",
                                          compression_level=3)
            writer.write_table(pa.Table.from_arrays(arrays, schema=SCHEMA))
            kept += len(selected)
            del sigs, arrays, texts, table
    finally:
        if writer is not None:
            writer.close()

    return worker_id, seen, kept, time.time() - started


def main() -> None:
    common.guard_disk(min_d_gb=40.0)
    BANDS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in BANDS_DIR.glob("part-*.parquet"):
        stale.unlink()

    raw_path = str(common.RAW_PARQUET)
    reader = pq.ParquetFile(raw_path)
    n_groups = reader.metadata.num_row_groups
    offsets, running = [], 0
    for i in range(n_groups):
        offsets.append((i, running))
        running += reader.metadata.row_group(i).num_rows
    common.expect(running, common.EXPECTED_ROWS, "row-group offsets cover all rows")

    n_workers = min(8, max(1, mp.cpu_count() - 4))
    # Round-robin so every worker gets a mix of early (short, older reviews) and
    # late row groups -- contiguous blocks would leave workers badly unbalanced.
    jobs = [(w, offsets[w::n_workers], raw_path,
             str(BANDS_DIR / f"part-{w:03d}.parquet")) for w in range(n_workers)]

    print(f"{n_groups} row groups, {running:,} rows, {n_workers} workers, "
          f"{N_PERMS} permutations, k={K} word shingles, min {MIN_WORDS} words")
    print(f"band columns: {len(BAND_COLUMNS)} "
          f"({', '.join(f'{n}={b}x{r}' for n, b, r in BAND_SPECS)})")

    with common.stage("06_minhash: signatures -> LSH band hashes"):
        with mp.Pool(n_workers) as pool:
            total_seen = total_kept = 0
            for worker_id, seen, kept, elapsed in pool.imap_unordered(_worker, jobs):
                total_seen += seen
                total_kept += kept
                print(f"  worker {worker_id}: {kept:,}/{seen:,} docs in {elapsed:.0f}s "
                      f"({kept / max(elapsed, 1e-9):,.0f} docs/s)", flush=True)

    common.expect(total_seen, common.EXPECTED_ROWS, "documents examined")
    skipped = total_seen - total_kept
    print(f"\n  hashed   {total_kept:,} documents ({100 * total_kept / total_seen:.2f}%)")
    print(f"  skipped  {skipped:,} documents under {MIN_WORDS} words "
          f"({100 * skipped / total_seen:.2f}%) -- excluded by design, not truncation")

    shards = sorted(BANDS_DIR.glob("part-*.parquet"))
    size_gb = sum(common.mb(p) for p in shards) / 1024
    print(f"  wrote    {len(shards)} shards, {size_gb:.2f} GiB total")

    con = common.connect()
    written = con.execute(
        f"SELECT count(*) FROM '{(BANDS_DIR / 'part-*.parquet').as_posix()}'").fetchone()[0]
    common.expect(written, total_kept, "band-hash rows written")
    con.close()
    print("\nStage 6 complete.")


if __name__ == "__main__":
    main()
