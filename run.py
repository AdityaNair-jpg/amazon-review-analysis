"""One command for the whole project.

    python run.py

does only what is needed, in order:

  1. checks the Python packages and Node are present (offers to install what is missing)
  2. builds any pipeline artifact the dashboard needs that does not exist yet
  3. starts the API on 127.0.0.1:8000 and the dashboard on 127.0.0.1:3000
  4. opens the dashboard in your browser, and stops both cleanly on Ctrl+C

Everything built is kept, so after the first time it starts in seconds.

Options
  --status          show what is built, missing or out of date, then exit
  --dev             run the dashboard with hot reload, for editing the UI
  --rebuild STAGE   rebuild a stage and everything downstream of it, e.g. --rebuild 09_score
  --reports         also build the optional reports: validation study, scaling table
  --no-browser      do not open a browser
  --yes             do not ask before long builds or installs

Both servers listen on 127.0.0.1 only, so nothing is reachable from other machines.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
LOGS = ROOT / "logs"
PIDFILE = LOGS / "run.json"
NEXT_BIN = WEB / "node_modules" / "next" / "dist" / "bin" / "next"
HOST = "127.0.0.1"
API_PORT, WEB_PORT = 8000, 3000
API_URL, WEB_URL = f"http://{HOST}:{API_PORT}", f"http://{HOST}:{WEB_PORT}"
IS_WINDOWS = os.name == "nt"


# --------------------------------------------------------------------- stages
@dataclass
class Stage:
    key: str
    script: str
    outputs: list[str]
    needs: list[str] = field(default_factory=list)
    minutes: float = 1.0
    what: str = ""
    report: bool = False

    def paths(self) -> list[Path]:
        return [ROOT / o for o in self.outputs]


# Everything the dashboard reads, in dependency order. `outputs` are the files whose
# existence means the stage has run; `needs` are the stages whose outputs it reads.
STAGES = [
    Stage("01_ingest", "pipeline/01_ingest.py", ["data/raw/reviews.parquet"],
          [], 5, "gzip -> Parquet, the one pass over the 9.9 GB source"),
    Stage("02_fact", "pipeline/02_fact.py",
          ["data/fact/fact_reviews.parquet", "data/dim/dim_reviewer.parquet",
           "data/dim/dim_product.parquet"], ["01_ingest"], 2, "keys, dimensions, fact table"),
    Stage("03_quality", "pipeline/03_quality.py", ["docs/data_quality.md"],
          ["02_fact"], 0.3, "data-quality report"),
    Stage("04_features", "pipeline/04_features.py",
          ["data/features/feat_reviewer.parquet", "data/features/feat_product.parquet",
           "data/features/baseline_daily_volume.parquet"], ["02_fact"], 1,
          "reviewer and product features"),
    Stage("05_duplicates", "pipeline/05_duplicates.py",
          ["data/features/dup_clusters.parquet", "data/features/dup_members.parquet"],
          ["02_fact"], 0.5, "exact duplicate clusters"),
    Stage("06_minhash", "pipeline/06_minhash.py", ["data/minhash/part-000.parquet"],
          ["01_ingest"], 19, "MinHash + LSH signatures"),
    Stage("07_neardup", "pipeline/07_neardup.py",
          ["data/features/neardup_clusters.parquet", "data/features/neardup_members.parquet"],
          ["06_minhash", "02_fact"], 4, "verified near-duplicate clusters"),
    Stage("08_graph", "pipeline/08_graph.py",
          ["data/graph/rings.parquet", "data/graph/ring_members.parquet",
           "data/graph/coreview_edges.parquet"], ["02_fact"], 14,
          "co-review graph and rings"),
    Stage("09_score", "pipeline/09_score.py",
          ["data/scores/reviewer_scores.parquet", "data/scores/score_meta.json"],
          ["04_features", "05_duplicates", "07_neardup", "08_graph"], 0.5,
          "suspicion scores"),
    # The search stages (13_index, 13b_docstore, 13c_docblob, 16_search_exposure) and
    # their ~67 GB of data were removed to keep only the visualizations. Their scripts
    # are still in pipeline/ and can be run by hand to bring search back.
    #
    # data/story/network.json (the Network page) is kept as a finished artifact rather
    # than a stage here: rebuilding it with pipeline/15_story_network.py needs the
    # search document store for its disclosure check.
    # Optional write-ups: nothing on screen depends on them.
    Stage("run_injection", "pipeline/run_injection.py", ["docs/validation.md"],
          ["09_score"], 25, "validation study with planted campaigns", report=True),
    Stage("12_scaling", "pipeline/12_scaling.py", ["docs/scaling.md"],
          ["09_score"], 30, "1M / 5M / 10M / 41M scaling table", report=True),
]
BY_KEY = {s.key: s for s in STAGES}
SLACK_S = 2.0   # filesystem timestamps are not exact; ignore sub-second "newer than"


def state(stage: Stage) -> str:
    """'missing', 'stale' (an input is newer than this stage's output), or 'ok'."""
    paths = stage.paths()
    if not all(p.exists() for p in paths):
        return "missing"
    oldest = min(p.stat().st_mtime for p in paths)
    for need in stage.needs:
        upstream = [p for p in BY_KEY[need].paths() if p.exists()]
        if upstream and max(p.stat().st_mtime for p in upstream) > oldest + SLACK_S:
            return "stale"
    return "ok"


def downstream(keys: set[str]) -> set[str]:
    """Every stage that reads, directly or not, from any stage in `keys`."""
    out = set(keys)
    changed = True
    while changed:
        changed = False
        for s in STAGES:
            if s.key not in out and any(n in out for n in s.needs):
                out.add(s.key)
                changed = True
    return out


def not_kept(stages: list[Stage]) -> set[str]:
    """Missing intermediates that nothing needs, because everything they feed is built.

    Some stages exist only to produce input for a later one -- 06_minhash feeds
    07_neardup and nothing else. Once their output has been deleted to save disk, they
    show up as missing, and rebuilding them would also rebuild everything downstream,
    overwriting finished results for no gain. So a missing stage counts as needed only
    if something that reads it also has to be built.
    """
    missing = {s.key for s in stages if state(s) == "missing"}
    skip: set[str] = set()
    for s in reversed(stages):                 # consumers are decided before producers
        if s.key not in missing:
            continue
        consumers = [c for c in stages if s.key in c.needs]
        if consumers and all(c.key not in missing or c.key in skip for c in consumers):
            skip.add(s.key)
    return skip


def missing_inputs(keys: set[str]) -> set[str]:
    """Missing stages these read, followed only through other missing stages.

    A built input stops the walk: rebuilding 09_score reads 07_neardup's output, which
    exists, so 06_minhash behind it does not need to come back.
    """
    out, frontier = set(), set(keys)
    while frontier:
        nxt = {n for k in frontier for n in BY_KEY[k].needs
               if state(BY_KEY[n]) == "missing"} - out
        out |= nxt
        frontier = nxt
    return out


def plan_build(include_reports: bool, rebuild: str | None) -> tuple[list[Stage], list[Stage]]:
    """What to run now, and what is out of date but will only be warned about.

    Missing outputs are built -- the dashboard cannot work without them -- and so is
    everything downstream of anything being built, so nothing is left reading a
    half-updated set of artifacts. Deleted intermediates nothing needs are left alone
    (see `not_kept`), unless a stage being rebuilt has to read them. A stage that merely
    *looks* stale by timestamp is reported, not rebuilt: that can mean hours of work,
    and it should be a choice.
    """
    wanted = [s for s in STAGES if include_reports or not s.report]
    keys = {s.key for s in wanted}
    skip = not_kept(wanted)
    run = {s.key for s in wanted if state(s) == "missing"} - skip
    if rebuild:
        if rebuild not in BY_KEY:
            raise SystemExit(f"unknown stage {rebuild!r}; one of: {', '.join(BY_KEY)}")
        run |= {rebuild}
    run = {k for k in downstream(run) if k in keys}
    # A stage being rebuilt may need a deleted intermediate after all.
    run |= {k for k in missing_inputs(run) if k in keys}
    todo = [s for s in wanted if s.key in run]
    stale = [s for s in wanted if s.key not in run and state(s) == "stale"]
    return todo, stale


# ------------------------------------------------------------------- printing
def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(msg: str) -> None:
    say(f"\n== {msg}")


def human_minutes(m: float) -> str:
    return f"{m:.0f} min" if m < 90 else f"{m / 60:.1f} h"


def size_of(paths: list[Path]) -> str:
    total = sum(p.stat().st_size for p in paths if p.exists())
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024 or unit == "GB":
            return f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
        total /= 1024
    return ""


def ask(question: str, assume_yes: bool) -> bool:
    if assume_yes or not sys.stdin.isatty():
        return True
    reply = input(f"{question} [Y/n] ").strip().lower()
    return reply in ("", "y", "yes")


def tail(path: Path, lines: int = 25) -> str:
    if not path.exists():
        return "(no log written)"
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join("    " + line for line in text[-lines:])


# ---------------------------------------------------------------- environment
PACKAGES = {  # import name -> pip name
    "duckdb": "duckdb", "pyarrow": "pyarrow", "numpy": "numpy", "pandas": "pandas",
    "scipy": "scipy", "sklearn": "scikit-learn", "networkx": "networkx",
    "orjson": "orjson", "xxhash": "xxhash", "fastapi": "fastapi", "uvicorn": "uvicorn",
    "nltk": "nltk", "onnxruntime": "onnxruntime", "tokenizers": "tokenizers",
}


def check_python(assume_yes: bool) -> None:
    if sys.version_info < (3, 10):
        raise SystemExit(f"Python 3.10+ is needed; this is {sys.version.split()[0]}.")
    missing = [pip for mod, pip in PACKAGES.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        say("  [ok] Python packages")
        return
    say(f"  [!!] missing Python packages: {', '.join(missing)}")
    if not ask("  Install them from requirements.txt with pip?", assume_yes):
        raise SystemExit("Install them with:  python -m pip install -r requirements.txt")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                    str(ROOT / "requirements.txt")], check=True)


