import Link from "next/link";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Pager } from "@/components/pager";
import { DuplicateFilters } from "@/components/duplicate-filters";
import { ClusterSizeChart } from "@/components/charts/cluster-size-chart";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export const dynamic = "force-dynamic";

type Cluster = {
  cluster_id: number;
  n_reviews: number;
  n_reviewers: number;
  n_products: number;
  n_words?: number;
  mean_jaccard?: number;
  span_days: number;
  mean_rating: number;
  first_day: number;
};

const BLURB: Record<string, string> = {
  exact:
    "Reviews whose text is character-for-character the same once capitalisation and spacing are ignored.",
  loose:
    "Reviews that are at least 70% the same — reworded a little, but clearly built from one original. Every match here was checked word by word, not estimated.",
  tight:
    "Reviews that are at least 88% the same. Fewer results, and almost no room to argue they were written independently.",
};

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const kind = sp.kind ?? "loose";
  let data: { kind: string; total: number; limit: number; offset: number; items: Cluster[] };
  let dist: {
    sizes: Parameters<typeof ClusterSizeChart>[0]["sizes"];
    jaccard: Parameters<typeof ClusterSizeChart>[0]["jaccard"];
  };
  try {
    [data, dist] = await Promise.all([
      api<typeof data>("/duplicates", {
        kind,
        limit: Number(sp.limit ?? 50),
        offset: Number(sp.offset ?? 0),
        sort: sp.sort,
        cross_reviewer: sp.cross_reviewer ?? "true",
        substantive: sp.substantive ?? "true",
      }),
      api<typeof dist>("/charts/cluster-sizes"),
    ]);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    throw error;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">The same review, posted twice</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{BLURB[kind]}</p>
        <p className="max-w-3xl rounded-md border-l-2 border-chart-4 bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
          <strong className="text-foreground">Read the top of this list sceptically.</strong>{" "}
          The biggest groups here are <em>not</em> campaigns. They are Amazon&rsquo;s own
          &ldquo;how to write a review&rdquo; help text, which a dozen confused people pasted
          in as their review, plus filler like the alphabet or counting to twenty from people
          padding out a length requirement. Those are low-effort reviews, not paid ones. The
          genuine templated promotion sits a little further down, in the groups of four to
          eight accounts &mdash; like{" "}
          <Link href="/duplicates/loose/60821" className="underline underline-offset-2">
            this one
          </Link>
          , where five accounts posted the same 200-word phone-case review across three
          different products.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">How much copying is there?</CardTitle>
          <CardDescription>
            Most copying is one person reusing their own words, which is lazy but not
            coordinated. The interesting cases are the right-hand tail: the same text on
            several different accounts. Both axes are logarithmic because that tail is long.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ClusterSizeChart sizes={dist.sizes} jaccard={dist.jaccard} />
        </CardContent>
      </Card>

      <DuplicateFilters />

      <Card className="overflow-hidden py-0">
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Group</TableHead>
                <TableHead className="text-right">Accounts involved</TableHead>
                <TableHead className="text-right">Reviews</TableHead>
                <TableHead className="text-right">Products</TableHead>
                {kind === "exact" ? (
                  <TableHead className="text-right">Words</TableHead>
                ) : (
                  <TableHead className="text-right" title="100% means word-for-word identical">
                    How identical
                  </TableHead>
                )}
                <TableHead className="text-right">Posted over</TableHead>
                <TableHead className="text-right">Avg rating</TableHead>
                <TableHead>First seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((c) => (
                <TableRow key={c.cluster_id}>
                  <TableCell>
                    <Link
                      href={`/duplicates/${kind}/${c.cluster_id}`}
                      className="font-mono text-xs underline-offset-4 hover:underline"
                    >
                      #{c.cluster_id}
                    </Link>
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">{c.n_reviewers}</TableCell>
                  <TableCell className="text-right tabular text-xs">{c.n_reviews}</TableCell>
                  <TableCell className="text-right tabular text-xs">{c.n_products}</TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {kind === "exact"
                      ? num(c.n_words)
                      : `${((c.mean_jaccard ?? 0) * 100).toFixed(0)}%`}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(c.span_days)}d
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {c.mean_rating?.toFixed(2)}
                  </TableCell>
                  <TableCell className="tabular text-xs text-muted-foreground">
                    {dayToDate(c.first_day)}
                  </TableCell>
                </TableRow>
              ))}
              {data.items.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={8}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    No clusters match these filters.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Pager total={data.total} limit={data.limit} offset={data.offset} />
    </div>
  );
}
