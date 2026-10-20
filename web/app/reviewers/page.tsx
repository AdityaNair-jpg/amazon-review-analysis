import Link from "next/link";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { ScoreBar } from "@/components/score-bar";
import { ReviewerFilters } from "@/components/reviewer-filters";
import { Pager } from "@/components/pager";
import { ReviewerScatter } from "@/components/charts/reviewer-scatter";
import { Badge } from "@/components/ui/badge";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export const dynamic = "force-dynamic";

type Row = {
  reviewer_sk: number;
  reviewerID: string;
  reviewer_name: string | null;
  score: number;
  score_text: number;
  score_behaviour: number;
  score_graph: number;
  n_reviews: number;
  max_per_day: number;
  lifespan_days: number;
  mean_rating: number;
  ring_id: number;
  ring_size: number;
  first_day: number;
  last_day: number;
};

type Response = { total: number; limit: number; offset: number; items: Row[] };

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const params = {
    limit: Number(sp.limit ?? 50),
    offset: Number(sp.offset ?? 0),
    sort: sp.sort ?? "score",
    dir: sp.dir ?? "desc",
    min_score: sp.min_score ?? 0,
    min_reviews: sp.min_reviews ?? 0,
    in_ring: sp.in_ring,
    q: sp.q,
  };

  let data: Response;
  let scatter: { points: Parameters<typeof ReviewerScatter>[0]["points"] };
  try {
    [data, scatter] = await Promise.all([
      api<Response>("/reviewers", params),
      api<typeof scatter>("/charts/reviewer-scatter"),
    ]);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    throw error;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Accounts</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Every account that wrote reviews in this corpus, ranked by how unusual its
          behaviour is. <strong className="text-foreground">Suspicion</strong> only climbs
          when more than one of the three checks agrees, so the three columns beside it
          &mdash; copying, activity and pack behaviour &mdash; show you <em>which</em> check
          fired. {num(data.total)} accounts match the current filters.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Where the flagged accounts sit</CardTitle>
          <CardDescription>
            Every dot is an account. Red dots are the suspicious ones &mdash; note that they
            cluster in a corner rather than mixing in with everybody else. Click any dot to
            open it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ReviewerScatter points={scatter.points} />
        </CardContent>
      </Card>

      <ReviewerFilters />

      <Card className="overflow-hidden py-0">
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[22%]">Account</TableHead>
                <TableHead className="w-[15%]">Suspicion</TableHead>
                <TableHead title="Posts text that appears elsewhere">Copying</TableHead>
                <TableHead title="Posts in bursts, or rates against the consensus">
                  Activity
                </TableHead>
                <TableHead title="Keeps reviewing alongside the same other accounts">
                  Pack
                </TableHead>
                <TableHead className="text-right">Reviews</TableHead>
                <TableHead className="text-right" title="Most reviews posted in a single day">
                  Busiest day
                </TableHead>
                <TableHead className="text-right" title="Days between first and last review">
                  Account life
                </TableHead>
                <TableHead className="text-right">Avg rating</TableHead>
                <TableHead title="Size of the co-reviewing group it belongs to">Group</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((r) => (
                <TableRow key={r.reviewer_sk}>
                  <TableCell>
                    <Link
                      href={`/reviewers/${r.reviewer_sk}`}
                      className="block underline-offset-4 hover:underline"
                    >
                      <span className="block font-mono text-xs">{r.reviewerID}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {r.reviewer_name ?? "(no display name)"}
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell><ScoreBar value={r.score} /></TableCell>
                  <TableCell className="tabular text-xs">{r.score_text.toFixed(3)}</TableCell>
                  <TableCell className="tabular text-xs">
                    {r.score_behaviour.toFixed(3)}
                  </TableCell>
                  <TableCell className="tabular text-xs">{r.score_graph.toFixed(3)}</TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(r.n_reviews)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(r.max_per_day)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(r.lifespan_days)}d
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {r.mean_rating.toFixed(2)}
                  </TableCell>
                  <TableCell>
                    {r.ring_size > 0 ? (
                      <Link href={`/rings/${r.ring_id}`}>
                        <Badge variant="secondary" className="tabular text-xs">
                          {r.ring_size}
                        </Badge>
                      </Link>
                    ) : (
                      <span className="text-xs text-muted-foreground">&mdash;</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {data.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={10} className="py-10 text-center text-sm text-muted-foreground">
                    No accounts match these filters.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Pager total={data.total} limit={data.limit} offset={data.offset} />

      <div className="space-y-2 rounded-lg border bg-muted/30 p-4 text-xs text-muted-foreground">
        <p>
          <strong className="text-foreground">How to read a row.</strong> An account with a
          high suspicion score, an account life of a few days and a big busiest-day number is
          the classic burst: somebody made an account, posted everything at once, and left.
          A high score spread over years is usually copied text or pack behaviour instead
          &mdash; a long-running account that keeps showing up next to the same others.
        </p>
        <p>
          Open any account to see exactly which measurements pushed it up, written out in
          plain language.
        </p>
      </div>
    </div>
  );
}
