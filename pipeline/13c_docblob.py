"""Stage 13c -- a flat document store, because Parquet is not a point-lookup format.

Search fetches about twenty documents by id per query. Stage 13b made that as fast as
Parquet allows and it was still the single largest cost in a search, so this measures
where the floor actually is and then goes under it.

What was measured, all on data/ir/docstore.parquet (9.01 GiB, 41.1M rows):

    fetching 1 row by review_sk                252 ms
    fetching 20 contiguous rows                214 ms
    fetching 20 scattered rows                 388-620 ms
    SELECT count(*) (footer metadata only)     106 ms

One row costing 252 ms is the whole story: almost none of it is reading data. Every
query re-parses the Parquet footer, whose cost grows with row_groups x columns, and
the row-group count is also what decides how much surplus data a lookup decompresses.
Tuning that trade helped -- 8,192-row groups gave 855 ms, 20,000-row groups 529 ms --
but it cannot remove a fixed cost, only balance it. Splitting text and metadata into
separate files so each could take its own row-group size made things worse (769 ms),
and `enable_object_cache` changed nothing.

So: a flat file and an offset index, which is what a point lookup wants.

    docblob.bin    one JSON record per review, concatenated, no separators
    docblob.idx    int64 offsets, N+1 of them, memory-mapped by the API

A lookup is offsets[i], offsets[i+1], one seek, one short read, one parse -- constant
time, no metadata, no decompression, nothing proportional to corpus size. Records are
stored as JSON arrays rather than objects because the field names are the same 12
strings 41 million times over; the API holds the order in FIELDS.

The file is uncompressed. That costs about 4 GB over the Parquet copy and buys a lookup
with no decompression step at all, which on a 107 GB disk is an easy trade.

Run:  python pipeline/13c_docblob.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import orjson
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

DOCSTORE = common.DATA / "ir" / "docstore.parquet"
BLOB = common.DATA / "ir" / "docblob.bin"
INDEX = common.DATA / "ir" / "docblob.idx"

# The record layout. The API imports this so the two cannot drift apart.
FIELDS = ("reviewer_sk", "product_sk", "day", "reviewerID", "asin", "reviewerName",
          "rating", "helpful_yes", "helpful_total", "n_words", "summary", "reviewText")

BATCH = 65_536
WRITE_BUFFER = 64 << 20


def main() -> None:
    common.guard_disk(min_d_gb=25.0)
    if not DOCSTORE.exists():
        raise SystemExit("run pipeline/13b_docstore.py first")

    source = pq.ParquetFile(DOCSTORE)
    n_rows = source.metadata.num_rows
    common.expect(n_rows, common.EXPECTED_ROWS, "source rows")

    offsets = np.empty(n_rows + 1, dtype=np.int64)
    offsets[0] = 0
    position = 0
    written = 0
    started = time.time()

    with common.stage("13c_docblob: write the flat record file"):
        with open(BLOB, "wb", buffering=WRITE_BUFFER) as out:
            for batch in source.iter_batches(batch_size=BATCH, columns=["review_sk", *FIELDS]):
                columns = {name: batch.column(name).to_pylist() for name in FIELDS}
                first = batch.column("review_sk")[0].as_py()
                if first != written:
                    raise SystemExit(
                        f"docstore is not in review_sk order at row {written}: got {first}. "
                        "13c relies on that ordering; rebuild with pipeline/13b_docstore.py.")

                rows = zip(*(columns[name] for name in FIELDS))
                for i, row in enumerate(rows):
                    # orjson serialises a tuple as a JSON array. The field names live in
                    # FIELDS rather than being repeated 41 million times on disk.
                    position += out.write(orjson.dumps(row))
                    offsets[written + i + 1] = position
                written += batch.num_rows

                if written % (BATCH * 64) == 0:
                    rate = written / max(time.time() - started, 1e-9)
                    print(f"  {written:>12,} / {n_rows:,}  "
                          f"({position / 1e9:.2f} GB, {rate:,.0f} rows/s)", flush=True)

    common.expect(written, common.EXPECTED_ROWS, "records written")
    offsets.tofile(INDEX)

    print("\n[verify]")
    print(f"  blob  {common.mb(BLOB) / 1024:.2f} GiB")
    print(f"  index {common.mb(INDEX):.1f} MB  ({len(offsets):,} offsets)")
    common.expect(int(offsets[-1]), BLOB.stat().st_size, "final offset == file size")

    # Read a scattered sample back and check it against the source of truth.
    index = np.memmap(INDEX, dtype=np.int64, mode="r")
    ids = list(range(1_000_000, 41_000_000, 2_000_000))[:20]
    with open(BLOB, "rb") as handle:
        for _ in range(2):
            t0 = time.time()
            fetched = {}
            for doc_id in ids:
                start, end = int(index[doc_id]), int(index[doc_id + 1])
                handle.seek(start)
                fetched[doc_id] = orjson.loads(handle.read(end - start))
            elapsed = (time.time() - t0) * 1000
    print(f"  lookup of {len(ids)} scattered ids: {elapsed:.2f} ms "
          f"-- Parquet needed 388-620 ms for the same thing")

    con = common.connect()
    keys = ",".join(str(i) for i in ids)
    truth = {r[0]: r[1:] for r in con.execute(
        f"SELECT review_sk, {', '.join(FIELDS)} FROM '{DOCSTORE.as_posix()}' "
        f"WHERE review_sk IN ({keys})").fetchall()}
    mismatches = 0
    for doc_id, record in fetched.items():
        expected = truth[doc_id]
        for name, got, want in zip(FIELDS, record, expected):
            if name in ("rating",):
                same = abs((got or 0) - (want or 0)) < 1e-6
            else:
                same = got == want
            if not same:
                mismatches += 1
                print(f"  MISMATCH doc {doc_id} field {name}: {got!r} != {want!r}")
    common.expect(mismatches, 0, "fields disagreeing with the Parquet source")
    con.close()

    print("\nStage 13c complete. The API uses this in preference to the Parquet store.")


if __name__ == "__main__":
    main()
