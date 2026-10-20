import { api, ApiDown } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/ui/badge";
import { CorrelationHeatmap } from "@/components/charts/correlation-heatmap";
import { AgreementChart } from "@/components/charts/agreement-chart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

type Meta = {
  n_reviewers: number;
  candidate_features: string[];
  kept_features: string[];
  culled: { dropped: string; kept: string; spearman: number; active_rows: number }[];
  families: Record<string, string[]>;
  excluded_by_contract: string[];
  cull_threshold: number;
  agreement: Record<string, number>;
};

import { FAMILY, featureLabel } from "@/lib/labels";

const FAMILY_NAME: Record<string, string> = {
  T: FAMILY.T.name,
  B: FAMILY.B.name,
  G: FAMILY.G.name,
};

const SURVIVAL: [string, string, string][] = [
  [
    "Xie et al., KDD 2012 — singleton review bursts",
    "Dead",
    "The 5-core filter guarantees every reviewer has ≥5 reviews, so the target population is empty by construction. SpEagle's singleton indicator is identically 0 across all 41.1M rows.",
  ],
  [
    "Fei et al., ICWSM 2013 — burstiness + Markov random field",
    "Partial",
    "The burst detection and belief propagation survive. Their state prior is the verified-purchase ratio, which they call their strongest feature — and the 2014 release has no verified-purchase flag.",
  ],
  [
    "Lim et al., CIKM 2010 — target product groups",
    "Dead as published",
    "Their group-targeting score needs a product attribute to group by (brand, publisher). No product metadata is used here.",
  ],
  [
    "Jindal & Liu, WSDM 2008 — duplicate pseudo-labels",
    "Weak",
    "Implemented, but the seed set is thin: exact duplicates cover 0.26% of this corpus, far below the density their method assumes. Duplicates are a high-precision seed here, not a backbone.",
  ],
  [
    "Mukherjee et al., ICWSM 2013 — behavioural features",
    "Survives",
    "MNR (peak reviews per day), RL (review length), RD (rating deviation) are all implemented. PR (percentage positive) is deliberately excluded as a rating level.",
  ],
  [
    "Mukherjee et al., WWW 2012 — spammer groups",
    "Survives in spirit",
    "The group signal is implemented as dense, temporally-tight co-review components. GSRank's frequent-itemset mining is not: it duplicates a result the co-review join already gives.",
  ],
  [
    "He, Hollenbeck & Proserpio, PNAS 2022 — product co-review network",
    "Survives fully",
    "Needs nothing but (reviewerID, asin). The only construction in this literature validated against externally-sourced real Amazon ground truth.",
  ],
  [
    "Any neural / embedding text model",
    "Not attempted",
    "No GPU is available, the corpus spans 1996–2014 so LLM-generated text is structurally absent, and Mukherjee et al. measured linguistic features underperforming behavioural ones (67.8% vs 86%).",
  ],
];

