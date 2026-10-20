# Data quality report

Source: `kcore_5.json.gz` - McAuley/UCSD Amazon product data, 2014 release, complete review data, 5-core.

## Shape

| Measure | Value |
|---|---|
| Reviews | 41,135,700 |
| Reviewers | 3,035,045 |
| Products | 1,569,973 |
| Reviews per reviewer (mean) | 13.55 |
| Reviews per product (mean) | 26.20 |

## 5-core invariant

- Reviews per reviewer: min **5**, max **23,851**
- Reviews per product: min **5**, max **13,550**
- Invariant holds: **True**

> Consequence: there are no singleton reviewers, so every method that targets them (Xie et al. KDD 2012; SpEagle's ISR feature) has an empty target population in this corpus by construction.

## Completeness

| Field | Missing | Share |
|---|---|---|
| `reviewerName` null | 932,551 | 2.27% |
| `reviewText` empty | 8,704 | 0.0212% |
| `unixReviewTime` null | 4 | 0.000010% |

Empty review text and null timestamps are excluded from text and temporal features respectively, rather than imputed.

## Rating distribution

| Stars | Reviews | Share |
|---|---|---|
| 1 | 2,504,117 | 6.09% |
| 2 | 2,066,950 | 5.02% |
| 3 | 3,833,977 | 9.32% |
| 4 | 8,374,593 | 20.36% |
| 5 | 24,356,063 | 59.21% |

> The corpus is 59.21% five-star. Any feature that flags 'mostly positive' as a level therefore flags three fifths of everyone. Rating features enter the score **only** as a deviation from the product's own distribution, or as an empirical-CDF percentile.

## Review length (words)

| Percentile | Words |
|---|---|
| p1 | 15 |
| p10 | 22 |
| p25 | 29 |
| median | 52 |
| p75 | 111 |
| p90 | 228 |
| p99 | 665 |
| mean words | 100 |
| mean chars | 541 |

Documents under 20 words: **808,313** (1.96%). These are excluded from near-duplicate detection - short text collides by chance, not by copying.

## Temporal coverage

| Year | Reviews | Share |
|---|---|---|
| 1996 | 25 | 0.00% |
| 1997 | 2,707 | 0.01% |
| 1998 | 18,657 | 0.05% |
| 1999 | 56,637 | 0.14% |
| 2000 | 248,593 | 0.60% |
| 2001 | 274,189 | 0.67% |
| 2002 | 303,205 | 0.74% |
| 2003 | 333,664 | 0.81% |
| 2004 | 413,555 | 1.01% |
| 2005 | 561,551 | 1.37% |
| 2006 | 613,914 | 1.49% |
| 2007 | 911,011 | 2.21% |
| 2008 | 1,064,548 | 2.59% |
| 2009 | 1,356,634 | 3.30% |
| 2010 | 1,798,443 | 4.37% |
| 2011 | 2,936,972 | 7.14% |
| 2012 | 5,702,329 | 13.86% |
| 2013 | 14,791,129 | 35.96% |
| 2014 | 9,747,933 | 23.70% |

Timestamps are day-granular (midnight UTC), so no intra-day timing signal exists; burst detection operates at day resolution or coarser.

Baseline series written: **6,266 distinct days**. Busiest day carries **84,243** reviews. Every temporal feature de-trends against this series using `E[c] = n_p * daily_volume(d) / 41,135,700` and `z = (c - E) / sqrt(E)`.

## Duplicate text

| Key | Clusters | Reviews covered | Share | Largest cluster |
|---|---|---|---|---|
| Raw exact | 12,101 | 70,509 | 0.171% | 718 |
| Normalised (lowercased, whitespace-collapsed) | 26,354 | 106,373 | 0.259% | 1,526 |
| Normalised, >= 20 words | 17,196 | 34,625 | 0.084% | 17 |

> Exact duplication is rare here. Jindal & Liu (WSDM 2008) built their pseudo-labels from a much denser duplicate population; in this corpus duplicate seeds are a small, high-precision set, **not** the backbone of the score. Near-duplicate detection (Stage 6) carries the text signal.

## Helpfulness votes - and the power of the Stage 9 AUC study

- Reviews with at least one vote: **18,875,759** (45.9%)
- Total votes cast: **128,662,489**, of which helpful: **97,292,577** (75.6%)

| Cohort | Count |
|---|---|
| Reviewers with >= 50 total votes | 464,797 |
|   of which benign proxy (>= 0.75 helpful) | 277,607 |
|   of which suspicious proxy (<= 0.25 helpful) | 13,258 |

**Statistical power for V2: sufficient.** The minority class (13,258 reviewers) bounds what the held-out AUC study can claim.

> This is a *proxy*, not ground truth: helpful votes measure perceived usefulness and are themselves gameable. It is named as a proxy everywhere it is reported. No helpful-vote quantity enters the suspicion score - a unit test enforces this.
