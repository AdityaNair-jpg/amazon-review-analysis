"""Stage 0 -- verify every import, every DuckDB setting and enough free disk.

Fails loudly rather than letting a multi-hour job discover a missing package or
a full C: drive halfway through.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

REQUIRED = ["duckdb", "pyarrow", "numpy", "pandas", "scipy", "sklearn",
            "networkx", "orjson", "xxhash", "tqdm"]
API_ONLY = ["fastapi", "uvicorn", "pytest"]
# Deliberately NOT required -- see plan section 5. torch is broken on this box
# (dist-info present, package directory absent) and no method in this pipeline
# needs it. A CPU wheel is ~2.5 GB against a 16 GB C: drive.
DELIBERATELY_ABSENT = ["torch", "sentence_transformers", "datasketch", "faiss",
                       "igraph", "lightgbm", "xgboost", "mlxtend"]


def check(mods: list[str], *, fatal: bool) -> list[str]:
    missing = []
    for name in mods:
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", "?")
            print(f"  OK   {name:<22} {version}")
        except Exception as exc:
            missing.append(name)
            print(f"  {'MISS' if fatal else 'warn'} {name:<22} {type(exc).__name__}")
    return missing


def main() -> None:
    print(f"Python {sys.version.split()[0]}  ({sys.executable})")

    print("\n[required]")
    missing = check(REQUIRED, fatal=True)

    print("\n[api layer]")
    missing_api = check(API_ONLY, fatal=False)

    print("\n[deliberately absent -- plan section 5, not an error]")
    for name in DELIBERATELY_ABSENT:
        try:
            importlib.import_module(name)
            print(f"  note {name:<22} present (unused)")
        except Exception:
            print(f"  ok   {name:<22} absent as expected")

    print("\n[source file]")
    if not common.SOURCE_GZ.exists():
        raise SystemExit(f"FAIL: {common.SOURCE_GZ} not found")
    size_gib = common.SOURCE_GZ.stat().st_size / 1024 ** 3
    print(f"  OK   {common.SOURCE_GZ.name}  {size_gib:.2f} GiB")

    print("\n[duckdb settings]")
    con = common.connect()
    for key in common.DUCKDB_SETTINGS:
        value = con.execute(f"SELECT current_setting('{key}')").fetchone()[0]
        print(f"  OK   {key:<28} = {value}")
    has_frn = con.execute(
        "SELECT count(*) FROM duckdb_functions() WHERE function_name = 'read_parquet'"
    ).fetchone()[0]
    print(f"  OK   read_parquet available ({has_frn} overloads)")
    con.close()

    print("\n[disk]")
    common.guard_disk()

    if missing:
        raise SystemExit(f"\nFAIL: missing required packages: {', '.join(missing)}")
    if missing_api:
        print(f"\nNOTE: API packages not yet installed: {', '.join(missing_api)}")
        print("      Install before stage 10:  pip install -r requirements.txt")
    print("\nEnvironment OK.")


if __name__ == "__main__":
    main()
