import Link from "next/link";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Stat } from "@/components/stat";
import { HowItWorks } from "@/components/how-it-works";
import { ScoreExplorer } from "@/components/score-explorer";
import { RatingDonut } from "@/components/charts/rating-donut";
import { VolumeChart } from "@/components/charts/volume-chart";
import { DecileChart } from "@/components/charts/decile-chart";
import { FamilyVenn } from "@/components/charts/family-venn";
import { RingConvergence } from "@/components/charts/ring-convergence";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

type Overview = {
  corpus: {
    n_reviews: number; n_reviewers: number; n_products: number;
    first_day: number; last_day: number;
  };
  ratings: { rating: number; n: number }[];
  histogram: { family: string; bin_lo: number; bin_hi: number; n: number }[];
  clusters: Record<string, number>;
};

type Highlights = {
  ring: {
    ring_id: number; n_members: number; n_products: number; n_reviews: number;
    density: number; mean_shared: number; span_days: number; mean_rating: number;
  } | null;
  cluster: {
    cluster_id: number; config: string; n_reviewers: number; n_reviews: number;
    n_products: number; mean_jaccard: number; span_days: number; mean_rating: number;
    sample_text: string | null; sample_summary: string | null;
  } | null;
  burst: {
    reviewer_sk: number; reviewerID: string; reviewer_name: string | null;
    score: number; n_reviews: number; max_per_day: number; mean_rating: number;
  } | null;
  totals: Record<string, number>;
};

