# Coordinated Review Detection — 41M Amazon Reviews, Entirely Local

A big-data pipeline and Next.js dashboard that surfaces **coordinated and templated
reviewing behaviour** in the McAuley/UCSD Amazon review corpus.

No cloud services, no hosted databases, no cloud storage, no API keys. Everything
runs on one laptop from one 9.87 GiB file.

---

## The corpus

`kcore_5.json.gz` — Amazon product data (2014 release), complete review data,
5-core. Measured over three full passes, not estimated:

| | |
|---|---|
| Reviews | **41,135,700** |
| Reviewers | **3,035,045** (min 5, median 8, max 23,851) |
| Products | **1,569,973** (min 5, median 10, max 13,550) |
| Period | 1996-05-20 → 2014-07-23, day-granular |
| Five-star share | 59.21% |
| Decompressed | ~44.3 GB JSON |

Fields, and nothing else: `reviewerID, asin, reviewerName, helpful[yes,total],
reviewText, overall, summary, unixReviewTime, reviewTime`.

## What it finds

- **1,381 coordination rings** — small, dense groups of accounts that co-reviewed
  the same products within days of each other; 247 of them complete graphs. The
  cleanest is six accounts hitting the same nineteen products inside 88 days with
  every single rating a five; the largest is 70 accounts across 905 products.
- **79,938 verified near-duplicate text clusters** covering 172,600 reviews, found
  by MinHash + LSH and then confirmed by exact Jaccard (17.7% of LSH candidates
  were rejected at that step).
- **26,354 exact-duplicate clusters** — though the largest of these turn out to be
  Amazon's own review-writing guidelines pasted in as reviews, which the dashboard
  says plainly rather than presenting them as campaigns.
- A per-account **suspicion score** built from three signal families that share no
  input feature, with a per-feature explanation for every account.

See [`docs/findings.md`](docs/findings.md) for the full write-up, including the
parts that did not work.

## What it is not

This is **not** bot detection and **not** fake-review detection. The 5-core filter
removed every singleton reviewer, the 2014 release has no verified-purchase flag,
no product metadata is used, and the corpus predates LLM-generated text entirely.
There are no labels anywhere in this data. The defensible claim is *coordinated and
templated reviewing behaviour among established accounts*, and the dashboard says so
on every page.

## Search

> **Removed from the running dashboard.** To keep only the visualizations, the ~67 GB of
> search data (`data/ir/`) was deleted, and Search was taken out of the navigation. The
> code is all still here: running `pipeline/13_index.py`, `13b_docstore.py` and
> `13c_docblob.py` brings it back. What follows describes how it worked and what it found.

The same corpus, from the other direction: an investigator pastes a suspicious
sentence and wants every account that posted it, out of 41.1 million reviews.

Scanning `reviewText` for a phrase takes **128 seconds** — it reads all 9.7 GiB. So the
text is inverted once, in advance.

| | |
|---|---|
| Postings | **1,866,565,578** (word, review) pairs |
| Vocabulary | **4,584,763** distinct Porter stems, 0 hash collisions |
| Index on disk | 8.32 GiB postings + 0.07 GiB dictionary, ZSTD |
| Build | 22 min tokenising on 5 processes, 18 min merging |
| Average document | 58.26 terms after stopping (max 4,738) |

**Ranking is BM25**, `k1=1.2, b=0.75`, evaluated in DuckDB. Two things make it fast
enough to be interactive on a laptop:

- The postings are sorted by `term_id`, so Parquet row-group statistics turn a term
  lookup into a read of two or three row groups instead of a scan of 1.87 billion
  rows. Measured at ~90 ms whether the term appears in 1,190 reviews or 2,026,842.
- The BM25 length normalisation is **precomputed into the posting** at merge time
  rather than applied per query. Storing raw term frequencies instead meant every
  query joined its postings against all 41.1M document lengths, and a four-term query
  spent 1.6 of its 2.0 seconds doing exactly that.

**Then a cross-encoder re-reads the top 50.** `ms-marco-MiniLM-L-6-v2` under ONNX
Runtime — 16 MB of runtime and a 91 MB model, against ~3.5 GB for a PyTorch stack on a
C: drive that is 93% full. Embedding all 41M documents for dense retrieval would take
over forty hours on this CPU, so BM25 does recall over the corpus and the neural model
does precision over a shortlist. That is how production search is built, not a
concession. Measured at 205 pairs/second; off by default, one toggle away.

**And the ranking knows about the spam analysis.** Every hit carries its author's
suspicion score, ring membership and reused-text cluster, and a *demote* toggle
multiplies relevance by how independent the author looks. Ranking documents when some
of the authors are actively gaming the ranking is its own IR problem (Manning IIR
ch. 19) — and here it is one query, not two systems bolted together.