def check_node(assume_yes: bool) -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is needed for the dashboard: https://nodejs.org (LTS).")
    if not NEXT_BIN.exists():
        say("  [..] dashboard dependencies are not installed yet")
        pnpm = shutil.which("pnpm")
        if not pnpm:
            raise SystemExit("pnpm is needed once, to install them. Run:  corepack enable\n"
                             "(or: npm install -g pnpm), then run this again.")
        if not ask("  Install them now with pnpm (one-time, a few minutes)?", assume_yes):
            raise SystemExit("Install them with:  cd web && pnpm install")
        subprocess.run([pnpm, "install"], cwd=WEB, check=True)
    say("  [ok] Node and dashboard dependencies")
    return node


# ---------------------------------------------------------------------- build
def run_stages(todo: list[Stage], assume_yes: bool) -> None:
    if not todo:
        say("  [ok] every artifact the dashboard needs is already built")
        return
    if BY_KEY["01_ingest"] in todo and not (ROOT / "kcore_5.json.gz").exists():
        raise SystemExit("The source dataset is missing: put kcore_5.json.gz in the project "
                         "folder (the 2014 McAuley/UCSD Amazon 5-core file).")
    total = sum(s.minutes for s in todo)
    say(f"  {len(todo)} stage(s) to build, roughly {human_minutes(total)} on the reference laptop:")
    for s in todo:
        say(f"    {s.key:<20} ~{human_minutes(s.minutes):>7}   {s.what}")
    if total >= 10 and not ask("  Start building now?", assume_yes):
        raise SystemExit("Nothing built. Run again when you are ready.")

    # Stage 0 checks imports, DuckDB settings and free disk before hours of work.
    subprocess.run([sys.executable, "-u", str(ROOT / "pipeline" / "00_verify_env.py")],
                   cwd=ROOT, check=True)
    started = time.time()
    for i, s in enumerate(todo, 1):
        say(f"\n---- [{i}/{len(todo)}] {s.key}: {s.what} (expect ~{human_minutes(s.minutes)})")
        t0 = time.time()
        result = subprocess.run([sys.executable, "-u", str(ROOT / s.script)], cwd=ROOT)
        if result.returncode != 0:
            raise SystemExit(f"\nBuild stopped: {s.key} failed (exit {result.returncode}) "
                             f"after {time.time() - t0:.0f}s. Its output is above.\n"
                             f"Fix it, then run `python run.py` again -- finished stages "
                             f"are kept and will not re-run.")
        say(f"---- {s.key} done in {(time.time() - t0) / 60:.1f} min")
    say(f"\n  [ok] build finished in {(time.time() - started) / 60:.1f} min")


