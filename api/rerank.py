"""Neural reranking of the BM25 shortlist, on CPU, via ONNX Runtime.

The architecture here is forced by the hardware and happens to be the right one anyway.
Embedding all 41,135,700 reviews with a transformer on a CPU with no GPU would take well
over forty hours, so dense retrieval cannot be the first stage. Instead BM25 does recall
over the whole corpus and a cross-encoder does precision over the top 50 -- which is how
production search is actually built. Measured on five fresh queries through the running
API: about 1.1 s for a shortlist of 50 (~47 pairs a second), and ~1 ms when the
(query, document) cache already holds the scores. An earlier figure of 205 pairs a
second was taken with nothing else competing for the CPU and does not hold in service.

A cross-encoder rather than a bi-encoder: it reads the query and the document together in
one pass, so it can model term interaction directly. That is strictly better per document
and only affordable because there are 50 of them rather than 41 million.

ONNX Runtime rather than PyTorch: a 16 MB runtime and a 91 MB model against a ~3.5 GB
PyTorch stack, on a C: drive that is 93% full -- and torch is currently broken on this
machine anyway. The tokeniser is the same Rust `tokenizers` library HuggingFace uses,
loaded straight from the model's own tokenizer.json.

Everything degrades gracefully: if the model has not been fetched, `available()` returns
False and search silently stays on BM25 alone.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "data" / "ir" / "model"
MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"
ONNX_FILE = MODEL_DIR / "model.onnx"
TOKENIZER_FILE = MODEL_DIR / "tokenizer.json"

MAX_LEN = 256          # query + document, in word pieces
BATCH = 16
CACHE_SIZE = 4_096

_session = None
_tokenizer = None
_lock = threading.Lock()
_cache: OrderedDict[str, float] = OrderedDict()


def available() -> bool:
    return ONNX_FILE.exists() and TOKENIZER_FILE.exists()


def _load():
    """Open the ONNX session once. Guarded, because FastAPI serves from a threadpool."""
    global _session, _tokenizer
    if _session is not None:
        return _session, _tokenizer
    with _lock:
        if _session is None:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            options = ort.SessionOptions()
            # One session shared across requests; let ORT use the cores it needs but
            # leave room for DuckDB, which is serving the same process.
            options.intra_op_num_threads = 4
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _session = ort.InferenceSession(str(ONNX_FILE), options,
                                            providers=["CPUExecutionProvider"])
            tok = Tokenizer.from_file(str(TOKENIZER_FILE))
            tok.enable_truncation(max_length=MAX_LEN)
            tok.enable_padding(length=None)
            _tokenizer = tok
    return _session, _tokenizer


def _key(query: str, doc_id: int) -> str:
    return hashlib.blake2b(f"{query}\x00{doc_id}".encode("utf-8"),
                           digest_size=16).hexdigest()


def score_pairs(query: str, docs: list[tuple[int, str]]) -> dict[int, float]:
    """Cross-encoder relevance for (query, document) pairs, batched."""
    session, tokenizer = _load()
    inputs = {i.name for i in session.get_inputs()}
    out: dict[int, float] = {}
    pending = []

    for doc_id, text in docs:
        cached = _cache.get(_key(query, doc_id))
        if cached is None:
            pending.append((doc_id, text))
        else:
            _cache.move_to_end(_key(query, doc_id))
            out[doc_id] = cached

    for start in range(0, len(pending), BATCH):
        chunk = pending[start:start + BATCH]
        encoded = tokenizer.encode_batch([(query, text or "") for _, text in chunk])
        feed = {
            "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
        }
        if "token_type_ids" in inputs:
            feed["token_type_ids"] = np.array([e.type_ids for e in encoded], dtype=np.int64)
        logits = session.run(None, {k: v for k, v in feed.items() if k in inputs})[0]
        logits = np.asarray(logits).reshape(len(chunk), -1)
        # A single-logit relevance head; squash to (0,1) so it composes with the
        # multiplicative spam penalty in search.py.
        values = 1.0 / (1.0 + np.exp(-logits[:, 0]))
        for (doc_id, _), value in zip(chunk, values):
            out[doc_id] = float(value)
            _cache[_key(query, doc_id)] = float(value)
            if len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
    return out


def rerank(query: str, hits: list[dict], depth: int = 50) -> list[dict]:
    """Reorder the first `depth` hits by cross-encoder score.

    The BM25 score is kept alongside so the UI can show what the neural pass changed --
    a reranker that silently replaces the ranking is impossible to argue with.
    """
    if not hits or not available():
        return hits
    head, tail = hits[:depth], hits[depth:]
    pairs = [(h["doc_id"], f"{h.get('summary') or ''} {h.get('snippet') or ''}")
             for h in head]
    scores = score_pairs(query, pairs)
    for h in head:
        h["rerank_score"] = scores.get(h["doc_id"], 0.0)
        h["bm25_score"] = h["score"]
    head.sort(key=lambda h: -h["rerank_score"])
    for rank, h in enumerate(head):
        h["rerank_position"] = rank

    # The tail was never scored by the model, but it still needs a value on the same
    # scale: the caller may multiply by a spam penalty and re-sort, and a raw BM25
    # score (tens) against a cross-encoder probability (0 to 1) would shuffle unjudged
    # documents to the top. Ranking them just below the judged set keeps their own
    # order and keeps them behind everything the model actually looked at.
    if tail:
        floor = min((h["rerank_score"] for h in head), default=0.0)
        span = max(len(tail), 1)
        for i, h in enumerate(tail):
            h["bm25_score"] = h["score"]
            h["rerank_score"] = floor * (1.0 - (i + 1) / (span + 1))
    return head + tail
