"""The two story exhibits: the suspicious-account network, and where search meets spam.

Both are precomputed by the pipeline (stages 15 and 16), so these endpoints only read a
JSON file and cache it. The graph is split from its summary so a page can render its
headline numbers without waiting on half a megabyte of coordinates.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/story")

STORY = Path(__file__).resolve().parent.parent / "data" / "story"


@lru_cache(maxsize=4)
def _load(name: str) -> dict:
    path = STORY / name
    if not path.exists():
        stage = "15_story_network" if name == "network.json" else "16_search_exposure"
        raise HTTPException(503, f"not built yet -- run pipeline/{stage}.py")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/network")
def network_summary() -> dict:
    """Headline numbers, the fragmentation check, the disclosure finding, cluster list."""
    data = _load("network.json")
    return {"summary": data["summary"], "fragmentation": data["fragmentation"],
            "disclosure": data["disclosure"], "clusters": data["packs"]["clusters"]}


@router.get("/network/graph")
def network_graph(view: str = Query("packs", pattern="^(packs|core)$")) -> dict:
    """Node positions and edges for one view. Laid out in the pipeline, drawn as-is."""
    return _load("network.json")[view]


@router.get("/search-exposure")
def search_exposure() -> dict:
    return _load("search_exposure.json")