def web_needs_build() -> bool:
    """True if there is no production build, or any source is newer than it."""
    stamp = WEB / ".next" / "BUILD_ID"
    if not stamp.exists():
        return True
    built = stamp.stat().st_mtime
    sources = [WEB / "next.config.ts", WEB / "package.json", WEB / "tsconfig.json"]
    for folder in ("app", "components", "lib", "public"):
        if (WEB / folder).exists():
            sources += [p for p in (WEB / folder).rglob("*") if p.is_file()]
    return any(p.exists() and p.stat().st_mtime > built for p in sources)


def build_web(node: str) -> None:
    if not web_needs_build():
        say("  [ok] dashboard build is up to date")
        return
    say("  [..] compiling the dashboard (only after UI changes; about a minute)...")
    log = LOGS / "web-build.log"
    with open(log, "w", encoding="utf-8", errors="replace") as out:
        result = subprocess.run([node, str(NEXT_BIN), "build"], cwd=WEB,
                                stdout=out, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise SystemExit(f"The dashboard failed to compile. Last lines of {log}:\n{tail(log)}")
    say("  [ok] dashboard compiled")


# ------------------------------------------------------------------ processes
def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def http_ok(url: str, timeout: float = 3.0, marker: str | None = None) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read(200_000).decode("utf-8", "replace")
            return r.status == 200 and (marker is None or marker in body)
    except Exception:
        return False


def process_name(pid: int) -> str | None:
    """Image name of a live process, or None if it is gone."""
    try:
        if IS_WINDOWS:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True).stdout.strip()
            return out.split('","')[0].strip('"').lower() if out.startswith('"') else None
        os.kill(pid, 0)
        return subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True,
                              text=True).stdout.strip().lower() or None
    except Exception:
        return None


