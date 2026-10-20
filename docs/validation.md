# Validation

No ground truth exists in this corpus. Every number here is against a named proxy or against data we planted ourselves, and each section says which.

## V1 - cross-family check (is the score circular?)

Text features used: `self_dup_rate`, `summary_reuse_rate`, `summary_is_text_rate`, `exact_dup_rate`, `neardup_rate`, `neardup_max_cluster`, `mean_words`, `words_cv`, `exclaim_rate`, `upper_rate`

Trained on 120,000 reviewers (59,906 top-decile by B+G, 60,094 bottom-decile).

- Text-only accuracy: **0.721** (+/- 0.002), chance = 0.500 on balanced classes
- Text-only ROC AUC: **0.805** (+/- 0.003)

> Text features share no input with behaviour or graph, so this is not the score predicting itself. Fei et al. (ICWSM 2013) report 71.2-77.6% on a comparable behavioural/linguistic split.

**Reading:** the three families are detecting a common underlying phenomenon.

## V2 - held-out helpful-vote proxy

Cohort: **290,865** reviewers with >= 50 total votes (**13,258** suspicious-proxy, **277,607** benign-proxy).

| Ranking | ROC AUC | Average precision |
|---|---|---|
| combined score | 0.5619 | 0.0526 |
| text (T) | 0.6583 | 0.0783 |
| behaviour (B) | 0.5414 | 0.0622 |
| graph (G) | 0.4269 | 0.0364 |

Base rate of the suspicious-proxy class: 0.0456 (that is the AP a random ranking would get).

> **This is a proxy, not ground truth.** Helpful votes measure perceived usefulness and are themselves gameable. It is reported because it is the labelling rule the REV2 and CARE-GNN Amazon benchmarks use, and because no helpful-vote quantity enters the score -- so the comparison is at least not circular.

## V4 - synthetic injection (the only real recall number)

> **These numbers describe the detector BEFORE the fix they caused.** The run below
> is what exposed the `>=20 reviews` eligibility floor on the co-review graph: of
> 2,400 planted accounts holding fewer than 20 reviews, zero were even eligible to
> be seen, while 1,015-1,200 of the 1,200 that cleared the floor were correctly
> placed in a ring. The floor has since been removed (the graph went from 311,005
> to 1,038,862 reviewers and from 314 to 1,381 rings), and these figures have not
> been regenerated against the fixed detector. Re-run with
> `python pipeline/run_injection.py` (~25 min) to refresh them. See
> `docs/findings.md` section 6.


Population: **3,039,845** accounts, of which **4,800** are planted (0.158%).

### Overall recall@k

| k | planted in top-k | recall | lift over chance |
|---|---|---|---|
| 1,000 | 0 | 0.0000 | 0.0x |
| 5,000 | 2 | 0.0004 | 0.3x |
| 10,000 | 6 | 0.0013 | 0.4x |
| 50,000 | 251 | 0.0523 | 3.2x |
| 100,000 | 572 | 0.1192 | 3.6x |

Median rank of a planted account: **632,368** of 3,039,845 (top 20.80%).

### Recall@10,000 per grid cell

Never averaged: the cells the detector misses are the informative ones.

