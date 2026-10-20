"""Shared configuration, DuckDB connection factory and timing harness.

Every pipeline script and the API import from here so the DuckDB memory/temp
settings are applied identically everywhere. The temp directory MUST live on D:
-- C: has ~16 GB free with a 10.75 GB pagefile on it, and letting DuckDB spill
there will wedge the machine.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

SOURCE_GZ = ROOT / "kcore_5.json.gz"
RAW_PARQUET = DATA / "raw" / "reviews.parquet"

# ---------------------------------------------------------------- namespacing
# Stages 4, 8 and 9 can be re-run over a DIFFERENT fact table, writing to a
# parallel set of artifacts, by setting two environment variables:
#
#   BDA_NAMESPACE   suffix appended to every derived filename (e.g. "_inj")
#   BDA_FACT        path to the fact table to read instead of the real one
#   BDA_SYNTH_TEXT  optional extra text parquet UNIONed onto the raw reviews
#
# This is what makes the Stage 10 synthetic-injection study possible without
# duplicating the feature SQL, and it is the same mechanism the scaling harness
# uses to re-run the pipeline at 1M / 5M / 10M / 41M rows.
NAMESPACE = os.environ.get("BDA_NAMESPACE", "")
SYNTH_TEXT = os.environ.get("BDA_SYNTH_TEXT") or None


def ns(path: Path) -> Path:
    """Insert the active namespace before the file extension."""
    return path if not NAMESPACE else path.with_name(f"{path.stem}{NAMESPACE}{path.suffix}")


FACT_PARQUET = Path(os.environ["BDA_FACT"]) if os.environ.get("BDA_FACT")     else DATA / "fact" / "fact_reviews.parquet"
DIM_REVIEWER = ns(DATA / "dim" / "dim_reviewer.parquet")
DIM_PRODUCT = DATA / "dim" / "dim_product.parquet"


def raw_sql() -> str:
    """SQL for the wide review text, with any synthetic rows appended.

    Copying the 9.7 GB raw parquet for an injection run would be absurd, so the
    synthetic text is kept in its own small file and UNIONed in here instead.
    """
    columns = ("file_row_number::BIGINT AS review_sk, reviewerID, asin, reviewText, "
               "summary, n_chars, n_words, text_hash, norm_text_hash")
    base = (f"SELECT {columns} FROM "
            f"read_parquet('{RAW_PARQUET.as_posix()}', file_row_number=true)")
    if SYNTH_TEXT:
        base += (f" UNION ALL BY NAME SELECT review_sk, reviewerID, asin, reviewText, "
                 f"summary, n_chars, n_words, text_hash, norm_text_hash "
                 f"FROM '{Path(SYNTH_TEXT).as_posix()}'")
    return base

# Measured ground truth from three full passes over the source file during planning.
# These are assertions, not estimates -- any deviation means the build is wrong.
EXPECTED_ROWS = 41_135_700
EXPECTED_REVIEWERS = 3_035_045
EXPECTED_PRODUCTS = 1_569_973
EXPECTED_RATING_COUNTS = {1: 2_504_117, 2: 2_066_950, 3: 3_833_977, 4: 8_374_593, 5: 24_356_063}
EXPECTED_MIN_DAY = 1996 - 1  # sanity only; real check is on the unix range
UNIX_MIN = 832_550_400   # 1996-05-20
UNIX_MAX = 1_406_073_600  # 2014-07-23

# Graph containment caps, chosen from the measured pair-explosion table:
#   uncapped            6,568,246,727 pairs  (infeasible)
#   K<=100, M>=20         101,963,753 pairs  (feasible)     <- chosen
#   K<=50,  M>=20          45,747,854 pairs  (comfortable)
PRODUCT_DEGREE_CAP = 100      # K: skip products with more than this many reviewers

# M: minimum reviews for a reviewer to enter the co-review graph.
#
# This was 20, and the synthetic-injection study (stages 10-11) measured what that
# cost: of 2,400 planted accounts holding fewer than 20 reviews, 0 were eligible
# for the graph, so 0 could ever be detected as ring members -- while 1,015-1,200
# of the 1,200 planted accounts that DID clear the floor were correctly placed in
# a ring. The detector was not failing on small accounts; it was refusing to look
# at them, which is exactly the account shape a real campaign would use.
#
# The floor existed to contain the pair explosion. Measured cost of removing it:
# 24.7M eligible reviews -> 11,181,701 pairs sharing >= 2 products (up from
# 7,418,333), in 63s instead of 1s. A one-time cost in a stage that already runs
# for minutes, in exchange for a detector that can see the whole population.
REVIEWER_MIN_REVIEWS = 5      # i.e. no floor beyond the corpus's own 5-core
MIN_SHARED_PRODUCTS = 2       # an edge needs at least this much co-review overlap

# MinHash / LSH
MINHASH_PERMS = 128
SHINGLE_K = 5                 # words per shingle
MIN_WORDS_FOR_NEARDUP = 20    # skip short documents entirely
LSH_CONFIGS = {"loose": (16, 8), "tight": (8, 16)}  # (bands, rows) -> J ~= 0.707 / 0.878
LSH_BUCKET_CAP = 1_000        # cap emitted bucket size; every truncation is logged

def bands_sql() -> str:
    """SQL for the LSH band hashes, with any synthetic shard appended."""
    base = f"SELECT * FROM '{(DATA / 'minhash' / 'part-*.parquet').as_posix()}'"
    synth = os.environ.get("BDA_SYNTH_BANDS")
    if synth:
        base += f" UNION ALL BY NAME SELECT * FROM '{Path(synth).as_posix()}'"
    return base


DUCKDB_SETTINGS = {
    "temp_directory": str(DATA / "tmp").replace("\\", "/"),
    "max_temp_directory_size": "80GiB",
    "memory_limit": "10GB",
    "threads": "10",
    "preserve_insertion_order": "false",
    "enable_progress_bar": "false",
}


def connect(read_only_db: str | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with the mandated settings applied."""
    con = duckdb.connect(read_only_db) if read_only_db else duckdb.connect()
    for key, value in DUCKDB_SETTINGS.items():
        con.execute(f"SET {key} = '{value}'")
    return con