def pid_on_port(port: int) -> int | None:
    try:
        if IS_WINDOWS:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                 text=True).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
                    return int(parts[4])
        else:
            out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                                 capture_output=True, text=True).stdout.split()
            return int(out[0]) if out else None
    except Exception:
        pass
    return None


def kill_tree(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        pass


def clear_leftovers() -> None:
    """Stop servers a previous run started and never shut down (closed terminal, crash).

    Only PIDs this script recorded itself, and only if they are still a python or node
    process -- a recycled PID belonging to something else is left alone.
    """
    if not PIDFILE.exists():
        return
    try:
        recorded = json.loads(PIDFILE.read_text(encoding="utf-8"))
    except Exception:
        recorded = {}
    for name, pid in recorded.items():
        image = process_name(int(pid))
        if image and ("python" in image or "node" in image):
            kill_tree(int(pid))
            say(f"  [ok] stopped the {name} server a previous run left behind (pid {pid})")
    PIDFILE.unlink(missing_ok=True)
    time.sleep(1.0)


def blocked(port: int, what: str) -> SystemExit:
    pid = pid_on_port(port)
    who = f"process {pid} ({process_name(pid) or 'unknown'})" if pid else "another program"
    fix = (f"taskkill /PID {pid} /F" if IS_WINDOWS else f"kill {pid}") if pid else ""
    return SystemExit(f"Port {port} is taken by {who}, which is not answering like the "
                      f"{what}.\nFree it and run again" + (f":  {fix}" if fix else "."))


def spawn(cmd: list[str], cwd: Path, log: Path) -> subprocess.Popen:
    out = open(log, "w", encoding="utf-8", errors="replace")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    extra = {} if IS_WINDOWS else {"start_new_session": True}
    return subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env, **extra)


def wait_until(url: str, proc: subprocess.Popen | None, log: Path, what: str,
               timeout: float, marker: str | None = None) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if http_ok(url, marker=marker):
            return
        if proc is not None and proc.poll() is not None:
            raise SystemExit(f"The {what} stopped while starting. Last lines of {log}:\n"
                             f"{tail(log)}")
        time.sleep(0.7)
    raise SystemExit(f"The {what} did not answer within {timeout:.0f}s. "
                     f"Last lines of {log}:\n{tail(log)}")


