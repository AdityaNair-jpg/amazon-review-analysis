"""Stage 15 -- the network of suspicious accounts, laid out for drawing, and what it wrote.

The full co-review graph has 1,038,862 accounts and never fragments, so drawing it says
nothing. This draws only the top 1% by suspicion score, joined by the same rule the ring
detector uses: at least three shared products within 30 days.

What comes out, measured on the full corpus:

    30,378 accounts score >= 0.9; 3,529 of them are linked to another one
    17,730 links between them, in 393 separate clusters

and the same trap as the full graph: one cluster holds 70% of the accounts. Stricter
rules do not break it up (a 61-72% share across every rule in `FRAGMENTATION` below),
so it is not a threshold artefact -- it is a real, different kind of structure, and it
is shown as its own view rather than as a hairball swallowing everything else.

The two views:

    packs   ~390 small clusters, ~1,050 accounts -- tight groups, the classic shape
    core    one linked cluster of ~2,479 accounts -- prolific, long-lived reviewers

What distinguishes them is found by searching what they wrote, not from the graph:
the core discloses free or discounted products several times more often than equally
prolific accounts that are not suspicious; the packs almost never do. `disclosure`
below measures that, and `group_docs.parquet` lets the search engine be scoped to
either group so anyone can check it for themselves.

Layouts are computed here, once, so the browser only draws: deterministic positions,
no simulation jank, and nothing that can disagree between server and client render.

Outputs under data/story/:
    network.json        both views: nodes, edges, cluster summaries, headline numbers
    group_docs.parquet  (grp, review_sk) for every review by a core or pack account

Run:  python pipeline/15_story_network.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import networkx as nx
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
import common  # noqa: E402
from api import docblob  # noqa: E402

OUT = common.DATA / "story"
SCORE_CUT = 0.9
SHARED_MIN = 3           # the ring detector's own edge rule
SEED = 20140723          # the last day in the corpus
SAMPLE_PER_ACCOUNT = 60

# Explicit disclosure language only. A bare "free" matched "free shipping" in the first
# attempt at this and flattered every group; this pattern needs the review itself to be
# the thing exchanged. It is a lower bound: undisclosed incentivised reviews exist.
DISCLOSURE = re.compile(
    r"(in exchange for (my|an|a|this) (honest|unbiased|fair|impartial)"
    r"|(free|discount(ed)?|reduced|no charge|no cost)[^.]{0,25}(for|in exchange for) "
    r"(my |an |a )?(honest |unbiased )?(review|evaluation|feedback)"
    r"|(received|given|provided|sent)[^.]{0,30}(for|to) (review|evaluation|testing) purposes"
    r"|sample[^.]{0,20}(for|in exchange for) (my |an )?(honest )?review)", re.I)

# Amazon's own early-reviewer programme, which would also put the same products in many
# hands at once. Measured so the obvious alternative explanation is answered, not assumed.
VINE = re.compile(r"\bvine\b", re.I)

FRAGMENTATION = [(0.9, 3, "shared_30d"), (0.9, 5, "shared_30d"), (0.9, 8, "shared_30d"),
                 (0.9, 3, "shared_7d"), (0.9, 5, "shared_7d"), (0.95, 3, "shared_30d")]


def subgraph(con, score_cut: float, shared_min: int, column: str = "shared_30d"):
    e = con.execute(f"""
        WITH s AS (SELECT reviewer_sk FROM scores WHERE score >= {score_cut})
        SELECT e.r1, e.r2, e.{column} AS w FROM edges e
        JOIN s a ON a.reviewer_sk = e.r1 JOIN s b ON b.reviewer_sk = e.r2
        WHERE e.{column} >= {shared_min}""").fetchnumpy()
    nodes = np.unique(np.concatenate([e["r1"], e["r2"]]))
    index = {int(v): i for i, v in enumerate(nodes)}
    rows = np.array([index[int(v)] for v in e["r1"]])
    cols = np.array([index[int(v)] for v in e["r2"]])
    n_comp, labels = connected_components(
        coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(nodes),) * 2),
        directed=False)
    return nodes, e, labels, n_comp


def unit_layout(g: nx.Graph, seed: int) -> dict[int, tuple[float, float]]:
    """Positions centred on 0 and scaled so the furthest node sits at radius 1."""
    n = g.number_of_nodes()
    if n == 1:
        return {next(iter(g.nodes)): (0.0, 0.0)}
    if n == 2:
        a, b = sorted(g.nodes)
        return {a: (-0.6, 0.0), b: (0.6, 0.0)}
    pos = nx.spring_layout(g, seed=seed, weight="w",
                           iterations=300 if n < 300 else 120)
    xy = np.array(list(pos.values()))
    xy -= xy.mean(axis=0)
    scale = np.sqrt((xy ** 2).sum(axis=1)).max() or 1.0
    xy /= scale
    return {node: (float(x), float(y)) for node, (x, y) in zip(pos, xy)}


def shelf_pack(sizes: list[int], base: float = 9.0, gap: float = 10.0):
    """Place circles of radius base*sqrt(size) in rows, largest first.

    Area proportional to membership, so a 45-account cluster reads as roughly twenty
    times a pair, which is the comparison the eye should be making.
    """
    radii = [base * math.sqrt(s) for s in sizes]
    total = sum((2 * r + gap) ** 2 for r in radii)
    width = math.sqrt(total * 1.8)
    centres, x, y, row_h = [], gap, gap, 0.0
    for r in radii:
        d = 2 * r
        if x + d > width and x > gap:
            x, y, row_h = gap, y + row_h + gap, 0.0
        centres.append((x + r, y + r))
        x += d + gap
        row_h = max(row_h, d)
    return centres, radii, width, y + row_h + gap


def dominant_family(row) -> str:
    fam = {"T": row["score_text"] or 0, "B": row["score_behaviour"] or 0,
           "G": row["score_graph"] or 0}
    return max(fam, key=fam.get)


def disclosure(con, accounts: list[int], label: str) -> dict:
    con.execute("CREATE OR REPLACE TEMP TABLE t AS SELECT unnest(?::BIGINT[]) AS reviewer_sk",
                [accounts])
    # hash() rather than random(): the sample has to be the same on every run.
    rows = con.execute(f"""
        SELECT reviewer_sk, review_sk FROM (
          SELECT f.reviewer_sk, f.review_sk,
                 row_number() OVER (PARTITION BY f.reviewer_sk ORDER BY hash(f.review_sk)) rn
          FROM fact f JOIN t USING (reviewer_sk))
        WHERE rn <= {SAMPLE_PER_ACCOUNT}""").fetchall()
    texts = docblob.fetch([sk for _, sk in rows])
    hits, accounts_hit, examples = 0, set(), []
    vine_hits, vine_accounts = 0, set()
    for reviewer, sk in rows:
        record = texts.get(sk) or {}
        body = record.get("reviewText") or ""
        if VINE.search(body):
            vine_hits += 1
            vine_accounts.add(reviewer)
        match = DISCLOSURE.search(body)
        if not match:
            continue
        hits += 1
        if reviewer not in accounts_hit and len(examples) < 6:
            start = max(0, match.start() - 90)
            snippet = body[start:match.end() + 70].replace("\n", " ").strip()
            examples.append({"reviewer_sk": int(reviewer), "doc_id": int(sk),
                             "summary": record.get("summary"),
                             "text": ("…" if start else "") + snippet + "…",
                             "match": match.group(0)})
        accounts_hit.add(reviewer)
    n_accounts = len({r for r, _ in rows})
    result = {"label": label, "accounts": n_accounts, "reviews_checked": len(rows),
              "reviews_disclosing": hits, "accounts_disclosing": len(accounts_hit),
              "review_rate": hits / max(len(rows), 1),
              "account_rate": len(accounts_hit) / max(n_accounts, 1),
              "vine_review_rate": vine_hits / max(len(rows), 1),
              "vine_account_rate": len(vine_accounts) / max(n_accounts, 1),
              "examples": examples}
    print(f"  {label:<36} {result['review_rate']:6.2%} of reviews, "
          f"{result['account_rate']:5.1%} of accounts ({n_accounts:,} accounts); "
          f"mentions Vine {result['vine_review_rate']:.2%}")
    return result


def main() -> None:
    if not docblob.available():
        raise SystemExit("needs the document store: run pipeline/13c_docblob.py first")
    OUT.mkdir(parents=True, exist_ok=True)
    con = common.connect()
    con.execute(f"CREATE VIEW scores AS SELECT * FROM "
                f"'{(common.DATA / 'scores' / 'reviewer_scores.parquet').as_posix()}'")
    con.execute(f"CREATE VIEW edges AS SELECT * FROM "
                f"'{(common.DATA / 'graph' / 'coreview_edges.parquet').as_posix()}'")
    con.execute(f"CREATE VIEW fact AS SELECT * FROM '{common.FACT_PARQUET.as_posix()}'")

    with common.stage("15_story: suspicious-only subgraph"):
        nodes, e, labels, n_comp = subgraph(con, SCORE_CUT, SHARED_MIN)
        sizes = np.bincount(labels)
        core_label = int(sizes.argmax())
        n_suspicious = con.execute(
            f"SELECT count(*) FROM scores WHERE score >= {SCORE_CUT}").fetchone()[0]
        print(f"  {n_suspicious:,} accounts score >= {SCORE_CUT}; {len(nodes):,} linked, "
              f"{len(e['r1']):,} links, {n_comp:,} clusters; "
              f"largest {sizes[core_label]:,} ({sizes[core_label] / len(nodes):.0%})")

    print("\n  does a stricter rule break the core up?")
    fragmentation = []
    for cut, k, col in FRAGMENTATION:
        n2, e2, l2, c2 = subgraph(con, cut, k, col)
        big = int(np.bincount(l2).max())
        fragmentation.append({"score_cut": cut, "shared_min": k, "window": col,
                              "accounts": len(n2), "edges": len(e2["r1"]),
                              "clusters": int(c2), "largest": big,
                              "largest_share": big / len(n2)})
        print(f"    score>={cut} {col}>={k}: largest {big:,} of {len(n2):,} "
              f"({big / len(n2):.0%})")

    info = {int(r["reviewer_sk"]): r for r in con.execute(f"""
        SELECT reviewer_sk, reviewerID, score, score_text, score_behaviour, score_graph,
               n_reviews, mean_rating, lifespan_days
        FROM scores WHERE score >= {SCORE_CUT}""").fetchdf().to_dict("records")}

    g = nx.Graph()
    for a, b, w in zip(e["r1"], e["r2"], e["w"]):
        g.add_edge(int(a), int(b), w=int(w))
    label_of = {int(v): int(l) for v, l in zip(nodes, labels)}

    def node_record(sk: int, x: float, y: float, cluster: int) -> dict:
        r = info[sk]
        return {"id": sk, "u": r["reviewerID"], "x": round(x, 1), "y": round(y, 1),
                "s": round(float(r["score"]), 3), "f": dominant_family(r),
                "n": int(r["n_reviews"]), "c": cluster}

    def edge_list(members: list[int], index: dict[int, int]) -> list[list[int]]:
        """[i, j, shared_products] with i < j, as positions into the node array."""
        return [[min(index[a], index[b]), max(index[a], index[b]), d["w"]]
                for a, b, d in g.subgraph(members).edges(data=True)]

    with common.stage("15_story: lay out the packs"):
        order = sorted((l for l in range(n_comp) if l != core_label),
                       key=lambda l: (-sizes[l], l))
        centres, radii, width, height = shelf_pack([int(sizes[l]) for l in order])
        pack_nodes, clusters = [], []
        for ci, (lab, (cx, cy), r) in enumerate(zip(order, centres, radii)):
            members = sorted(v for v, l in label_of.items() if l == lab)
            pos = unit_layout(g.subgraph(members), SEED + ci)
            for sk in members:
                x, y = pos[sk]
                pack_nodes.append(node_record(sk, cx + x * r * 0.82, cy + y * r * 0.82, ci))
            sub = g.subgraph(members)
            k = len(members)
            clusters.append({
                "id": ci, "size": k, "edges": sub.number_of_edges(),
                "density": round(2 * sub.number_of_edges() / (k * (k - 1)), 3),
                "cx": round(cx, 1), "cy": round(cy, 1), "r": round(r, 1),
                "mean_score": round(float(np.mean([info[m]["score"] for m in members])), 3),
                "median_reviews": int(np.median([info[m]["n_reviews"] for m in members]))})
        pack_index = {n["id"]: i for i, n in enumerate(pack_nodes)}
        pack_edges = edge_list([n["id"] for n in pack_nodes], pack_index)
        print(f"  {len(pack_nodes):,} accounts in {len(clusters):,} clusters, "
              f"{len(pack_edges):,} links, canvas {width:.0f} x {height:.0f}")

    with common.stage("15_story: lay out the core"):
        core_members = sorted(v for v, l in label_of.items() if l == core_label)
        pos = unit_layout(g.subgraph(core_members), SEED)
        core_nodes = [node_record(sk, 500 + x * 480, 500 + y * 480, 0)
                      for sk, (x, y) in pos.items()]
        core_index = {n["id"]: i for i, n in enumerate(core_nodes)}
        core_edges = edge_list(core_members, core_index)
        print(f"  {len(core_nodes):,} accounts, {len(core_edges):,} links")

    print("\n  what they wrote -- disclosure of a free or discounted product:")
    with common.stage("15_story: disclosure check"):
        pack_accounts = [n["id"] for n in pack_nodes]
        # The control is every account that is as prolific as the core but clearly not
        # suspicious -- all 4,713 of them, not a sample. A 2,500-account sample gave
        # 3.7x on one draw and 4.8x on another, which is too unstable to put on a page.
        control = [r[0] for r in con.execute(
            "SELECT reviewer_sk FROM scores WHERE score < 0.5 AND n_reviews BETWEEN 60 AND 200 "
            "ORDER BY reviewer_sk").fetchall()]
        disclosed = {
            "core": disclosure(con, core_members, "the linked core"),
            "packs": disclosure(con, pack_accounts, "the small packs"),
            "control": disclosure(con, control, "control: prolific, not suspicious"),
        }
        disclosed["ratio_core_vs_control"] = (
            disclosed["core"]["review_rate"] / max(disclosed["control"]["review_rate"], 1e-9))
        print(f"  core discloses {disclosed['ratio_core_vs_control']:.1f}x as often as the control")

    with common.stage("15_story: review ids for scoped search"):
        con.execute("CREATE OR REPLACE TEMP TABLE members AS "
                    "SELECT unnest(?::BIGINT[]) AS reviewer_sk, unnest(?::VARCHAR[]) AS grp",
                    [core_members + pack_accounts,
                     ["core"] * len(core_members) + ["packs"] * len(pack_accounts)])
        target = OUT / "group_docs.parquet"
        con.execute(f"""
            COPY (SELECT m.grp, f.review_sk::INTEGER AS review_sk
                  FROM fact f JOIN members m USING (reviewer_sk) ORDER BY 1, 2)
            TO '{target.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
        counts = dict(con.execute(
            f"SELECT grp, count(*) FROM '{target.as_posix()}' GROUP BY 1").fetchall())
        print(f"  {counts}")

    def median(values):
        return int(np.median(values)) if values else 0

    summary = {
        "score_cut": SCORE_CUT, "shared_min": SHARED_MIN,
        "all_accounts": 3_035_045, "full_graph_accounts": 1_038_862,
        "suspicious_accounts": int(n_suspicious), "linked_accounts": len(nodes),
        "links": len(e["r1"]), "clusters": int(n_comp),
        "core_accounts": len(core_nodes), "core_links": len(core_edges),
        "core_share": len(core_nodes) / len(nodes),
        "pack_accounts": len(pack_nodes), "pack_clusters": len(clusters),
        "pack_links": len(pack_edges),
        "core_median_reviews": median([info[m]["n_reviews"] for m in core_members]),
        "pack_median_reviews": median([info[m]["n_reviews"] for m in pack_accounts]),
        "core_median_lifespan": median([info[m]["lifespan_days"] or 0 for m in core_members]),
        "pack_median_lifespan": median([info[m]["lifespan_days"] or 0 for m in pack_accounts]),
        "group_reviews": {k: int(v) for k, v in counts.items()},
    }
    payload = {"summary": summary, "fragmentation": fragmentation, "disclosure": disclosed,
               "packs": {"width": round(width), "height": round(height),
                         "nodes": pack_nodes, "edges": pack_edges, "clusters": clusters},
               "core": {"width": 1000, "height": 1000,
                        "nodes": core_nodes, "edges": core_edges}}
    path = OUT / "network.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"\nWrote {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