| G | P | W | rho | camouflage | planted | recall@10k | recall@50k | median rank |
|---|---|---|---|---|---|---|---|---|
| 25 | 8 | 7 | 1.0 | yes | 125 | 0.040 | 0.400 | 57,771 |
| 25 | 8 | 7 | 0.6 | yes | 125 | 0.008 | 0.464 | 52,161 |
| 5 | 3 | 7 | 0.0 | yes | 25 | 0.000 | 0.000 | 351,611 |
| 5 | 3 | 7 | 0.0 | no | 25 | 0.000 | 0.000 | 1,854,281 |
| 5 | 3 | 7 | 0.6 | yes | 25 | 0.000 | 0.000 | 272,044 |
| 5 | 3 | 7 | 0.6 | no | 25 | 0.000 | 0.000 | 1,777,494 |
| 5 | 3 | 7 | 1.0 | yes | 25 | 0.000 | 0.000 | 299,107 |
| 5 | 3 | 7 | 1.0 | no | 25 | 0.000 | 0.000 | 1,793,386 |
| 5 | 3 | 30 | 0.0 | no | 25 | 0.000 | 0.000 | 2,058,195 |
| 5 | 3 | 30 | 0.0 | yes | 25 | 0.000 | 0.000 | 440,958 |
| 5 | 3 | 30 | 0.6 | yes | 25 | 0.000 | 0.000 | 433,939 |
| 5 | 3 | 30 | 0.6 | no | 25 | 0.000 | 0.000 | 1,960,787 |
| 5 | 3 | 30 | 1.0 | yes | 25 | 0.000 | 0.000 | 270,298 |
| 5 | 3 | 30 | 1.0 | no | 25 | 0.000 | 0.000 | 1,794,635 |
| 5 | 8 | 7 | 0.0 | no | 25 | 0.000 | 0.000 | 891,943 |
| 5 | 8 | 7 | 0.0 | yes | 25 | 0.000 | 0.120 | 119,261 |
| 5 | 8 | 7 | 0.6 | yes | 25 | 0.000 | 0.560 | 45,623 |
| 5 | 8 | 7 | 0.6 | no | 25 | 0.000 | 0.000 | 653,031 |
| 5 | 8 | 7 | 1.0 | no | 25 | 0.000 | 0.000 | 735,306 |
| 5 | 8 | 7 | 1.0 | yes | 25 | 0.000 | 0.560 | 45,098 |
| 5 | 8 | 30 | 0.0 | yes | 25 | 0.000 | 0.040 | 243,500 |
| 5 | 8 | 30 | 0.0 | no | 25 | 0.000 | 0.000 | 1,616,730 |
| 5 | 8 | 30 | 0.6 | yes | 25 | 0.000 | 0.040 | 123,983 |
| 5 | 8 | 30 | 0.6 | no | 25 | 0.000 | 0.000 | 1,238,815 |
| 5 | 8 | 30 | 1.0 | no | 25 | 0.000 | 0.000 | 1,072,308 |
| 5 | 8 | 30 | 1.0 | yes | 25 | 0.000 | 0.120 | 152,128 |
| 10 | 3 | 7 | 0.0 | yes | 50 | 0.000 | 0.000 | 412,258 |
| 10 | 3 | 7 | 0.0 | no | 50 | 0.000 | 0.000 | 1,992,946 |
| 10 | 3 | 7 | 0.6 | yes | 50 | 0.000 | 0.000 | 266,446 |
| 10 | 3 | 7 | 0.6 | no | 50 | 0.000 | 0.000 | 1,907,086 |
| 10 | 3 | 7 | 1.0 | yes | 50 | 0.000 | 0.000 | 271,988 |
| 10 | 3 | 7 | 1.0 | no | 50 | 0.000 | 0.000 | 1,650,250 |
| 10 | 3 | 30 | 0.0 | yes | 50 | 0.000 | 0.000 | 488,488 |
| 10 | 3 | 30 | 0.0 | no | 50 | 0.000 | 0.000 | 2,024,246 |
| 10 | 3 | 30 | 0.6 | yes | 50 | 0.000 | 0.000 | 401,498 |
| 10 | 3 | 30 | 0.6 | no | 50 | 0.000 | 0.000 | 1,896,228 |
| 10 | 3 | 30 | 1.0 | yes | 50 | 0.000 | 0.000 | 409,251 |
| 10 | 3 | 30 | 1.0 | no | 50 | 0.000 | 0.000 | 1,807,816 |
| 10 | 8 | 7 | 0.0 | no | 50 | 0.000 | 0.000 | 898,296 |
| 10 | 8 | 7 | 0.0 | yes | 50 | 0.000 | 0.180 | 95,418 |
| 10 | 8 | 7 | 0.6 | yes | 50 | 0.000 | 0.480 | 52,323 |
| 10 | 8 | 7 | 0.6 | no | 50 | 0.000 | 0.000 | 807,011 |
| 10 | 8 | 7 | 1.0 | yes | 50 | 0.000 | 0.480 | 53,905 |
| 10 | 8 | 7 | 1.0 | no | 50 | 0.000 | 0.000 | 754,055 |
| 10 | 8 | 30 | 0.0 | yes | 50 | 0.000 | 0.040 | 208,885 |
| 10 | 8 | 30 | 0.0 | no | 50 | 0.000 | 0.000 | 1,334,884 |
| 10 | 8 | 30 | 0.6 | yes | 50 | 0.000 | 0.040 | 143,643 |
| 10 | 8 | 30 | 0.6 | no | 50 | 0.000 | 0.000 | 1,452,601 |
| 10 | 8 | 30 | 1.0 | no | 50 | 0.000 | 0.000 | 1,195,262 |
| 10 | 8 | 30 | 1.0 | yes | 50 | 0.000 | 0.080 | 164,579 |
| 25 | 3 | 7 | 0.0 | no | 125 | 0.000 | 0.000 | 1,991,204 |
| 25 | 3 | 7 | 0.0 | yes | 125 | 0.000 | 0.008 | 351,116 |
| 25 | 3 | 7 | 0.6 | yes | 125 | 0.000 | 0.000 | 327,205 |
| 25 | 3 | 7 | 0.6 | no | 125 | 0.000 | 0.000 | 1,812,710 |
| 25 | 3 | 7 | 1.0 | no | 125 | 0.000 | 0.000 | 1,689,141 |
| 25 | 3 | 7 | 1.0 | yes | 125 | 0.000 | 0.000 | 311,893 |
| 25 | 3 | 30 | 0.0 | no | 125 | 0.000 | 0.000 | 2,139,447 |
| 25 | 3 | 30 | 0.0 | yes | 125 | 0.000 | 0.000 | 525,242 |
| 25 | 3 | 30 | 0.6 | no | 125 | 0.000 | 0.000 | 1,991,054 |
| 25 | 3 | 30 | 0.6 | yes | 125 | 0.000 | 0.000 | 435,496 |
| 25 | 3 | 30 | 1.0 | yes | 125 | 0.000 | 0.000 | 389,392 |
| 25 | 3 | 30 | 1.0 | no | 125 | 0.000 | 0.000 | 1,840,776 |
| 25 | 8 | 7 | 0.0 | no | 125 | 0.000 | 0.008 | 1,007,323 |
| 25 | 8 | 7 | 0.0 | yes | 125 | 0.000 | 0.200 | 106,439 |
| 25 | 8 | 7 | 0.6 | no | 125 | 0.000 | 0.000 | 813,768 |
| 25 | 8 | 7 | 1.0 | no | 125 | 0.000 | 0.000 | 953,042 |
| 25 | 8 | 30 | 0.0 | yes | 125 | 0.000 | 0.016 | 252,105 |
| 25 | 8 | 30 | 0.0 | no | 125 | 0.000 | 0.000 | 1,594,132 |
| 25 | 8 | 30 | 0.6 | yes | 125 | 0.000 | 0.048 | 162,445 |
| 25 | 8 | 30 | 0.6 | no | 125 | 0.000 | 0.000 | 1,301,741 |
| 25 | 8 | 30 | 1.0 | yes | 125 | 0.000 | 0.056 | 140,247 |
| 25 | 8 | 30 | 1.0 | no | 125 | 0.000 | 0.000 | 1,214,524 |

**Best cell:** `G25_P8_W7_rho1.0_cam` at recall@10k = 0.040. **Worst cell:** `G10_P8_W7_rho0.6_bare` at 0.000.

> Read the worst cell as the honest headline: it is the campaign shape this pipeline does not catch, and it bounds what the score can be trusted to find.

## What none of this establishes

- No real review in this corpus is labelled. The ranking identifies accounts whose behaviour is statistically unusual along three independent axes; it does not establish that any particular account is fraudulent.

- The 5-core filter removed every singleton reviewer, the 2014 release carries no verified-purchase flag, and no product metadata is used. Methods that depend on those are not merely unimplemented here, they are unimplementable.

- V2 is a proxy. V1 tests internal consistency, not correctness. V4 measures recall on campaigns matching the shapes we chose to generate, so it bounds performance on those shapes and says nothing about shapes outside the grid.
