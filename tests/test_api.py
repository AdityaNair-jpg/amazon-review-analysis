"""API contract tests.

These are about the guardrails, not about the numbers. The numbers are asserted
in the pipeline stages themselves; what matters here is that no endpoint can be
talked into scanning the whole corpus, interpolating a user string into SQL, or
handing the browser a million rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

fastapi_testclient = pytest.importorskip("fastapi.testclient")
from api import db  # noqa: E402
from api.main import app  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (ROOT / "data" / "scores" / "reviewer_scores.parquet").exists(),
    reason="pipeline artifacts not built",
)


@pytest.fixture(scope="module")
def client():
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_health_lists_views(client):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert {"fact", "scores", "feat_reviewer"} <= set(body["views"])


def test_overview_matches_the_measured_corpus(client):
    corpus = client.get("/overview").json()["corpus"]
    assert corpus["n_reviews"] == 41_135_700
    assert corpus["n_reviewers"] == 3_035_045
    assert corpus["n_products"] == 1_569_973


def test_limit_is_capped(client):
    body = client.get("/reviewers", params={"limit": 999_999}).json()
    assert body["limit"] == db.MAX_LIMIT
    assert len(body["items"]) <= db.MAX_LIMIT


def test_unknown_sort_column_is_rejected_not_interpolated(client):
    """A column name that is not on the whitelist must fall back, never execute."""
    malicious = client.get(
        "/reviewers", params={"sort": "score; DROP TABLE scores --", "limit": 3})
    assert malicious.status_code == 200
    default = client.get("/reviewers", params={"limit": 3}).json()
    assert malicious.json()["items"] == default["items"]
    # and the database is still there
    assert client.get("/overview").json()["corpus"]["n_reviews"] == 41_135_700


def test_score_filter_narrows_the_result(client):
    everything = client.get("/reviewers", params={"limit": 1}).json()["total"]
    narrow = client.get("/reviewers", params={"min_score": 0.99, "limit": 1}).json()["total"]
    assert 0 < narrow < everything


def test_reviewers_are_ordered_by_score_descending(client):
    items = client.get("/reviewers", params={"limit": 50}).json()["items"]
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)


def test_reviewer_detail_explains_its_own_score(client):
    top = client.get("/reviewers", params={"limit": 1}).json()["items"][0]
    detail = client.get(f"/reviewers/{top['reviewer_sk']}").json()
    assert detail["profile"]["reviewerID"] == top["reviewerID"]
    assert detail["contributions"], "the explain panel must have something to show"
    families = {c["family"] for c in detail["contributions"]}
    assert families <= {"T", "B", "G"}
    assert all(0.0 <= c["percentile"] <= 1.0 for c in detail["contributions"])


def test_missing_reviewer_is_a_404(client):
    assert client.get("/reviewers/999999999").status_code == 404


def test_products_resolve_by_sk_and_by_asin(client):
    first = client.get("/products", params={"limit": 1}).json()["items"][0]
    by_sk = client.get(f"/products/{first['product_sk']}").json()
    by_asin = client.get(f"/products/{first['asin']}").json()
    assert by_sk["product"]["product_sk"] == by_asin["product"]["product_sk"]


def test_product_series_carries_the_detrended_expectation(client):
    first = client.get("/products", params={"limit": 1}).json()["items"][0]
    series = client.get(f"/products/{first['product_sk']}").json()["series"]
    assert series, "a product with reviews must have a timeline"
    assert all("expected" in p and "z" in p for p in series)
    # E is floored at 1.0, so a product-day can never produce an infinite z.
    assert all(p["expected"] >= 1.0 for p in series)


def test_rings_are_small_and_dense(client):
    """The ring definition is size- and density-bounded by construction."""
    rings = client.get("/rings", params={"limit": 200}).json()["items"]
    assert rings
    assert all(3 <= r["n_members"] <= 200 for r in rings)
    assert all(r["density"] >= 0.30 for r in rings)


def test_ring_detail_caps_the_subgraph(client):
    ring = client.get("/rings", params={"limit": 1}).json()["items"][0]
    detail = client.get(f"/rings/{ring['ring_id']}", params={"max_nodes": 5}).json()
    assert len(detail["members"]) <= 5
    ids = {m["reviewer_sk"] for m in detail["members"]}
    assert all(e["r1"] in ids and e["r2"] in ids for e in detail["edges"])


@pytest.mark.parametrize("kind", ["exact", "loose", "tight"])
def test_duplicate_clusters_and_their_members(client, kind):
    listing = client.get("/duplicates", params={"kind": kind, "limit": 1}).json()
    assert listing["total"] > 0
    cluster = listing["items"][0]
    detail = client.get(f"/duplicates/{kind}/{cluster['cluster_id']}").json()
    assert len(detail["members"]) >= 2
    assert all(m["reviewText"] for m in detail["members"])
    if kind != "exact":
        threshold = 0.707 if kind == "loose" else 0.878
        assert all(m["jaccard"] >= threshold for m in detail["members"])


def test_bad_duplicate_kind_is_a_400(client):
    assert client.get("/duplicates/nonsense/1").status_code == 400


def test_list_responses_ship_snippets_not_whole_reviews(client):
    top = client.get("/reviewers", params={"limit": 1}).json()["items"][0]
    detail = client.get(f"/reviewers/{top['reviewer_sk']}").json()
    for review in detail["recent_reviews"]:
        assert len(review["snippet"]) <= db.SNIPPET_CHARS