# ------------------------------------------------------------------- commands
def status() -> None:
    say(f"{'stage':<20} {'state':<9} {'size':>9}   what")
    for s in STAGES:
        st = state(s)
        label = {"ok": "built", "missing": "MISSING", "stale": "STALE"}[st]
        if st == "missing" and s.key in not_kept([x for x in STAGES if not x.report]):
            label = "not kept"
        tag = "  (optional report)" if s.report else ""
        say(f"{s.key:<20} {label:<9} {size_of(s.paths()) if st != 'missing' else '':>9}   "
            f"{s.what}{tag}")
    network = ROOT / "data" / "story" / "network.json"
    say(f"\nnetwork page data        {'present' if network.exists() else 'MISSING (the Network page will be empty)'}")
    say(f"dashboard build          {'needs compiling' if web_needs_build() else 'up to date'}")
    say(f"API       {API_URL:<24} {'running' if http_ok(API_URL + '/health') else 'not running'}")
    say(f"dashboard {WEB_URL:<24} {'running' if port_open(WEB_PORT) else 'not running'}")
    todo, stale = plan_build(False, None)
    if stale:
        say("\nOut of date (an input changed after these were built):")
        for s in stale:
            say(f"  {s.key:<20} python run.py --rebuild {s.key}")


def serve(node: str, dev: bool, open_browser: bool) -> None:
    LOGS.mkdir(exist_ok=True)
    clear_leftovers()
    managed: dict[str, subprocess.Popen] = {}
    api_log, web_log = LOGS / "api.log", LOGS / "web.log"

    try:
        step("Starting the API")
        if port_open(API_PORT):
            if not http_ok(API_URL + "/health"):
                raise blocked(API_PORT, "API")
            say(f"  [ok] an API is already running at {API_URL}; using it")
        else:
            managed["api"] = spawn([sys.executable, "-m", "uvicorn", "api.main:app",
                                    "--host", HOST, "--port", str(API_PORT)], ROOT, api_log)
            wait_until(API_URL + "/health", managed["api"], api_log, "API", 90)
            say(f"  [ok] API ready at {API_URL}")

        step("Starting the dashboard")
        marker = "reviewing together"
        if port_open(WEB_PORT):
            if not http_ok(WEB_URL + "/search", timeout=10, marker=marker):
                raise blocked(WEB_PORT, "dashboard")
            say(f"  [ok] a dashboard is already running at {WEB_URL}; using it")
        else:
            if not dev:
                build_web(node)
            mode = "dev" if dev else "start"
            managed["web"] = spawn([node, str(NEXT_BIN), mode, "-p", str(WEB_PORT), "-H", HOST],
                                   WEB, web_log)
            wait_until(WEB_URL + "/search", managed["web"], web_log, "dashboard",
                       240 if dev else 90, marker)
            say(f"  [ok] dashboard ready at {WEB_URL}" + ("  (hot reload on)" if dev else ""))

        PIDFILE.write_text(json.dumps({k: p.pid for k, p in managed.items()}), encoding="utf-8")
        if open_browser:
            webbrowser.open(WEB_URL)
        say(f"""
  Dashboard   {WEB_URL}
  API docs    {API_URL}/docs
  Logs        {api_log.relative_to(ROOT)}, {web_log.relative_to(ROOT)}

  Press Ctrl+C to stop.""")
        if not managed:
            return
        while True:
            for name, proc in managed.items():
                if proc.poll() is not None:
                    log = api_log if name == "api" else web_log
                    raise SystemExit(f"\nThe {name} server stopped unexpectedly "
                                     f"(exit {proc.returncode}). Last lines of {log}:\n{tail(log)}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        say("\nStopping...")
    finally:
        for proc in managed.values():
            if proc.poll() is None:
                kill_tree(proc.pid)
        if managed:
            PIDFILE.unlink(missing_ok=True)
            say("  [ok] stopped")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build what is missing, then run the API and dashboard.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("Options")[1])
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--rebuild", metavar="STAGE")
    parser.add_argument("--reports", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--yes", "-y", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)

    if args.status:
        status()
        return

    step("Checking the environment")
    check_python(args.yes)
    node = check_node(args.yes)

    step("Checking the pipeline")
    todo, stale = plan_build(args.reports, args.rebuild)
    for s in stale:
        say(f"  [!!] {s.key} is older than its inputs; rebuild with: "
            f"python run.py --rebuild {s.key}")
    run_stages(todo, args.yes)

    serve(node, args.dev, not args.no_browser)


if __name__ == "__main__":
    main()