def free_gb(drive: str) -> float:
    return shutil.disk_usage(drive).free / 1024 ** 3


def guard_disk(min_c_gb: float = 8.0, min_d_gb: float = 30.0) -> None:
    """Refuse to start a long job that could fill C: and wedge the machine."""
    c, d = free_gb("C:\\"), free_gb("D:\\")
    if c < min_c_gb:
        raise SystemExit(f"ABORT: C: has only {c:.1f} GB free (need {min_c_gb} GB). "
                         f"Free space before running a long job.")
    if d < min_d_gb:
        raise SystemExit(f"ABORT: D: has only {d:.1f} GB free (need {min_d_gb} GB).")
    print(f"[disk] C: {c:.1f} GB free | D: {d:.1f} GB free")


def peak_rss_mb() -> float:
    """Peak working set of this process, in MB (Windows PSAPI)."""
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                               wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                          ctypes.byref(counters), counters.cb):
            return float("nan")
        return counters.PeakWorkingSetSize / 1024 ** 2
    except Exception:
        return float("nan")


PERF_LOG = DOCS / "perf.jsonl"


@contextmanager
def stage(name: str):
    """Time a stage, print progress, and append one line to docs/perf.jsonl."""
    print(f"\n{'=' * 70}\n[stage] {name}\n{'=' * 70}", flush=True)
    t0 = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - t0
        rss = peak_rss_mb()
        print(f"\n[stage] {name} finished in {elapsed:.1f}s (peak RSS {rss:.0f} MB)", flush=True)
        PERF_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PERF_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"stage": name, "seconds": round(elapsed, 2),
                                     "peak_rss_mb": round(rss, 1)}) + "\n")


def expect(actual, wanted, label: str) -> None:
    """Hard assertion against the measured corpus totals.

    Skipped when a namespace is active: on an injected or subsampled run the
    real corpus counts no longer apply, and asserting them would fail the build
    for the wrong reason.
    """
    if NAMESPACE:
        print(f"  -- {label}: {actual:,} (assertion skipped, namespace {NAMESPACE!r})")
        return
    if actual != wanted:
        raise SystemExit(f"FAIL {label}: got {actual:,} expected {wanted:,}")
    print(f"  OK {label}: {actual:,}")


def mb(path: Path) -> float:
    return path.stat().st_size / 1024 ** 2 if path.exists() else 0.0