export default async function Page() {
  let meta: Meta;
  let heat: {
    features: string[];
    families: Record<string, string>;
    matrix: (number | null)[][];
    active_rows: number[][];
    min_active: number;
  };
  let agree: {
    rows: Parameters<typeof AgreementChart>[0]["rows"];
    spearman: Record<string, number>;
  };
  try {
    [meta, heat, agree] = await Promise.all([
      api<Meta>("/meta"),
      api<typeof heat>("/charts/correlation"),
      api<typeof agree>("/charts/agreement"),
    ]);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    throw error;
  }

  const pairs = [
    ["spearman_TB", "Text ↔ Behaviour"],
    ["spearman_TG", "Text ↔ Graph"],
    ["spearman_BG", "Behaviour ↔ Graph"],
  ] as const;

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">How this works</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          What was measured, what was deliberately thrown away, how it was checked, and the
          things this data simply cannot answer. Written for someone who wants to argue with
          the method rather than take it on trust.
        </p>
      </section>

      <Card className="border-chart-4/50">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">What this is, and what it is not</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            This detects <strong className="text-foreground">coordinated and templated
            reviewing behaviour among established accounts</strong>. It is not bot detection
            and it is not fake-review detection, because this corpus cannot support those
            claims:
          </p>
          <ul className="ml-5 list-disc space-y-1">
            <li>
              The 5-core filter removed every singleton reviewer. Every account here has at
              least five reviews, which deletes the population most fake-review methods target.
            </li>
            <li>
              The 2014 release has no verified-purchase flag — the single strongest feature in
              several of the papers below.
            </li>
            <li>No product metadata is used, so there is no category-normalised baseline.</li>
            <li>
              Timestamps are day-granular, so nothing finer than a day of timing is observable.
            </li>
            <li>
              The corpus predates LLM-generated text entirely (1996–2014).
            </li>
            <li>
              <strong className="text-foreground">There are no labels.</strong> Nothing here
              establishes that any specific account is fraudulent.
            </li>
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">The score</CardTitle>
          <CardDescription>
            {meta.kept_features.length} features over {meta.n_reviewers.toLocaleString("en-US")}{" "}
            accounts, in three families that share no inputs.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5 text-sm">
          <div className="grid gap-4 sm:grid-cols-3">
            {Object.entries(meta.families).map(([key, features]) => (
              <div key={key} className="space-y-2 rounded-lg border p-3">
                <div className="text-xs font-medium uppercase tracking-wide">
                  {FAMILY_NAME[key]} ({features.length})
                </div>
                <div className="flex flex-wrap gap-1">
                  {features.map((f) => (
                    <Badge key={f} variant="secondary" className="text-[10px]" title={f}>
                      {featureLabel(f)}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="space-y-2 text-muted-foreground">
            <p>
              Each feature is transformed by its <strong className="text-foreground">empirical
              CDF</strong> before aggregation, so the score is invariant to units and to base
              rates. Families are combined by rank aggregation, not by a weighted sum of raw
              values.
            </p>
            <p>
              <strong className="text-foreground">Consensus vs any.</strong> The headline score
              is the mean of the three family ranks, so it is high only when several
              independent families agree — high precision, low recall. A second score takes the
              maximum instead, flagging anything one family finds extreme. Both are exposed
              because they answer different questions.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Feature correlation, after the cull</CardTitle>
          <CardDescription>
            Every surviving feature against every other. If the cull worked, nothing off the
            diagonal is dark.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CorrelationHeatmap
            features={heat.features}
            families={heat.families}
            matrix={heat.matrix}
            activeRows={heat.active_rows}
            minActive={heat.min_active}
            threshold={meta.cull_threshold}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Family agreement against a chance baseline</CardTitle>
          <CardDescription>
            Observed overlap versus what random ranking alone would produce.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AgreementChart rows={agree.rows} spearman={agree.spearman} />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Collinearity cull</CardTitle>
            <CardDescription>
              Dropped at |Spearman| &gt; {meta.cull_threshold}. Without this, &ldquo;writes a
              lot&rdquo; enters the score under several names and silently multiplies its own
              weight.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ul className="space-y-1.5">
              {meta.culled.map((c) => (
                <li key={c.dropped} className="flex flex-wrap items-baseline gap-2 text-xs">
                  <span className="text-destructive line-through" title={c.dropped}>
                    {featureLabel(c.dropped)}
                  </span>
                  <span className="text-muted-foreground">
                    was saying the same thing as
                  </span>
                  <span title={c.kept}>{featureLabel(c.kept)}</span>
                  <span className="tabular text-muted-foreground">
                    (ρ = {c.spearman.toFixed(3)})
                  </span>
                  <span className="tabular text-muted-foreground">
                    ({c.active_rows.toLocaleString("en-US")} active rows)
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              Correlation is measured on the <em>active subset</em> — rows where at least one of
              the pair is non-zero. Most graph and duplicate features are zero for over 99% of
              accounts, and a Spearman over that mass of ties returns 1.000 for any two sparse
              features, which would cull genuinely different signals.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Do the families agree?</CardTitle>
            <CardDescription>
              The families share no inputs, so agreement between them is evidence rather than
              circularity. The honest answer is: somewhat.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ul className="space-y-1 text-xs">
              {pairs.map(([key, label]) => (
                <li key={key} className="flex items-baseline justify-between gap-3 border-b py-1">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="tabular">{meta.agreement[key]?.toFixed(4)}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              Rank correlations between families are low (0.03&ndash;0.16), which means they are
              largely detecting <em>different</em> accounts. Where they do overlap, they overlap
              well above chance: in the top 100,000, all three families agree on{" "}
              {meta.agreement["overlap_TBG_at_100000"]?.toLocaleString("en-US")} accounts against a
              chance expectation of{" "}
              {meta.agreement["overlap_TBG_at_100000_expected"]?.toLocaleString("en-US")} — roughly a
              sevenfold lift. At the very top (k = 1,000) the chance expectation is below one
              account, so the observed overlap carries no information either way, and it is
              reported as such rather than dressed up.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Which published methods survive this corpus</CardTitle>
          <CardDescription>
            A third of the canonical opinion-spam literature is unimplementable here, and it is
            better to say which and why than to imply full coverage.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {SURVIVAL.map(([name, verdict, why]) => (
            <div key={name} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b pb-3 text-sm last:border-0">
              <span className="font-medium">{name}</span>
              <Badge
                variant={
                  verdict.startsWith("Survives") ? "secondary" : "outline"
                }
                className="text-[10px]"
              >
                {verdict}
              </Badge>
              <span className="w-full text-xs text-muted-foreground">{why}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Excluded from the score by contract</CardTitle>
          <CardDescription>
            Enforced by unit tests, not by discipline.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <div className="flex flex-wrap gap-1">
            {meta.excluded_by_contract.map((f) => (
              <Badge key={f} variant="outline" className="font-mono text-[10px]">
                {f}
              </Badge>
            ))}
          </div>
          <ul className="ml-5 list-disc space-y-1 text-xs">
            <li>
              <strong className="text-foreground">Rating levels</strong> (mean rating, % 5-star,
              % extreme). The corpus is 59.21% five-star, so a level feature flags three fifths
              of the population. Ratings enter only as a deviation from the product&rsquo;s own
              consensus, or as a within-account distribution shape.
            </li>
            <li>
              <strong className="text-foreground">Helpful votes.</strong> These are the
              validation proxy. Scoring on them and then validating against them would produce
              an impressive AUC that means nothing.
            </li>
            <li>
              <strong className="text-foreground">Raw review volume.</strong> Writing a lot is
              not suspicious, and volume correlates with nearly every other feature.
            </li>
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">How search works</CardTitle>
          <CardDescription>
            The other half of this project: finding a review among 41 million, and the
            fact that the people being searched for are actively gaming the ranking.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Scanning the review text for a phrase takes{" "}
            <strong className="text-foreground">128 seconds</strong> — it reads all 9.7 GB.
            So the text is inverted once, in advance, into a list of which words appear in
            which reviews:{" "}
            <strong className="text-foreground">1,866,565,578</strong> entries over{" "}
            <strong className="text-foreground">4,584,763</strong> distinct word stems.
            Words are lowercased, 70 stopwords are dropped, and the rest are reduced to
            their stem, so <span className="font-mono text-foreground">charging</span>,{" "}
            <span className="font-mono text-foreground">charged</span> and{" "}
            <span className="font-mono text-foreground">charges</span> all become{" "}
            <span className="font-mono text-foreground">charg</span> and match each other.
          </p>
          <p>
            <strong className="text-foreground">Ranking is BM25.</strong> A review scores
            highly when it uses a query word often, when that word is rare across the
            corpus, and when the review is short enough that the word carries weight — a
            mention in twenty words means more than the same mention in two thousand. The
            length correction is computed at build time and stored with each entry, which
            is why a search does not have to consult 41.1 million document lengths to
            answer.
          </p>
          <p>
            <strong className="text-foreground">Then a neural model re-reads the top 50.</strong>{" "}
            BM25 only counts word overlap; a cross-encoder reads the query and the review
            together and judges whether one actually answers the other. Running it over the
            whole corpus would take days on this machine, so it re-orders a shortlist
            instead — which is how production search engines are built, not a shortcut.
          </p>
          <p>
            <strong className="text-foreground">And the results know about the spam
            analysis.</strong> Every hit carries its author&rsquo;s suspicion score, group
            membership and reused-text cluster, and the demote toggle multiplies relevance
            by how independent the author looks. Ranking documents when some of the authors
            are trying to manipulate the ranking is its own problem, and this is the one
            place where both halves of the project are in the same query.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
