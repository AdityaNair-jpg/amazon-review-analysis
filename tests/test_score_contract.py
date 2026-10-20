"""The score's structural contract, enforced as tests rather than as discipline.

Three things must hold or the headline claim of the project collapses:

1. The three signal families share no feature. The project's central argument --
   "three independent information sources agree on who is at the top" -- is only
   evidence if they are actually independent in their inputs.

2. No helpful-vote quantity enters the score. Helpful votes are the Stage 10
   validation proxy. Scoring on them and then validating against them would
   produce a high AUC that means nothing.

3. No rating LEVEL enters the score. This corpus is 59.21% five-star, so a level
   feature flags three fifths of the population. Ratings may enter only as a
   deviation from the product's own consensus, or as a within-reviewer
   distribution shape.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))


def _load(name: str):
    """pipeline modules start with digits, so they need a path-based import."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "pipeline" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = _load("09_score")

VOTE_TOKENS = ("helpful", "vote", "votes_")
RATING_LEVEL_FEATURES = {"mean_rating", "frac_5star", "frac_extreme", "frac_4star",
                         "frac_1star", "rating", "avg_rating"}


def test_families_are_disjoint():
    families = Counter()
    for name, (family, _) in score.FEATURE_SPEC.items():
        families[name] += 1
        assert family in ("T", "B", "G"), f"{name} has unknown family {family!r}"
    duplicated = [n for n, c in families.items() if c > 1]
    assert not duplicated, f"features declared in more than one family: {duplicated}"


def test_every_family_is_populated():
    present = {family for family, _ in score.FEATURE_SPEC.values()}
    assert present == {"T", "B", "G"}, f"missing families: {{'T','B','G'}} - {present}"


def test_directions_are_declared():
    for name, (_, direction) in score.FEATURE_SPEC.items():
        assert direction in ("high", "low"), f"{name} has invalid direction {direction!r}"


def test_no_helpful_vote_feature_enters_the_score():
    leaked = [n for n in score.FEATURE_SPEC if any(t in n.lower() for t in VOTE_TOKENS)]
    assert not leaked, (
        f"helpful-vote features leaked into the score: {leaked}. "
        "These are the Stage 10 validation proxy and must not be scored on.")


def test_no_rating_level_enters_the_score():
    leaked = sorted(set(score.FEATURE_SPEC) & RATING_LEVEL_FEATURES)
    assert not leaked, (
        f"rating LEVEL features leaked into the score: {leaked}. "
        "The corpus is 59.21% five-star; levels flag three fifths of everyone.")


def test_excluded_set_and_scored_set_do_not_intersect():
    assert not (set(score.FEATURE_SPEC) & score.EXCLUDED)


@pytest.mark.parametrize("family", ["T", "B", "G"])
def test_built_score_kept_at_least_one_feature_per_family(family):
    meta_path = ROOT / "data" / "scores" / "score_meta.json"
    if not meta_path.exists():
        pytest.skip("score_meta.json not built yet (run pipeline/09_score.py)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["families"][family], f"family {family} was culled to nothing"


def test_built_score_respects_the_contract():
    meta_path = ROOT / "data" / "scores" / "score_meta.json"
    if not meta_path.exists():
        pytest.skip("score_meta.json not built yet (run pipeline/09_score.py)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    kept = set(meta["kept_features"])
    assert not (kept & set(meta["excluded_by_contract"]))
    assert not [n for n in kept if any(t in n.lower() for t in VOTE_TOKENS)]
    assert not (kept & RATING_LEVEL_FEATURES)
    # Families in the built artifact must also be disjoint.
    seen: set[str] = set()
    for members in meta["families"].values():
        assert not (seen & set(members)), "built families overlap"
        seen |= set(members)


def test_ecdf_is_a_percentile_transform():
    import numpy as np
    values = np.array([5.0, 1.0, 3.0, 3.0, 9.0])
    high = score.ecdf(values, "high")
    low = score.ecdf(values, "low")
    assert high.min() >= 0.0 and high.max() <= 1.0
    assert high[4] == high.max(), "largest value must sit at the suspicious end for 'high'"
    assert low[1] == low.max(), "smallest value must sit at the suspicious end for 'low'"
    assert high[2] == high[3], "ties must share a percentile"
    assert np.allclose(high + low, 1.0), "'low' must be the exact mirror of 'high'"
