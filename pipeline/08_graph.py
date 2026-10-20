"""Stage 8 -- the two co-review graph projections.

Uncapped, the reviewer-reviewer projection is sum over products of C(n_reviewers, 2)
= 6,568,246,727 pair instances (measured). That is not tractable here, and the
blow-up is driven entirely by popular products: the largest carries 13,550
reviewers, contributing 91.8M pairs on its own. Both projections are therefore
degree-capped, and the caps are reported rather than hidden.

A. REVIEWER <-> REVIEWER  (the ring finder)
   Products with <= 100 reviewers; NO reviewer-degree floor. An earlier version
   required >= 20 reviews, and the injection study measured that this made the
   detector structurally blind to every planted account below that size -- see
   the note on REVIEWER_MIN_REVIEWS in common.py.
   Measured: 11,181,701 reviewer pairs sharing >= 2 products, in 63s.

   A connected component is NOT a ring, and assuming otherwise is the central
   error available here. Measured on this corpus: at "co-reviewed >= 2 products
   within 30 days" the largest component already holds 82.1% of the graph, and
   tightening to >= 8 only moves it to 89.2%. The graph does not fragment because
   a reviewing population is small-world by nature -- a few prolific accounts
   bridge everything. The sweep is printed at run time as evidence.

   A ring is therefore a SMALL, DENSE component: 3-200 accounts, internal density
   >= 0.30, linked by co-reviewing >= 3 products within 30 days of each other.
   That is the Mukherjee et al. (WWW 2012) group signal reduced to what
   day-granular timestamps support. The giant component is reported and excluded.

B. PRODUCT <-> PRODUCT  (He, Hollenbeck & Proserpio, PNAS 2022)
   Reviewers with <= 50 reviews (keeps 2,954,421 of 3,035,045 = 97.3%).
   Measured: 246,890,819 pair instances before aggregation.
   This is the only construction in the fake-review literature validated against
   externally-sourced real Amazon ground truth, and it needs nothing but
   (reviewerID, asin) -- which is all this corpus reliably provides.

scipy.sparse CSR throughout. networkx costs ~500 B/edge and would need tens of GB
on graphs this size; it is reserved for the 50-200 node drill-down subgraphs the
dashboard serves.

Clustering coefficient is deliberately NOT computed: triangle counting needs
A @ A, which densifies catastrophically on a graph with hubs this heavy. Degree,
PageRank and eigenvector centrality are all power-iteration cheap and carry the
same structural signal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

GRAPH = common.DATA / "graph"
COREVIEW_EDGES = common.ns(GRAPH / "coreview_edges.parquet")
RING_MEMBERS = common.ns(GRAPH / "ring_members.parquet")
RINGS = common.ns(GRAPH / "rings.parquet")
PRODUCT_EDGES = common.ns(GRAPH / "product_edges.parquet")
PRODUCT_CENTRALITY = common.ns(GRAPH / "product_centrality.parquet")

PRODUCT_GRAPH_REVIEWER_CAP = 50   # keeps 97.3% of reviewers; hubs distort the projection
MIN_SHARED_PRODUCTS = common.MIN_SHARED_PRODUCTS
MIN_SHARED_REVIEWERS = 2

# Ring definition. A connected component is NOT a ring -- see the measured sweep
# in main(): this graph never fragments, because a small-world reviewing
# population is connected by construction. A ring is a SMALL, DENSE component.
EDGE_SHARED_30D = 3    # co-reviewed at least this many products within 30 days
MIN_RING_SIZE = 3
MAX_RING_SIZE = 200    # anything larger is the graph's core, not a coordinated group
MIN_RING_DENSITY = 0.30


def pagerank(adjacency, damping: float = 0.85, iterations: int = 60) -> np.ndarray:
    """Power-iteration PageRank on a symmetric CSR adjacency matrix."""
    n = adjacency.shape[0]
    out_degree = np.asarray(adjacency.sum(axis=1)).ravel()
    inverse = np.divide(1.0, out_degree, out=np.zeros(n), where=out_degree > 0)
    rank = np.full(n, 1.0 / n)
    dangling = out_degree == 0
    for _ in range(iterations):
        contribution = adjacency.T @ (rank * inverse)
        updated = damping * (contribution + rank[dangling].sum() / n) + (1 - damping) / n
        if np.abs(updated - rank).sum() < 1e-10:
            rank = updated
            break
        rank = updated
    return rank


def eigenvector_centrality(adjacency, iterations: int = 100) -> np.ndarray:
    """Power iteration for the leading eigenvector of a symmetric adjacency matrix."""
    vector = np.full(adjacency.shape[0], 1.0 / np.sqrt(adjacency.shape[0]))
    for _ in range(iterations):
        nxt = adjacency @ vector
        norm = np.linalg.norm(nxt)
        if norm == 0:
            return vector
        nxt /= norm
        if np.abs(nxt - vector).sum() < 1e-12:
            return nxt
        vector = nxt
    return vector


def main() -> None:
    common.guard_disk()
    GRAPH.mkdir(parents=True, exist_ok=True)

    con = common.connect()
    con.execute(f"CREATE VIEW f AS SELECT * FROM '{common.FACT_PARQUET.as_posix()}'")
    con.execute(f"CREATE VIEW fp AS SELECT * FROM "
                f"'{common.ns(common.DATA / 'features' / 'feat_product.parquet').as_posix()}'")
    con.execute(f"CREATE VIEW fr AS SELECT * FROM "
                f"'{common.ns(common.DATA / 'features' / 'feat_reviewer.parquet').as_posix()}'")

    # ------------------------------------------------- A: reviewer <-> reviewer
    with common.stage("08_graph: reviewer co-review edges"):
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE elig AS
            SELECT f.reviewer_sk, f.product_sk, f.day
            FROM f
            JOIN fp USING (product_sk)
            JOIN fr USING (reviewer_sk)
            WHERE fp.n_reviews <= {common.PRODUCT_DEGREE_CAP}
              AND fr.n_reviews >= {common.REVIEWER_MIN_REVIEWS}
              AND f.day IS NOT NULL
        """)
        rows, reviewers, products = con.execute(
            "SELECT count(*), count(DISTINCT reviewer_sk), count(DISTINCT product_sk) "
            "FROM elig").fetchone()
        print(f"  eligible: {rows:,} reviews, {reviewers:,} reviewers, {products:,} products "
              f"(product degree <= {common.PRODUCT_DEGREE_CAP}, "
              f"reviewer reviews >= {common.REVIEWER_MIN_REVIEWS})")

        # The TEMPORAL co-occurrence count is what separates a ring from a shared
        # interest. Two enthusiasts both reviewing the same ten cameras over eight
        # years is a genre; ten accounts hitting the same ten cameras inside a
        # month is a campaign. This is the Mukherjee et al. (WWW 2012) group
        # signal, reduced to what day-granular timestamps can support.
        con.execute(f"""
            COPY (
                SELECT a.reviewer_sk AS r1, b.reviewer_sk AS r2,
                       count(*)::INTEGER AS shared,
                       count(*) FILTER (WHERE abs(a.day - b.day) <= 30)::INTEGER AS shared_30d,
                       count(*) FILTER (WHERE abs(a.day - b.day) <= 7)::INTEGER  AS shared_7d
                FROM elig a JOIN elig b
                  ON a.product_sk = b.product_sk AND a.reviewer_sk < b.reviewer_sk
                GROUP BY 1, 2
                HAVING count(*) >= {MIN_SHARED_PRODUCTS}
            ) TO '{COREVIEW_EDGES.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        con.execute(f"CREATE VIEW ce AS SELECT * FROM '{COREVIEW_EDGES.as_posix()}'")
        n_edges, max_shared, n_30, n_7 = con.execute(
            "SELECT count(*), max(shared), count(*) FILTER (WHERE shared_30d >= 2), "
            "count(*) FILTER (WHERE shared_7d >= 2) FROM ce").fetchone()
        print(f"  {n_edges:,} reviewer pairs sharing >= {MIN_SHARED_PRODUCTS} products "
              f"(max shared = {max_shared:,})")
        print(f"  of those, {n_30:,} share >= 2 products within 30 days, "
              f"{n_7:,} within 7 days")

    with common.stage("08_graph: rings (threshold sweep + connected components)"):
        edges = con.execute("SELECT r1, r2, shared, shared_30d FROM ce").fetchnumpy()
        r1, r2 = edges["r1"], edges["r2"]
        shared = edges["shared"].astype(np.int64)
        shared_30d = edges["shared_30d"].astype(np.int64)
        nodes = np.unique(np.concatenate([r1, r2]))
        lookup = np.full(int(nodes.max()) + 1, -1, dtype=np.int64)
        lookup[nodes] = np.arange(len(nodes))
        i, j = lookup[r1], lookup[r2]

        def build(mask):
            g = coo_matrix((shared[mask], (i[mask], j[mask])),
                           shape=(len(nodes), len(nodes)))
            return (g + g.T).tocsr()

        # MEASURED, and it changes the method: a co-review graph of this corpus
        # does not fragment at ANY sensible edge threshold. At ">= 2 products
        # within 30 days" the largest component holds 82.1% of the graph; pushing
        # to ">= 8" only takes it to 89.2%. That is the ordinary small-world
        # structure of a reviewing population -- a handful of prolific accounts
        # bridge everything -- not one enormous conspiracy.
        #
        # So a connected component is NOT a ring, and treating it as one would be
        # the central error available here. Components are candidates; what makes
        # a ring is DENSITY. The giant component is reported and excluded.
        print(f"  {'temporal edge rule':<28} {'reviewers':>10} {'components':>11} "
              f"{'largest':>10} {'largest %':>10}")
        for threshold in (2, 3, 4, 5, 6, 8):
            mask = shared_30d >= threshold
            if not mask.any():
                continue
            g = build(mask)
            present = np.nonzero(np.diff(g.indptr))[0]
            _, labels = connected_components(g, directed=False)
            largest = int(np.bincount(labels[present]).max()) if len(present) else 0
            print(f"  shared within 30d >= {threshold:<6} {len(present):>10,} "
                  f"{len(np.unique(labels[present])):>11,} "
                  f"{largest:>10,} {100 * largest / max(len(present), 1):>9.1f}%")
        print("\n  The graph never fragments, so components alone cannot define a ring.\n"
              f"  Edge rule: >= {EDGE_SHARED_30D} products co-reviewed within 30 days.\n"
              f"  Ring rule: component of {MIN_RING_SIZE}-{MAX_RING_SIZE} accounts with "
              f"internal density >= {MIN_RING_DENSITY}.")

        graph_full = build(shared_30d >= 2)     # per-reviewer degree features
        graph = build(shared_30d >= EDGE_SHARED_30D)
        _, labels = connected_components(graph, directed=False)
        present = np.nonzero(np.diff(graph.indptr))[0]
        sizes = np.bincount(labels)
        degree = np.diff(graph_full.indptr)
        weight = np.asarray(graph_full.sum(axis=1)).ravel() / 2.0

        candidates = np.unique(labels[present])
        candidates = candidates[(sizes[candidates] >= MIN_RING_SIZE)]
        print(f"\n  {len(present):,} reviewers survive the edge rule, in "
              f"{len(np.unique(labels[present])):,} components; "
              f"{len(candidates):,} have >= {MIN_RING_SIZE} members")

        order = np.argsort(labels, kind="stable")
        sorted_labels = labels[order]
        keep, rejected_big, rejected_sparse = [], [], []
        for comp in candidates:
            size = int(sizes[comp])
            if size > MAX_RING_SIZE:
                rejected_big.append((int(comp), size))
                continue
            lo = int(np.searchsorted(sorted_labels, comp))
            hi = int(np.searchsorted(sorted_labels, comp, side="right"))
            idx = order[lo:hi]
            sub = graph[idx][:, idx]
            density = (sub.nnz / 2) / (size * (size - 1) / 2)
            if density < MIN_RING_DENSITY:
                rejected_sparse.append((int(comp), size, density))
                continue
            keep.append(comp)
        keep = np.array(sorted(keep), dtype=np.int64)

        for comp, size in sorted(rejected_big, key=lambda x: -x[1]):
            print(f"  EXCLUDED component {comp}: {size:,} accounts -- larger than "
                  f"{MAX_RING_SIZE}, this is the graph's small-world core, not a ring")
        print(f"  EXCLUDED {len(rejected_sparse):,} components below density "
              f"{MIN_RING_DENSITY}")
        print(f"  {len(keep):,} rings kept "
              f"(largest = {int(sizes[keep].max()) if len(keep) else 0:,} members)")

        # Cohesion: realised edge weight over the complete-graph maximum. 1.0 means
        # every member co-reviewed every other member on every eligible product.
        ring_rows, member_rows = [], []
        starts = np.searchsorted(sorted_labels, keep)
        ends = np.searchsorted(sorted_labels, keep, side="right")
        for rank, comp in enumerate(keep):
            idx = order[starts[rank]:ends[rank]]
            size = len(idx)
            sub = graph[idx][:, idx]
            realised_edges = sub.nnz / 2
            possible = size * (size - 1) / 2
            density = realised_edges / possible
            mean_shared = (sub.sum() / 2) / max(realised_edges, 1)
            ring_rows.append((int(comp), size, int(realised_edges), float(density),
                              float(mean_shared)))
            member_rows.extend((int(nodes[k]), int(comp), int(degree[k]), float(weight[k]))
                               for k in idx)

        con.execute("CREATE OR REPLACE TEMP TABLE rr (ring_id INTEGER, n_members INTEGER, "
                    "n_edges INTEGER, density DOUBLE, mean_shared DOUBLE)")
        con.executemany("INSERT INTO rr VALUES (?, ?, ?, ?, ?)", ring_rows)
        con.execute("CREATE OR REPLACE TEMP TABLE rm (reviewer_sk INTEGER, ring_id INTEGER, "
                    "coreview_degree INTEGER, coreview_weight DOUBLE)")
        con.executemany("INSERT INTO rm VALUES (?, ?, ?, ?)", member_rows)

        con.execute(f"""
            COPY (
                SELECT r.ring_id, r.n_members, r.n_edges, r.density, r.mean_shared,
                       s.n_products, s.span_days, s.mean_rating, s.first_day, s.n_reviews
                FROM rr r JOIN (
                    SELECT m.ring_id,
                           count(DISTINCT f.product_sk)::INTEGER AS n_products,
                           (max(f.day) - min(f.day))             AS span_days,
                           avg(f.rating::DOUBLE)                 AS mean_rating,
                           min(f.day)                            AS first_day,
                           count(*)::INTEGER                     AS n_reviews
                    FROM rm m JOIN f USING (reviewer_sk) GROUP BY 1
                ) s USING (ring_id)
            ) TO '{RINGS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        # Every reviewer that appears in the co-review graph keeps its degree, even
        # if its component is too small to count as a ring.
        con.execute("CREATE OR REPLACE TEMP TABLE allm (reviewer_sk INTEGER, "
                    "coreview_degree INTEGER, coreview_weight DOUBLE)")
        con.executemany("INSERT INTO allm VALUES (?, ?, ?)",
                        [(int(nodes[k]), int(degree[k]), float(weight[k]))
                         for k in range(len(nodes))])
        con.execute(f"""
            COPY (
                SELECT a.reviewer_sk, a.coreview_degree, a.coreview_weight,
                       m.ring_id, coalesce(r.n_members, 0) AS ring_size,
                       coalesce(r.density, 0.0)            AS ring_density
                FROM allm a
                LEFT JOIN rm m USING (reviewer_sk)
                LEFT JOIN rr r ON r.ring_id = m.ring_id
            ) TO '{RING_MEMBERS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

    # -------------------------------------------------- B: product <-> product
    with common.stage("08_graph: product co-review projection (He et al. PNAS 2022)"):
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE eligp AS
            SELECT f.reviewer_sk, f.product_sk
            FROM f JOIN fr USING (reviewer_sk)
            WHERE fr.n_reviews <= {PRODUCT_GRAPH_REVIEWER_CAP}
        """)
        rows, reviewers = con.execute(
            "SELECT count(*), count(DISTINCT reviewer_sk) FROM eligp").fetchone()
        print(f"  eligible: {rows:,} reviews from {reviewers:,} reviewers "
              f"({100 * reviewers / common.EXPECTED_REVIEWERS:.1f}% of all, "
              f"reviewer degree <= {PRODUCT_GRAPH_REVIEWER_CAP})")

        con.execute(f"""
            COPY (
                SELECT a.product_sk AS p1, b.product_sk AS p2, count(*)::INTEGER AS shared
                FROM eligp a JOIN eligp b
                  ON a.reviewer_sk = b.reviewer_sk AND a.product_sk < b.product_sk
                GROUP BY 1, 2
                HAVING count(*) >= {MIN_SHARED_REVIEWERS}
            ) TO '{PRODUCT_EDGES.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        con.execute(f"CREATE VIEW pe AS SELECT * FROM '{PRODUCT_EDGES.as_posix()}'")
        n_edges, max_shared = con.execute("SELECT count(*), max(shared) FROM pe").fetchone()
        print(f"  {n_edges:,} product pairs sharing >= {MIN_SHARED_REVIEWERS} reviewers "
              f"(max shared = {max_shared:,})")

    with common.stage("08_graph: product centrality"):
        edges = con.execute("SELECT p1, p2, shared FROM pe").fetchnumpy()
        p1, p2, weights = edges["p1"], edges["p2"], edges["shared"].astype(np.float64)
        nodes = np.unique(np.concatenate([p1, p2]))
        lookup = np.full(int(nodes.max()) + 1, -1, dtype=np.int64)
        lookup[nodes] = np.arange(len(nodes))
        i, j = lookup[p1], lookup[p2]
        graph = coo_matrix((weights, (i, j)), shape=(len(nodes), len(nodes)))
        graph = (graph + graph.T).tocsr()
        print(f"  {len(nodes):,} products, {graph.nnz // 2:,} undirected edges, "
              f"CSR {(graph.data.nbytes + graph.indices.nbytes + graph.indptr.nbytes) / 1e6:.0f} MB")

        degrees = np.diff(graph.indptr).astype(np.int32)
        strength = np.asarray(graph.sum(axis=1)).ravel()
        ranks = pagerank(graph)
        eigen = np.abs(eigenvector_centrality(graph))
        n_comp, labels = connected_components(graph, directed=False)
        component_size = np.bincount(labels)[labels].astype(np.int32)
        print(f"  {n_comp:,} components; largest holds {component_size.max():,} products")

        con.execute("CREATE OR REPLACE TEMP TABLE pc (product_sk INTEGER, pg_degree INTEGER, "
                    "pg_strength DOUBLE, pg_pagerank DOUBLE, pg_eigen DOUBLE, "
                    "pg_component_size INTEGER)")
        con.executemany("INSERT INTO pc VALUES (?, ?, ?, ?, ?, ?)",
                        list(zip(nodes.astype(int).tolist(), degrees.tolist(),
                                 strength.tolist(), ranks.tolist(), eigen.tolist(),
                                 component_size.tolist())))
        con.execute(f"COPY pc TO '{PRODUCT_CENTRALITY.as_posix()}' "
                    f"(FORMAT PARQUET, COMPRESSION ZSTD)")

    print("\n[summary]")
    for label, path in (("coreview_edges", COREVIEW_EDGES), ("rings", RINGS),
                        ("ring_members", RING_MEMBERS), ("product_edges", PRODUCT_EDGES),
                        ("product_centrality", PRODUCT_CENTRALITY)):
        print(f"  {label:<20} {common.mb(path):8.1f} MB")

    print("\n[densest rings]")
    rows = con.execute(f"""
        SELECT ring_id, n_members, n_products, n_reviews, round(density, 3),
               round(mean_shared, 1), span_days, round(mean_rating, 2)
        FROM '{RINGS.as_posix()}'
        WHERE n_members >= 4
        ORDER BY density DESC, n_members DESC LIMIT 15""").fetchall()
    print(f"  {'ring':>8} {'accts':>6} {'prods':>6} {'revs':>7} {'dens':>6} "
          f"{'shared':>7} {'days':>6} {'rating':>6}")
    for row in rows:
        print(f"  {row[0]:>8} {row[1]:>6} {row[2]:>6} {row[3]:>7} {row[4]:>6} "
              f"{row[5]:>7} {row[6]:>6} {row[7]:>6}")

    con.close()
    print("\nStage 8 complete.")


if __name__ == "__main__":
    main()
