"""Stage 11 -- the three validation studies, and the honest framing of each.

There is no ground truth in this corpus. Every number below is therefore either
against a named proxy or against data we planted ourselves, and the report says
which, every time.

V1  CROSS-FAMILY CHECK (answers the circularity objection)
    Rank reviewers by BEHAVIOUR + GRAPH only, take the top and bottom deciles,
    and ask whether a classifier using ONLY TEXT features can tell them apart.
    Text shares no feature with behaviour or graph -- that is enforced by
    tests/test_score_contract.py -- so if text recovers the ranking, the three
    families are detecting something in common rather than each other.
    Literature anchor: Fei et al. ICWSM 2013 report 71.2-77.6% on a comparable
    behavioural/linguistic split.

V2  HELD-OUT HELPFUL-VOTE PROXY (an AUC, against something we did not score on)
    Reviewers with >= 50 total votes: >= 0.75 helpful is the benign class,
    <= 0.25 the suspicious one. Measured power: 277,607 benign and 13,258
    suspicious reviewers, so the minority class is ample.
    This is the rule the REV2 and CARE-GNN Amazon benchmarks are built on. It is
    a PROXY -- helpful votes measure perceived usefulness and are themselves
    gameable -- and no helpful-vote quantity enters the score, so the comparison
    is at least not circular.

V4  SYNTHETIC INJECTION (the only real recall number)
    Campaigns planted by pipeline/10_inject.py with known membership. Recall@k is
    reported PER GRID CELL and never averaged: a single mean would hide exactly
    the configurations the detector misses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import cross_val_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SCORES = common.DATA / "scores"
FEATURES = common.DATA / "features"
VALIDATE = common.DATA / "validate"
REPORT = common.DOCS / "validation.md"

DECILE = 0.10
V1_SAMPLE = 120_000
RECALL_AT = (1_000, 5_000, 10_000, 50_000, 100_000)
SEED = 20240919


def main() -> None:
    con = common.connect()
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    emit("# Validation\n")
    emit("No ground truth exists in this corpus. Every number here is against a named "
         "proxy or against data we planted ourselves, and each section says which.\n")

    scores_path = SCORES / "reviewer_scores.parquet"
    contrib_path = SCORES / "reviewer_contributions.parquet"
    if not scores_path.exists():
        raise SystemExit("Run pipeline/09_score.py first.")

    # ---------------------------------------------------------------- V1
    with common.stage("11_validate: V1 cross-family text check"):
        import json
        meta = json.loads((SCORES / "score_meta.json").read_text(encoding="utf-8"))
        text_features = meta["families"]["T"]
        emit("## V1 - cross-family check (is the score circular?)\n")
        emit(f"Text features used: `{'`, `'.join(text_features)}`\n")

        data = con.execute(f"""
            SELECT s.reviewer_sk, s.score_behaviour, s.score_graph,
                   {', '.join('c.' + f for f in text_features)}
            FROM '{scores_path.as_posix()}' s JOIN '{contrib_path.as_posix()}' c
              USING (reviewer_sk)
        """).fetchnumpy()
        bg = (data["score_behaviour"] + data["score_graph"]) / 2.0
        lo, hi = np.quantile(bg, [DECILE, 1 - DECILE])
        mask = (bg <= lo) | (bg >= hi)
        y = (bg[mask] >= hi).astype(np.int8)
        X = np.column_stack([data[f][mask] for f in text_features])

        rng = np.random.default_rng(SEED)
        if len(y) > V1_SAMPLE:
            idx = rng.choice(len(y), size=V1_SAMPLE, replace=False)
            X, y = X[idx], y[idx]
        emit(f"Trained on {len(y):,} reviewers "
             f"({y.sum():,} top-decile by B+G, {(1 - y).sum():,} bottom-decile).\n")

        model = HistGradientBoostingClassifier(max_iter=150, random_state=SEED)
        acc = cross_val_score(model, X, y, cv=5, scoring="accuracy")
        auc = cross_val_score(model, X, y, cv=5, scoring="roc_auc")
        emit(f"- Text-only accuracy: **{acc.mean():.3f}** (+/- {acc.std():.3f}), "
             f"chance = 0.500 on balanced classes")
        emit(f"- Text-only ROC AUC: **{auc.mean():.3f}** (+/- {auc.std():.3f})\n")
        emit("> Text features share no input with behaviour or graph, so this is not "
             "the score predicting itself. Fei et al. (ICWSM 2013) report 71.2-77.6% "
             "on a comparable behavioural/linguistic split.\n")
        verdict = ("the three families are detecting a common underlying phenomenon"
                   if acc.mean() > 0.60 else
                   "text carries little of the same signal; the score leans on B and G")
        emit(f"**Reading:** {verdict}.\n")

    # ---------------------------------------------------------------- V2
    with common.stage("11_validate: V2 helpful-vote proxy AUC"):
        emit("## V2 - held-out helpful-vote proxy\n")
        proxy = con.execute(f"""
            SELECT s.score, s.score_text, s.score_behaviour, s.score_graph,
                   CASE WHEN v.helpful_ratio <= 0.25 THEN 1 ELSE 0 END AS label
            FROM '{scores_path.as_posix()}' s
            JOIN '{(FEATURES / 'feat_reviewer_votes.parquet').as_posix()}' v
              USING (reviewer_sk)
            WHERE v.votes_total >= 50
              AND (v.helpful_ratio >= 0.75 OR v.helpful_ratio <= 0.25)
        """).fetchnumpy()
        label = proxy["label"]
        emit(f"Cohort: **{len(label):,}** reviewers with >= 50 total votes "
             f"(**{int(label.sum()):,}** suspicious-proxy, "
             f"**{int((1 - label).sum()):,}** benign-proxy).\n")
        rows = []
        for name, key in (("combined score", "score"), ("text (T)", "score_text"),
                          ("behaviour (B)", "score_behaviour"), ("graph (G)", "score_graph")):
            auc = roc_auc_score(label, proxy[key])
            ap = average_precision_score(label, proxy[key])
            rows.append(f"| {name} | {auc:.4f} | {ap:.4f} |")
        emit("| Ranking | ROC AUC | Average precision |")
        emit("|---|---|---|")
        for row in rows:
            emit(row)
        emit(f"\nBase rate of the suspicious-proxy class: "
             f"{label.mean():.4f} (that is the AP a random ranking would get).\n")
        emit("> **This is a proxy, not ground truth.** Helpful votes measure perceived "
             "usefulness and are themselves gameable. It is reported because it is the "
             "labelling rule the REV2 and CARE-GNN Amazon benchmarks use, and because "
             "no helpful-vote quantity enters the score -- so the comparison is at least "
             "not circular.\n")

    # ---------------------------------------------------------------- V4
    inj_scores = common.DATA / "scores" / "reviewer_scores_inj.parquet"
    campaigns = VALIDATE / "campaigns.parquet"
    emit("## V4 - synthetic injection (the only real recall number)\n")
    if not (inj_scores.exists() and campaigns.exists()):
        emit("_Not run._ Build it with `pipeline/10_inject.py`, re-run stages 4-9 under "
             "`BDA_NAMESPACE=_inj`, then re-run this script.\n")
    else:
        with common.stage("11_validate: V4 injection recall@k"):
            con.execute(f"""
                CREATE OR REPLACE TEMP TABLE ranked AS
                SELECT s.reviewer_sk, s.score, s.score_any, s.score_graph,
                       (rank() OVER (ORDER BY s.score DESC))::BIGINT       AS rnk,
                       (rank() OVER (ORDER BY s.score_any DESC))::BIGINT   AS rnk_any,
                       (rank() OVER (ORDER BY s.score_graph DESC))::BIGINT AS rnk_g,
                       c.campaign_id, c.g, c.p, c.w, c.rho, c.camouflage, c.cell
                FROM '{inj_scores.as_posix()}' s
                LEFT JOIN '{campaigns.as_posix()}' c USING (reviewer_sk)
            """)
            total, planted = con.execute(
                "SELECT count(*), count(*) FILTER (WHERE campaign_id IS NOT NULL) "
                "FROM ranked").fetchone()
            emit(f"Population: **{total:,}** accounts, of which **{planted:,}** are planted "
                 f"({100 * planted / total:.3f}%).\n")

            emit("### Overall recall@k, by aggregation\n")
            emit("Three rankings, because they answer different questions: the CONSENSUS "
                 "score (mean of the three family ranks), the ANY score (max of them), and "
                 "the GRAPH family on its own. A planted campaign's only real anomaly is its "
                 "co-review structure -- its text and ratings are sampled from the real "
                 "corpus and are meant to look ordinary -- so the consensus score, which "
                 "requires several families to agree, is the wrong instrument for it and is "
                 "reported here to show that rather than to hide it.\n")
            emit("| k | consensus | lift | any | lift | graph only | lift |")
            emit("|---|---|---|---|---|---|---|")
            for k in RECALL_AT:
                cells = []
                for column in ("rnk", "rnk_any", "rnk_g"):
                    hit = con.execute(
                        f"SELECT count(*) FROM ranked WHERE campaign_id IS NOT NULL "
                        f"AND {column} <= {k}").fetchone()[0]
                    recall = hit / planted
                    cells += [f"{recall:.4f}", f"{recall / (k / total):.1f}x"]
                emit(f"| {k:,} | " + " | ".join(cells) + " |")
            med, med_any, med_g = con.execute(
                "SELECT median(rnk), median(rnk_any), median(rnk_g) FROM ranked "
                "WHERE campaign_id IS NOT NULL").fetchone()
            emit(f"\nMedian rank of a planted account, of {total:,}: "
                 f"**{med:,.0f}** by consensus, **{med_any:,.0f}** by any, "
                 f"**{med_g:,.0f}** by graph alone.\n")
            in_ring = con.execute(
                "SELECT count(*) FROM ranked WHERE campaign_id IS NOT NULL "
                "AND score_graph >= 0.99").fetchone()[0]
            emit(f"Planted accounts the graph family places in its top percentile: "
                 f"**{in_ring:,}** of {planted:,} ({100 * in_ring / planted:.1f}%).\n")

            emit("### Per grid cell\n")
            emit("Never averaged: the cells the detector misses are the informative ones.\n")
            emit("| G | P | W | rho | camouflage | planted | graph r@10k | graph r@50k | "
                 "any r@50k | consensus r@50k |")
            emit("|---|---|---|---|---|---|---|---|---|---|")
            for row in con.execute("""
                SELECT g, p, w, rho, camouflage, count(*) AS n,
                       avg(CASE WHEN rnk_g   <= 10000 THEN 1.0 ELSE 0.0 END) AS g10k,
                       avg(CASE WHEN rnk_g   <= 50000 THEN 1.0 ELSE 0.0 END) AS g50k,
                       avg(CASE WHEN rnk_any <= 50000 THEN 1.0 ELSE 0.0 END) AS a50k,
                       avg(CASE WHEN rnk     <= 50000 THEN 1.0 ELSE 0.0 END) AS c50k
                FROM ranked WHERE campaign_id IS NOT NULL
                GROUP BY 1, 2, 3, 4, 5 ORDER BY g10k DESC, g, p, w, rho
            """).fetchall():
                emit(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | "
                     f"{'yes' if row[4] else 'no'} | {row[5]} | {row[6]:.3f} | "
                     f"{row[7]:.3f} | {row[8]:.3f} | {row[9]:.3f} |")

            best = con.execute("""
                SELECT cell, avg(CASE WHEN rnk_g <= 10000 THEN 1.0 ELSE 0.0 END) r
                FROM ranked WHERE campaign_id IS NOT NULL GROUP BY 1 ORDER BY r DESC LIMIT 1
            """).fetchone()
            worst = con.execute("""
                SELECT cell, avg(CASE WHEN rnk_g <= 10000 THEN 1.0 ELSE 0.0 END) r
                FROM ranked WHERE campaign_id IS NOT NULL GROUP BY 1 ORDER BY r ASC LIMIT 1
            """).fetchone()
            emit(f"\n**Best cell:** `{best[0]}` at recall@10k = {best[1]:.3f}. "
                 f"**Worst cell:** `{worst[0]}` at {worst[1]:.3f}.\n")
            emit("> Read the worst cell as the honest headline: it is the campaign shape "
                 "this pipeline does not catch, and it bounds what the score can be "
                 "trusted to find.\n")

    emit("## What none of this establishes\n")
    emit("- No real review in this corpus is labelled. The ranking identifies accounts "
         "whose behaviour is statistically unusual along three independent axes; it does "
         "not establish that any particular account is fraudulent.\n")
    emit("- The 5-core filter removed every singleton reviewer, the 2014 release carries "
         "no verified-purchase flag, and no product metadata is used. Methods that depend "
         "on those are not merely unimplemented here, they are unimplementable.\n")
    emit("- V2 is a proxy. V1 tests internal consistency, not correctness. V4 measures "
         "recall on campaigns matching the shapes we chose to generate, so it bounds "
         "performance on those shapes and says nothing about shapes outside the grid.\n")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    con.close()
    print(f"\nWrote {REPORT}")


if __name__ == "__main__":
    main()