export default async function Page() {
  let data: Overview;
  let high: Highlights;
  let volume: { series: Parameters<typeof VolumeChart>[0]["series"] };
  let deciles: { deciles: Parameters<typeof DecileChart>[0]["deciles"] };
  let venn: { k: number; union: number; segments: Parameters<typeof FamilyVenn>[0]["segments"] };
  try {
    [data, high, volume, deciles, venn] = await Promise.all([
      api<Overview>("/overview"),
      api<Highlights>("/charts/highlights"),
      api<typeof volume>("/charts/volume", { bucket: 60 }),
      api<typeof deciles>("/charts/rating-by-decile"),
      api<typeof venn>("/charts/family-composition", { k: 10000 }),
    ]);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    throw error;
  }

  const { corpus, ratings, histogram, clusters } = data;
  const t = high.totals ?? {};
  const total = ratings.reduce((a, r) => a + r.n, 0);

  let convergence: {
    products: Parameters<typeof RingConvergence>[0]["products"];
    reviews: Parameters<typeof RingConvergence>[0]["reviews"];
    members: Parameters<typeof RingConvergence>[0]["members"];
  } | null = null;
  if (high.ring) {
    try {
      convergence = await api(`/rings/${high.ring.ring_id}/convergence`);
    } catch {
      convergence = null;
    }
  }

  return (
    <div className="space-y-12">
      {/* ------------------------------------------------ what is this ---- */}
      <section className="space-y-4">
        <Badge variant="secondary" className="text-xs">
          {num(corpus.n_reviews)} Amazon reviews &middot;{" "}
          {dayToDate(corpus.first_day).slice(0, 4)}&ndash;
          {dayToDate(corpus.last_day).slice(0, 4)}
        </Badge>
        <h1 className="max-w-4xl text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
          Which of these reviews were written by people working together?
        </h1>
        <div className="max-w-3xl space-y-3 text-[15px] leading-relaxed text-muted-foreground">
          <p>
            This is every review Amazon published between 1996 and 2014 that survived a
            basic activity filter &mdash; {num(corpus.n_reviews)} of them, from{" "}
            {num(corpus.n_reviewers)} accounts, covering {num(corpus.n_products)} products.
            Not one of them is labelled. Nobody has said which are genuine.
          </p>
          <p>
            So the question can&rsquo;t be &ldquo;which reviews are fake&rdquo;. It has to be
            something the data can actually answer:{" "}
            <strong className="text-foreground">
              which accounts behave as though they are not acting independently?
            </strong>{" "}
            Three separate checks run over every account, and the ones where those checks
            agree are what this dashboard shows you.
          </p>
        </div>
      </section>

      {/* ------------------------------------------------- headline finds -- */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          {
            value: num(t.rings ?? clusters.rings),
            label: "groups of accounts found reviewing together",
            sub: `${num(t.ring_accounts)} accounts, ${num(t.perfect_rings)} of the groups completely interlinked`,
            href: "/rings",
          },
          {
            value: num(t.copy_groups),
            label: "cases of the same review text on different accounts",
            sub: "verified word-by-word, not estimated",
            href: "/duplicates",
          },
          {
            value: num(t.top_consensus),
            label: "accounts flagged by more than one check at once",
            sub: `out of ${num(corpus.n_reviewers)} — the strongest evidence here`,
            href: "/reviewers?min_score=0.99",
          },
          {
            value: num(t.top_any),
            label: "accounts flagged by at least one check",
            sub: "a wider net, and weaker evidence per account",
            href: "/reviewers",
          },
        ].map((card) => (
          <Link key={card.label} href={card.href} className="group">
            <Card className="h-full transition-colors group-hover:border-foreground/25">
              <CardContent className="space-y-1 pt-6">
                <div className="tabular text-3xl font-semibold leading-none">{card.value}</div>
                <div className="text-sm font-medium">{card.label}</div>
                <div className="text-xs text-muted-foreground">{card.sub}</div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </section>

      {/* ------------------------------------------------- how it works ---- */}
      <section className="space-y-4">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">
            What counts as suspicious here
          </h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Three checks, each looking at something completely different.
          </p>
        </div>
        <HowItWorks
          examples={{
            T: high.cluster ? (
              <>
                {high.cluster.n_reviewers} accounts posted the same review across{" "}
                {high.cluster.n_products} different products &mdash;{" "}
                {(high.cluster.mean_jaccard * 100).toFixed(0)}% identical wording, average
                rating {high.cluster.mean_rating.toFixed(1)}&#9733;.{" "}
                <Link
                  href={`/duplicates/${high.cluster.config}/${high.cluster.cluster_id}`}
                  className="underline underline-offset-2"
                >
                  Read them side by side
                </Link>
                .
              </>
            ) : null,
            B: high.burst ? (
              <>
                One account posted all {num(high.burst.n_reviews)} of its reviews on a
                single day, averaging {high.burst.mean_rating.toFixed(1)}&#9733;, and was
                never seen again.{" "}
                <Link
                  href={`/reviewers/${high.burst.reviewer_sk}`}
                  className="underline underline-offset-2"
                >
                  See its timeline
                </Link>
                .
              </>
            ) : null,
            G: high.ring ? (
              <>
                {high.ring.n_members} accounts reviewed the same {high.ring.n_products}{" "}
                products inside {num(high.ring.span_days)} days, every rating{" "}
                {high.ring.mean_rating.toFixed(1)}&#9733;.{" "}
                <Link
                  href={`/rings/${high.ring.ring_id}`}
                  className="underline underline-offset-2"
                >
                  See the group
                </Link>
                .
              </>
            ) : null,
          }}
        />
      </section>

      {/* ------------------------------------------- the clearest example -- */}
      {high.ring && convergence && convergence.products.length > 0 && (
        <section className="space-y-4">
          <div className="space-y-1">
            <h2 className="text-xl font-semibold tracking-tight">
              The clearest case in the data
            </h2>
            <p className="max-w-3xl text-sm text-muted-foreground">
              Each row is a product. Each dot is one review by one member of this group of{" "}
              {high.ring.n_members} accounts. Time runs left to right.{" "}
              <strong className="text-foreground">
                Independent shoppers scatter across a row; these arrive together.
              </strong>
            </p>
          </div>
          <Card>
            <CardContent className="pt-6">
              <RingConvergence
                products={convergence.products}
                reviews={convergence.reviews}
                members={convergence.members}
              />
              <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-1 border-t pt-4 text-xs text-muted-foreground">
                <span>
                  <span className="tabular font-medium text-foreground">
                    {high.ring.n_members}
                  </span>{" "}
                  accounts
                </span>
                <span>
                  <span className="tabular font-medium text-foreground">
                    {high.ring.mean_shared.toFixed(1)}
                  </span>{" "}
                  products in common per pair
                </span>
                <span>
                  all activity inside{" "}
                  <span className="tabular font-medium text-foreground">
                    {num(high.ring.span_days)}
                  </span>{" "}
                  days
                </span>
                <span>
                  average rating{" "}
                  <span className="tabular font-medium text-foreground">
                    {high.ring.mean_rating.toFixed(2)}
                  </span>
                  &#9733;
                </span>
                <Link
                  href={`/rings/${high.ring.ring_id}`}
                  className="ml-auto underline underline-offset-4"
                >
                  Open this group &rarr;
                </Link>
              </div>
            </CardContent>
          </Card>
        </section>
      )}

      {/* --------------------------------------------------- the numbers --- */}
      <section className="space-y-4">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">What the whole corpus looks like</h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Context for the numbers above, and the two checks that keep the method honest.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              Almost all of these reviews were written recently
            </CardTitle>
            <CardDescription>
              2013 alone accounts for 14.8 million of the 41.1 million. That matters: a
              &ldquo;sudden spike of reviews&rdquo; in 2013 is normal, and the same spike in
              2003 would be extraordinary. Every timing measurement here is adjusted against
              this curve, or it would just be re-detecting the year 2013.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <VolumeChart series={volume.series} />
          </CardContent>
        </Card>

        <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">How suspicious is everybody?</CardTitle>
              <CardDescription>
                Every one of the {num(corpus.n_reviewers)} accounts, scored 0 to 1. Drag the
                line to pick a cut-off and see how many sit above it. Almost nobody scores
                high, which is the point &mdash; a score only climbs when several independent
                checks agree.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ScoreExplorer histogram={histogram} totalReviewers={corpus.n_reviewers} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Almost everyone gives five stars</CardTitle>
              <CardDescription>
                {(((ratings.find((r) => r.rating === 5)?.n ?? 0) / total) * 100).toFixed(0)}% of
                all reviews are 5&#9733;.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <RatingDonut
                ratings={ratings}
                caption={
                  <>
                    This is why &ldquo;posts lots of glowing reviews&rdquo; is useless on its
                    own &mdash; it describes three fifths of everyone on Amazon. So a high
                    rating never counts against an account here. What counts is{" "}
                    <em>disagreeing with everyone else who reviewed the same product</em>.
                  </>
                }
              />
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Does the score actually mean anything?</CardTitle>
              <CardDescription>
                A fair test: ratings were never shown to the scoring system, so if flagged
                accounts rate differently that is something it discovered, not something it
                was told.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <DecileChart deciles={deciles.deciles} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Do the three checks find the same people?</CardTitle>
              <CardDescription>
                Mostly not &mdash; and that is worth knowing rather than hiding.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <FamilyVenn segments={venn.segments} k={venn.k} union={venn.union} />
            </CardContent>
          </Card>
        </div>
      </section>

      {/* ------------------------------------------------------- explore --- */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">Look around</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              href: "/rings",
              title: "Groups",
              body: "Sets of accounts that keep reviewing the same products within days of each other. Start here — it is the most convincing thing in the data.",
            },
            {
              href: "/duplicates",
              title: "Copied reviews",
              body: "The same words posted by different accounts, shown side by side so you can judge for yourself.",
            },
            {
              href: "/reviewers",
              title: "Accounts",
              body: "Every account, ranked, with a plain-language breakdown of what made each one look unusual.",
            },
            {
              href: "/network",
              title: "The network",
              body: "The most suspicious 1% of accounts, drawn as a map. It splits into two very different shapes, and their own reviews say why.",
            },
            {
              href: "/methodology",
              title: "How it was built",
              body: "The method, what was thrown away and why, and an honest list of what this data cannot tell us.",
            },
          ].map((card) => (
            <Link key={card.href} href={card.href} className="group">
              <Card className="h-full transition-colors group-hover:border-foreground/25">
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">{card.title}</CardTitle>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">{card.body}</CardContent>
              </Card>
            </Link>
          ))}
        </div>
      </section>

      <section className="rounded-lg border-l-2 border-chart-4 bg-muted/40 px-5 py-4">
        <h2 className="mb-2 text-sm font-semibold">Before you draw conclusions</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          A high score means an account behaves unusually along axes that research has linked
          to coordinated reviewing. It is <strong className="text-foreground">not</strong> proof
          that anyone was paid, and this data contains no answer key to check against. Some of
          the tightest groups here are probably book clubs and hobbyist forums rather than
          review farms &mdash; the data cannot tell those apart, and neither can this tool.{" "}
          <Link href="/methodology" className="underline underline-offset-4">
            The full list of caveats
          </Link>{" "}
          is worth reading before quoting any number from this page.
        </p>
      </section>
    </div>
  );
}
