# Findings

What the pipeline actually surfaced, including the parts that did not work.

---

## 1. The corpus is not what the literature assumes

Three full passes over `kcore_5.json.gz` established the ground truth this project
is built on. Several numbers materially change which published methods are even
implementable.

| Measurement | Value |
|---|---|
| Reviews | 41,135,700 |
| Reviewers | 3,035,045 (min 5, median 8, p99 88, max 23,851) |
| Products | 1,569,973 (min 5, median 10, p99 262, max 13,550) |
| Period | 1996-05-20 to 2014-07-23, day-granular |
| Five-star share | 59.21% |
| Decompressed JSON | ~44.3 GB |

Four consequences, each of which killed or reshaped a method:

1. **No singletons.** The 5-core filter guarantees ≥5 reviews per account and per
   product. Xie et al. (KDD 2012) targets singleton reviewers; its target
   population here is empty by construction, and SpEagle's singleton indicator is
   identically zero across all 41.1M rows.
2. **No verified-purchase flag.** The 2014 release does not carry it. Fei et al.
   (ICWSM 2013) build their MRF state prior on exactly that field and call it their
   strongest feature.
3. **No product metadata.** Lim et al. (CIKM 2010) group products by brand or
   publisher; there is nothing to group by.
4. **Exactly one review per (reviewer, product).** Measured: zero duplicate pairs
   in 41,135,700 rows. A standard data-quality signal is absent by construction.

## 2. Exact duplication is rare — and normalisation more than doubles what you find

| Key | Clusters | Reviews | Share |
|---|---|---|---|
| Raw exact text | 12,101 | 70,509 | 0.171% |
| Lowercased, whitespace-collapsed | 26,354 | 106,373 | 0.259% |
| Normalised, ≥20 words | 17,196 | 34,625 | 0.084% |

Jindal & Liu (WSDM 2008) built their pseudo-labels on a much denser duplicate
population. Here duplicates are a small high-precision seed, not a backbone, and
the text signal had to come from near-duplicate detection instead.

**The biggest duplicate clusters are not campaigns.** The largest cross-account
clusters are Amazon's own "how to write a review" guideline text pasted in as a
review (15 accounts), and filler — the alphabet (16 accounts), counting to twenty
(14 accounts). These are gamed reviews, but they are not promotion. Only 73 exact
clusters have ≥3 accounts *and* ≥20 words. Reporting the top of that list without
this caveat would misrepresent it.

## 3. Near-duplicate detection is where the text signal actually lives

MinHash with 128 permutations over 5-word shingles, banded two ways from the same
signatures, then every candidate verified by exact Jaccard against its cluster
exemplar.

| Configuration | Clusters | Reviews | Cross-account | ≥3 accounts | Mean Jaccard |
|---|---|---|---|---|---|
| loose (16×8, J ≥ 0.707) | 79,938 | 172,600 | 10,381 | 184 | 0.937 |
| tight (8×16, J ≥ 0.878) | 41,874 | 87,236 | 7,898 | 132 | 0.979 |

**17.7% of LSH candidates were rejected at verification** (20.6% at the tight
threshold). Reporting LSH candidates as findings would have inflated the result by
roughly a fifth.

This is where real templated promotion appears. Cluster #60821: five accounts,
three products, mean Jaccard 0.965, every rating 5★, all posting the same long
phone-case review over 122 days.

## 4. A connected component is not a ring

This was the most important methodological correction in the project.

The obvious approach — build a co-review graph, take connected components, call
them rings — does not work on this corpus, and the failure is not subtle:

| Edge rule | Reviewers in graph | Components | Largest | Largest share |
|---|---|---|---|---|
| ≥2 shared products within 30d | 108,951 | 8,181 | 89,469 | 82.1% |
| ≥3 | 47,910 | 1,644 | 44,039 | 91.9% |
| ≥4 | 30,926 | 800 | 28,859 | 93.3% |
| ≥5 | 22,725 | 597 | 21,111 | 92.9% |
| ≥8 | 11,657 | 344 | 10,402 | 89.2% |

The graph never fragments. Tightening the threshold shrinks the graph without
breaking up the blob, because a reviewing population is small-world by nature — a
few prolific accounts bridge everything. Calling that 44,039-account component a
"ring" would have been the single largest error available here.

**A ring is therefore defined as a small, dense component**: 3–200 accounts,
internal density ≥ 0.30, linked by co-reviewing ≥3 products within 30 days of each
other. The giant component is reported and excluded rather than quietly dropped.

Result: **1,381 rings covering 5,982 accounts, 247 of them at density 1.000.**

The cleanest exhibit is ring **#179919** — six accounts, density 1.000, nineteen
products, 79 reviews, mean rating 4.95, whole operation inside 88 days:

| Product | Ring members who reviewed it | Mean rating | Window |
|---|---|---|---|
| B00JV88PJ0 | 6 of 6 | **5.00** | 23 days |
| B00JQMWCDG | 6 of 6 | **5.00** | 29 days |
| B00HFNP0OQ | 6 of 6 | **5.00** | 29 days |
| B00JQNWYCE | 6 of 6 | **5.00** | 29 days |
| B00JQPPM1C | 6 of 6 | **5.00** | 29 days |
| B00JQP3L7Y | 6 of 6 | **5.00** | 29 days |

Six accounts, all six on every product, all within a month of each other, and not
one rating below five.

The largest is ring **#11709** — 70 accounts over 905 products. Its top targets
are hit by 59-61 of those accounts inside 20-99 days each, though at a mean rating
of 3.6-4.5 rather than a flat five, which reads more like an organised
review-exchange community than a single paid campaign. The dashboard draws both as
a convergence plot: one row per product, one dot per member review, on a shared
time axis. A ring is the vertical stacks.

