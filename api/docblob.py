"""Constant-time document fetch, backed by pipeline/13c_docblob.py.

Search returns twenty documents per query and has to turn twenty ids into twenty
records. Doing that in DuckDB over Parquet has a floor of roughly 250 ms no matter how
few rows are asked for -- the footer is re-parsed every time -- and stage 13c documents
the measurements behind that. Here the same fetch is a seek and a short read.

    offsets[i] .. offsets[i + 1]   the bytes of record i, in docblob.bin

The offset index is memory-mapped rather than read: it is 329 MB on disk and the pages
actually touched are the handful holding the ids in hand, so resident cost is a few KB.

Degrades the way everything else here does -- if the blob has not been built,
`available()` is False and search falls back to the Parquet store.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import orjson

ROOT = Path(__file__).resolve().parent.parent
BLOB = ROOT / "data" / "ir" / "docblob.bin"
INDEX = ROOT / "data" / "ir" / "docblob.idx"

# Must match FIELDS in pipeline/13c_docblob.py. Records are stored as JSON arrays, so
# this is the only thing that says what the positions mean.
FIELDS = ("reviewer_sk", "product_sk", "day", "reviewerID", "asin", "reviewerName",
          "rating", "helpful_yes", "helpful_total", "n_words", "summary", "reviewText")

_offsets: np.memmap | None = None
_handle = None
_lock = threading.Lock()


def available() -> bool:
    return BLOB.exists() and INDEX.exists()


def _open():
    """Map the index and open the blob once, shared across requests.

    FastAPI serves from a threadpool, so the file handle is guarded: seek-then-read is
    two calls and two threads interleaving them would read each other's bytes.
    """
    global _offsets, _handle
    if _handle is None:
        with _lock:
            if _handle is None:
                _offsets = np.memmap(INDEX, dtype=np.int64, mode="r")
                _handle = open(BLOB, "rb")
    return _offsets, _handle


def fetch(doc_ids: list[int]) -> dict[int, dict]:
    """Return {doc_id: record} for the ids that exist, skipping any that do not."""
    if not doc_ids or not available():
        return {}
    offsets, handle = _open()
    limit = len(offsets) - 1
    out: dict[int, dict] = {}
    # Ascending order turns scattered seeks into a forward pass over the file, which
    # is friendlier to both the drive and the OS readahead.
    with _lock:
        for doc_id in sorted(set(int(d) for d in doc_ids)):
            if doc_id < 0 or doc_id >= limit:
                continue
            start, end = int(offsets[doc_id]), int(offsets[doc_id + 1])
            handle.seek(start)
            raw = handle.read(end - start)
            out[doc_id] = dict(zip(FIELDS, orjson.loads(raw)))
    return out