Accuracy is measured without anyone hand-judging anything: a query is the opening
words of a review in a verified near-duplicate cluster, and its cluster-mates are the
relevant set. The ground truth comes from MinHash and LSH, a completely different part
of the pipeline from the ranking being scored. See
[`docs/ir_evaluation.md`](docs/ir_evaluation.md).

### How the two halves meet

The dashboard tells this as one story, and each step uses a different half of the project.

1. **A shopper searches** (IR: ranking). Across 40 ordinary shopping searches, 5.3% of
   first-page results come from a top-1% suspicious account, against a 3.9% base rate:
   only 1.3x. 27 of the 40 had none at all. It is concentrated rather than widespread,
   and bad in a few categories: "vitamin supplement" has 5 of 10. The search page shows
   all 40, not only the worst.
2. **Click an author, and they sit in a network** (big data: graph). Restricted to the
   top 1%, the co-review graph is 3,529 accounts and 17,730 links, and it splits into two
   shapes: ~390 small separate groups, and one connected core of 2,479 accounts that no
   stricter linking rule breaks up (61-72% of accounts in one piece across six rules).
3. **Why is the core linked? Search what it wrote** (IR: full-text search scoped to one
   group's reviews). The core says it received the product free or discounted in exchange
   for the review **4.7x as often** as all 4,713 equally prolific non-suspicious accounts
   (1.68% vs 0.36% of reviews). The small groups almost never say so (0.03%). Same score,
   two different behaviours. Amazon Vine is ruled out: 0.17% vs 0.16%.

Search is what answers step 3: the network shows *that* accounts are connected, and only
their text says *why*. Neural reranking earns its place there too: scoped to the core,
BM25 puts genuine disclosures at 8 of the top 10; the cross-encoder makes it 10 of 10.

### IR techniques, and where they live

| Technique | Reference | File |
|---|---|---|
| Inverted index, SPIMI block construction | IIR §4.3 | `pipeline/13_index.py` |
| Porter stemming, stopping, tokenisation | IIR §2.2 | `pipeline/13_index.py` |
| BM25, impact-ordered postings | IIR ch. 11, §7.1.5 | `pipeline/13_index.py`, `api/search.py` |
| Neural cross-encoder reranking | — | `api/rerank.py` |
| Shingling, MinHash, LSH | IIR §19.6 | `pipeline/06_minhash.py` |
| Jaccard near-duplicate verification | IIR §19.6 | `pipeline/07_neardup.py` |
| PageRank, eigenvector centrality | IIR ch. 21 | `pipeline/08_graph.py` |
| Adversarial IR / web spam | IIR ch. 19 | the whole detection half |
| Query-time stopping by collection frequency | IIR §2.2.2 | `api/search.py` |
| MRR, nDCG@10 evaluation | IIR ch. 8 | `pipeline/14_evaluate.py` |
| Filtered retrieval, scoped to one group's documents | — | `api/search.py` (`group=`) |
| Spam demotion as a ranking penalty | IIR ch. 19 | `api/search.py` (`demote=`) |

One technique from the textbook is deliberately **not** used, and the reason is
specific to this corpus. Champion lists (IIR §7.1.2) keep each term's top-N postings by
impact and search those first. Reviews here average 58 terms, so `tf` is 1 for almost
every posting, which makes "highest impact" mean "shortest document" rather than "most
relevant". Measured on a four-term query, generating candidates that way agreed with
exact BM25 on **0 of the top 20**. Dropping the two dozen stems that appear in more
than 15% of the corpus achieves the same speedup without that cost, since those are
also the terms contributing least to the ranking.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Storage | Parquet + ZSTD on local disk | 9.7 GiB for 41.1M rows; no database server to run |
| Engine | DuckDB 1.4 in-process | out-of-core joins on a 15.4 GB box, spilling to D: |
| Compute | numpy / scipy.sparse / scikit-learn | CSR graphs; `networkx` would need tens of GB |
| API | FastAPI + uvicorn on 127.0.0.1:8000 | read-only DuckDB; keeps the Python ML stack available |
| UI | Next.js 16 + shadcn/ui + Recharts | proxied to the API through a `next.config` rewrite |
| Retrieval | own inverted index + BM25 in DuckDB | 1.87B postings; no Lucene, no search server |
| Result fetch | flat blob + memory-mapped offset index | a seek, not a query; Parquet floors at ~250 ms |
| Reranking | ONNX Runtime, MiniLM cross-encoder | 107 MB total; no GPU, no PyTorch |

The frontend talks to a Python sidecar rather than calling DuckDB from Node because
Turbopack (the default bundler in Next 16) breaks on the native `duckdb.node` addon
and its sibling DLL on Windows.

## Layout

```
pipeline/   numbered build stages, each asserting its own outputs
api/        FastAPI service over the precomputed Parquet artifacts
web/        Next.js dashboard
data/       all derived artifacts (gitignored; rebuilt by pipeline/)
docs/       data quality, findings, validation, scaling, retrieval accuracy
tests/      score-contract and API tests
```

## Run it

One command, from the project folder:

```bash
python run.py
```

On Windows you can also double-click `run.bat`.

It checks the Python packages and Node, builds whatever the dashboard needs that does
not exist yet, starts the API and the dashboard, and opens the dashboard in your
browser. Ctrl+C stops both. Everything it builds is kept, so after the first time it
starts in seconds. Both servers listen on `127.0.0.1` only.

The first run from nothing needs the source file `kcore_5.json.gz` in the project
folder, Python 3.10+, Node.js and pnpm, and takes about an hour on the reference
laptop. It shows what it is about to build, with an estimate, and asks before starting.

```bash
python run.py --status            # what is built, missing or out of date
python run.py --dev               # dashboard with hot reload, for editing the UI
python run.py --rebuild 09_score  # redo a stage and everything downstream of it
python run.py --reports           # also build the optional write-ups (below)
python run.py --no-browser        # start without opening a browser
```

If a stage looks older than its inputs, `run.py` warns and prints the command to fix it
rather than silently starting hours of rebuilding. If a previous run was closed without
Ctrl+C, the next one stops the servers it left behind. It never stops processes it did
not start itself. Server logs go to `logs/`.

### What it runs

In dependency order. Each stage checks its own outputs against the measured corpus
totals and stops the build on a mismatch.

| Stage | Takes | Builds |
|---|---|---|
| `01`–`09` | ~60 min | ingest, fact table, features, duplicates, MinHash, near-duplicates, graph, scores |

Optional write-ups, built only with `--reports` because nothing on screen depends on
them: `run_injection` (validation study, ~25 min), `12_scaling` (the 1M/5M/10M/41M
scaling table).

Every stage can still be run by hand, e.g. `python pipeline/13_index.py`, and
`python -m pytest tests/ -q` runs the tests.

## Design decisions worth knowing

**The `.gz` is read exactly once.** Gzip is a single member and decodes serially at
~210 MB/s regardless of thread count, so that pass is the hard floor on ingest. Every
per-row text counter and hash is computed inline during it; benchmarked, they add
under 5% on top of the decode.

**No rating *level* enters the score.** The corpus is 59.21% five-star, so a
"mostly positive" rule flags three fifths of the population. Ratings enter only as a
leave-one-out deviation from the product's own consensus, or as a distribution shape.
A unit test enforces this.

**Every temporal feature is de-trended.** 2013 alone holds 14.79M of the 41.1M
reviews; 1997 holds 2,707. Burst scores are computed against the corpus-wide daily
volume, which brings the correlation between burst score and calendar year down to
+0.093.

**Helpful votes never enter the score.** They are the validation proxy. Scoring on
them and then validating against them would produce a meaningless AUC. A unit test
enforces this too.

**A connected component is not a ring.** The co-review graph does not fragment at any
threshold — at ">=2 shared products within 30 days" the largest component already
holds 82.1% of it. A ring is defined as a small, dense component instead, and the
44,039-account small-world core is reported and excluded.

**Parquet is not a point-lookup format, and search is nothing but point lookups.**
Fetching twenty results by id started at 3.1 s, because `review_sk` is Parquet's
virtual row number in the raw archive and the fact table is sorted by `reviewer_sk`,
so neither can prune row groups on it. Stage 13b fixed the pruning and got it to
529 ms. It would not go lower: fetching a *single* row still cost 252 ms, because
every query re-parses the file footer. Row-group tuning only moves that cost around
(8,192 rows -> 855 ms, 20,000 -> 529 ms), splitting text from metadata made it worse
(769 ms), and `enable_object_cache` did nothing. Stage 13c stores the documents in a
flat file with a memory-mapped offset index instead, which is what a lookup by dense
integer id actually wants.

**The injection study found a real bug.** Planting campaigns with known ground truth
revealed that a `>=20 reviews` eligibility floor on the co-review graph made the
detector structurally blind to every small account — the exact shape a campaign would
use. Removing it took the graph from 311,005 to 1,038,862 reviewers and from 314 to
1,381 rings.