## 5. The three signal families largely disagree — and that is the finding

Text, behaviour and graph share no input feature (enforced by a unit test). Their
rank correlations are low:

| Pair | Spearman |
|---|---|
| Text ↔ Behaviour | +0.162 |
| Text ↔ Graph | +0.090 |
| Behaviour ↔ Graph | +0.043 |

They are mostly finding *different* accounts. Where they do overlap, they overlap
well above chance — in the top 100,000, all three agree on 771 accounts against a
chance expectation of 108.6, a sevenfold lift — but the honest summary is that
there is no single population of "suspicious accounts" that all three see.

Two consequences, both built into the product:

- The headline **consensus score** (mean of the three family ranks) is
  high-precision and low-recall by construction: 172 accounts clear 0.99.
- A **score_any** (max of the three) is exposed alongside it: 88,762 accounts clear
  0.99. It answers a different question and is labelled as such.

At k = 1,000 the chance expectation for a three-way overlap is below one account,
so the observed overlap there carries no information. That is reported as "n/a"
rather than dressed up as a zero.

## 6. The injection study found a real bug in the detector

Planting 360 synthetic campaigns (4,800 accounts, ~72k reviews) and re-running the
entire pipeline over the augmented corpus produced, on the first attempt, **almost
no recall at all** — median rank 632,368 of 3,039,845, recall@10,000 of 0.0013.

The diagnosis was unambiguous:

| Cohort | Accounts | Mean reviews | Eligible for the graph | Detected in a ring |
|---|---|---|---|---|
| Camouflaged, 8 products | 1,200 | 28.0 | 1,200 | **1,200** |
| Camouflaged, 3 products | 1,200 | 23.0 | 1,200 | **1,015** |
| Bare, 8 products | 1,200 | 12.0 | **0** | 0 |
| Bare, 3 products | 1,200 | 7.0 | **0** | 0 |

The ring detector was placing 92–100% of every planted account it was allowed to
see into a ring. It saw none of the small accounts, because the co-review graph
had a `≥20 reviews` eligibility floor that I had added purely to contain the pair
explosion. That floor made the detector structurally blind to exactly the account
shape a real campaign would use.

Measured cost of removing it: 11,181,701 pairs instead of 7,418,333, and 63 seconds
instead of 1. The graph now covers **1,038,862 reviewers instead of 311,005**, and
finds **1,381 rings instead of 314**.

This is the single most useful thing the validation harness did, and it is the
argument for building one: without planted ground truth, a detector that is blind
to half the population looks exactly like a detector that is working.

See `validation.md` for the post-fix recall numbers per campaign shape.

## 7. How the dashboard shows this

Every finding above has a view that makes it legible rather than merely stated:

| View | Chart | What it is there to show |
|---|---|---|
| Overview | Stacked area, 18 years of volume by rating | Why de-trending is mandatory: the 2013 wall is visible at a glance |
| Overview | 200-bin score histogram with a client-side threshold slider | Where any cut-off you pick actually lands, with no round trip |
| Overview | Rating donut | The 59.21% five-star base rate that rules out rating levels |
| Overview | Rating behaviour by suspicion decile (bars + line) | An independent check — the score was never given a rating level |
| Overview | Three-set Venn plus a donut | Whether there is one suspect population or three (it is three) |
| Reviewers | Scatter: burst vs rating deviation, and volume vs tenure | Where flagged accounts sit relative to everyone else; click to open |
| Reviewer | Activity timeline — time × rating, sized by length | The silhouette: a burst account is a vertical wall |
| Reviewer | Three-axis radar against the corpus median | Spike (one family) versus triangle (all three) |
| Reviewer | Per-feature contribution bars | Exactly which features drove this account's score |
| Rings | Bubble scatter: lifespan × density, sized by reviews | The short-lived, dense, multi-account corner is the one to read |
| Ring | Convergence strip plot | One row per product, one dot per member review — vertical stacks are the ring |
| Ring | Circular co-review graph | How close the group is to a complete graph |
| Ring | Rating donut | Whether the group's ratings have any spread at all |
| Duplicates | Log-log cluster-size distribution; verified-Jaccard histogram | Heavy tail, and how much LSH over-reported before verification |
| Product | Daily volume against the de-trended expectation | The gap between observed and expected, not the bar height |
| Product | Rating donut | J-shape (ordinary) versus a flat wall of fives |
| Methodology | Correlation heatmap, diverging, with unmeasurable pairs hatched | Whether the cull actually worked |
| Methodology | Observed vs chance overlap, log scale | The agreement claim, with its own null baseline beside it |

Two choices worth defending. The ring convergence plot and the circular co-review
graph are hand-drawn SVG rather than a charting library: one is a categorical-y
strip plot with a mark per observation, the other needs deterministic node
positions, and both are things general charting libraries make harder rather than
easier. And the heatmap is served from the matrix the cull itself used rather than
recomputed — an independently recomputed version cannot reproduce the cull's
active-subset filter, and the first version of that endpoint consequently accused
the cull of a bug it does not have.

## 8. What none of this establishes

- No review in this corpus is labelled. The ranking identifies accounts that are
  statistically unusual along three axes associated with coordination in the
  literature. It does not establish that any account is fraudulent.
- The helpful-vote AUC is against a **proxy** — perceived usefulness, itself
  gameable — not ground truth. It is reported because REV2 and CARE-GNN use the
  same rule, and because no helpful-vote quantity enters the score.
- The injection recall bounds performance on the campaign shapes in the grid and
  says nothing about shapes outside it.
- Burst detection is de-trended against the corpus-wide daily series, but the
  baseline is global rather than per-category, because no product metadata is used.
  A burst in Books and a burst in Electronics are compared on the same scale.
