import Link from "next/link";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Pager } from "@/components/pager";
import { RingScatter } from "@/components/charts/ring-scatter";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export const dynamic = "force-dynamic";

type Ring = {
  ring_id: number;
  n_members: number;
  n_edges: number;
  density: number;
  mean_shared: number;
  n_products: number;
  n_reviews: number;
  span_days: number;
  mean_rating: number;
  first_day: number;
};

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  let data: { total: number; limit: number; offset: number; items: Ring[] };
  let scatter: { rings: Parameters<typeof RingScatter>[0]["rings"] };
  try {
    [data, scatter] = await Promise.all([
      api<{ total: number; limit: number; offset: number; items: Ring[] }>("/rings", {
        limit: Number(sp.limit ?? 50),
        offset: Number(sp.offset ?? 0),
        sort: sp.sort ?? "density",
        dir: sp.dir ?? "desc",
      }),
      api<typeof scatter>("/charts/ring-scatter"),
    ]);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    throw error;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Groups reviewing together</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {num(data.total)} sets of accounts that keep turning up on the same products{" "}
          <em>within days of each other</em>. Two people buying the same three things over a
          decade is a coincidence. Six accounts hitting the same nineteen products inside a
          month is a schedule &mdash; and that is what this page lists.
        </p>
        <p className="max-w-3xl rounded-md border-l-2 border-chart-4 bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
          <strong className="text-foreground">Why these are small.</strong> If you simply
          follow the chain of &ldquo;this account shares products with that one&rdquo;, you
          end up with a single blob containing 82% of everybody &mdash; because in any large
          population almost everyone is connected to everyone else through a few steps. That
          blob means nothing. So a group only counts here if it is both{" "}
          <em>small</em> and <em>tightly interlinked</em>: every member overlapping with most
          of the others, not just strung together in a chain. One 44,039-account blob was
          excluded on exactly that basis.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Every group at a glance</CardTitle>
          <CardDescription>
            Bubbles at the top-left are the ones worth looking at: tightly interlinked and
            short-lived. Bubbles on the right ran for years, which more often means a genuine
            community than a campaign. Click any bubble to open it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RingScatter rings={scatter.rings} />
        </CardContent>
      </Card>

      <Card className="overflow-hidden py-0">
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Group</TableHead>
                <TableHead className="text-right">Accounts</TableHead>
                <TableHead
                  className="text-right"
                  title="1.00 means every member overlaps with every other member"
                >
                  How interlinked
                </TableHead>
                <TableHead className="text-right" title="Averaged over every pair in the group">
                  Products in common
                </TableHead>
                <TableHead className="text-right">Products touched</TableHead>
                <TableHead className="text-right">Reviews</TableHead>
                <TableHead className="text-right" title="First to last review by the group">
                  Operated over
                </TableHead>
                <TableHead className="text-right">Avg rating</TableHead>
                <TableHead>First seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((r) => (
                <TableRow key={r.ring_id}>
                  <TableCell>
                    <Link
                      href={`/rings/${r.ring_id}`}
                      className="font-mono text-xs underline-offset-4 hover:underline"
                    >
                      #{r.ring_id}
                    </Link>
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">{r.n_members}</TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {r.density.toFixed(3)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {r.mean_shared.toFixed(1)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(r.n_products)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(r.n_reviews)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(r.span_days)}d
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {r.mean_rating.toFixed(2)}
                  </TableCell>
                  <TableCell className="tabular text-xs text-muted-foreground">
                    {dayToDate(r.first_day)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Pager total={data.total} limit={data.limit} offset={data.offset} />
    </div>
  );
}
