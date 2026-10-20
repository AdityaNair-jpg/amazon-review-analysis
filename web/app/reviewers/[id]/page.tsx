import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Stat } from "@/components/stat";
import { ContributionBars } from "@/components/contribution-bars";
import { FamilyRadar } from "@/components/charts/family-radar";
import { ActivityTimeline } from "@/components/charts/activity-timeline";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export const dynamic = "force-dynamic";

type Detail = {
  profile: Record<string, number | string | null>;
  features: Record<string, number | null>;
  contributions: { feature: string; percentile: number; family: string }[];
  recent_reviews: {
    review_sk: number;
    day: number;
    rating: number;
    n_words: number;
    helpful_yes: number;
    helpful_total: number;
    asin: string;
    snippet: string;
    summary: string;
  }[];
};

const FAMILY_LABEL: Record<string, string> = {
  T: "Text",
  B: "Behaviour",
  G: "Graph",
};

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let data: Detail;
  let timeline: { points: Parameters<typeof ActivityTimeline>[0]["points"] };
  try {
    [data, timeline] = await Promise.all([
      api<Detail>(`/reviewers/${id}`),
      api<typeof timeline>(`/reviewers/${id}/timeline`),
    ]);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    if (error instanceof Error && error.message.includes("not found")) notFound();
    throw error;
  }

  const p = data.profile as Record<string, number & string>;
  const f = data.features ?? {};

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Link
          href="/reviewers"
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          &larr; All reviewers
        </Link>
        <h1 className="font-mono text-2xl font-semibold tracking-tight">{p.reviewerID}</h1>
        <p className="text-sm text-muted-foreground">
          {(p.reviewer_name as unknown as string) ?? "(no display name)"}
          {Number(p.ring_size) > 0 && (
            <>
              {" · "}
              <Link href={`/rings/${p.ring_id}`} className="underline underline-offset-4">
                member of a {num(Number(p.ring_size))}-account ring
              </Link>
            </>
          )}
        </p>
      </div>

      <Card>
        <CardContent className="grid grid-cols-2 gap-6 pt-6 sm:grid-cols-4 lg:grid-cols-8">
          <Stat
            label="Suspicion"
            value={Number(p.score).toFixed(3)}
            sub="0 = ordinary, 1 = extreme"
          />
          <Stat label="Copying" value={Number(p.score_text).toFixed(3)} sub="reuses text" />
          <Stat
            label="Activity"
            value={Number(p.score_behaviour).toFixed(3)}
            sub="bursts, odd ratings"
          />
          <Stat
            label="Pack"
            value={Number(p.score_graph).toFixed(3)}
            sub="reviews with others"
          />
          <Stat label="Reviews written" value={num(Number(p.n_reviews))} />
          <Stat label="Busiest day" value={num(Number(p.max_per_day))} sub="reviews in 24h" />
          <Stat
            label="Account life"
            value={`${num(Number(p.lifespan_days))} days`}
            sub={`${dayToDate(Number(p.first_day))} → ${dayToDate(Number(p.last_day))}`}
          />
          <Stat label="Average rating" value={Number(p.mean_rating).toFixed(2)} />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Reviewing history</CardTitle>
            <CardDescription>
              Every dated review this account wrote, on one timeline.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ActivityTimeline points={timeline.points} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Which checks fired</CardTitle>
            <CardDescription>
              A lopsided spike means only one check found something. A full triangle means all
              three did, independently &mdash; which is much harder to explain innocently.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FamilyRadar
              text={Number(p.score_text)}
              behaviour={Number(p.score_behaviour)}
              graph={Number(p.score_graph)}
            />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Why this account was flagged</CardTitle>
            <CardDescription>
              Each bar shows how extreme this account is on one measurement, compared with all
              3,035,045 accounts. The longest bars are what pushed its score up.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ContributionBars contributions={data.contributions} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">The underlying numbers</CardTitle>
            <CardDescription>
              Every measurement taken for this account, unprocessed. These are the internal
              names used in the pipeline code, kept so a number can be traced back to where
              it came from.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
              {Object.entries(f)
                .filter(([k]) => k !== "reviewer_sk")
                .map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between gap-3 border-b py-1">
                    <dt className="truncate text-muted-foreground">{k}</dt>
                    <dd className="tabular shrink-0">
                      {typeof v === "number"
                        ? Number.isInteger(v) ? num(v) : v.toFixed(4)
                        : "—"}
                    </dd>
                  </div>
                ))}
            </dl>
          </CardContent>
        </Card>
      </div>

      <Card className="overflow-hidden py-0">
        <CardHeader className="px-6 pb-2 pt-6">
          <CardTitle className="text-base">Most recent reviews</CardTitle>
          <CardDescription>
            Text is fetched from the raw archive on demand; it is never scanned for list views.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-28">Date</TableHead>
                <TableHead className="w-28">Product</TableHead>
                <TableHead className="w-14 text-right">Stars</TableHead>
                <TableHead className="w-16 text-right">Words</TableHead>
                <TableHead className="w-20 text-right">Helpful</TableHead>
                <TableHead>Review</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.recent_reviews.map((r) => (
                <TableRow key={r.review_sk}>
                  <TableCell className="tabular text-xs">{dayToDate(r.day)}</TableCell>
                  <TableCell className="font-mono text-xs">{r.asin}</TableCell>
                  <TableCell className="text-right tabular text-xs">{r.rating}★</TableCell>
                  <TableCell className="text-right tabular text-xs">{num(r.n_words)}</TableCell>
                  <TableCell className="text-right tabular text-xs text-muted-foreground">
                    {r.helpful_total > 0 ? `${r.helpful_yes}/${r.helpful_total}` : "—"}
                  </TableCell>
                  <TableCell className="text-xs">
                    <span className="font-medium">{r.summary}</span>
                    <span className="block text-muted-foreground">{r.snippet}…</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="rounded-lg border-l-2 border-chart-4 bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
        A high score means this account behaves unusually along measurements that research has
        linked to coordinated reviewing. It is <strong className="text-foreground">not</strong>{" "}
        evidence that this person did anything wrong. Prolific hobbyists, early adopters and
        members of enthusiast communities all produce some of these patterns honestly.
      </p>
    </div>
  );
}
