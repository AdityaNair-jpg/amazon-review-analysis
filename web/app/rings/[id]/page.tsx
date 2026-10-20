import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Stat } from "@/components/stat";
import { ScoreBar } from "@/components/score-bar";
import { RingGraph } from "@/components/ring-graph";
import { RingConvergence } from "@/components/charts/ring-convergence";
import { RatingDonut } from "@/components/charts/rating-donut";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export const dynamic = "force-dynamic";

type Detail = {
  ring: Record<string, number>;
  members: {
    reviewer_sk: number;
    reviewerID: string;
    reviewer_name: string | null;
    coreview_degree: number;
    coreview_weight: number;
    score: number | null;
    score_text: number | null;
    score_behaviour: number | null;
    score_graph: number | null;
    n_reviews: number;
    max_per_day: number;
    lifespan_days: number;
    mean_rating: number;
  }[];
  edges: { r1: number; r2: number; shared: number }[];
  shared_products: {
    asin: string;
    product_sk: number;
    n_ring_reviews: number;
    mean_rating: number;
    first_day: number;
    last_day: number;
  }[];
  truncated: boolean;
};

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let data: Detail;
  let convergence: {
    products: Parameters<typeof RingConvergence>[0]["products"];
    reviews: Parameters<typeof RingConvergence>[0]["reviews"];
    members: Parameters<typeof RingConvergence>[0]["members"];
  };
  try {
    [data, convergence] = await Promise.all([
      api<Detail>(`/rings/${id}`),
      api<typeof convergence>(`/rings/${id}/convergence`),
    ]);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    if (error instanceof Error && error.message.includes("not found")) notFound();
    throw error;
  }
  const r = data.ring;

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Link
          href="/rings"
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          &larr; All rings
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Ring #{id}</h1>
      </div>

      <Card>
        <CardContent className="grid grid-cols-2 gap-6 pt-6 sm:grid-cols-4 lg:grid-cols-7">
          <Stat label="Accounts" value={num(r.n_members)} />
          <Stat label="Density" value={r.density.toFixed(3)} sub={`${num(r.n_edges)} edges`} />
          <Stat
            label="Shared / pair"
            value={r.mean_shared.toFixed(1)}
            sub="products, within 30d"
          />
          <Stat label="Products" value={num(r.n_products)} />
          <Stat label="Reviews" value={num(r.n_reviews)} />
          <Stat label="Mean rating" value={r.mean_rating.toFixed(2)} />
          <Stat
            label="Active span"
            value={`${num(r.span_days)}d`}
            sub={`from ${dayToDate(r.first_day)}`}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">When this ring hit each product</CardTitle>
          <CardDescription>
            One row per shared product, one dot per member review, on a shared time axis.
            Vertical stacks are the signal.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RingConvergence
            products={convergence.products}
            reviews={convergence.reviews}
            members={convergence.members}
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Co-review structure</CardTitle>
            <CardDescription>
              Each node is an account; edge thickness is the number of products the pair
              co-reviewed within 30 days of each other.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RingGraph members={data.members} edges={data.edges} />
          </CardContent>
        </Card>

        <Card className="overflow-hidden py-0">
          <CardHeader className="px-6 pb-2 pt-6">
            <CardTitle className="text-base">Products this ring converged on</CardTitle>
            <CardDescription>Products reviewed by more than one ring member.</CardDescription>
          </CardHeader>
          <CardContent className="max-h-[420px] overflow-auto px-0 pb-0">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">Ring reviews</TableHead>
                  <TableHead className="text-right">Mean rating</TableHead>
                  <TableHead className="text-right">Window</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.shared_products.map((p) => (
                  <TableRow key={p.product_sk}>
                    <TableCell>
                      <Link
                        href={`/products/${p.product_sk}`}
                        className="font-mono text-xs underline-offset-4 hover:underline"
                      >
                        {p.asin}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right tabular text-xs">
                      {p.n_ring_reviews}
                    </TableCell>
                    <TableCell className="text-right tabular text-xs">
                      {p.mean_rating.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right tabular text-xs text-muted-foreground">
                      {p.last_day - p.first_day}d
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">What ratings this ring gave</CardTitle>
          <CardDescription>
            Across every review its members wrote on the products they share.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RatingDonut
            ratings={[1, 2, 3, 4, 5].map((rating) => ({
              rating,
              n: convergence.reviews.filter((r) => r.rating === rating).length,
            })).filter((r) => r.n > 0)}
            caption={
              <>
                A ring pushing a product leaves a rating distribution with almost no spread.
                Compare this against the corpus-wide mix of 4.16 &mdash; and remember that no
                rating level enters the score, so this is a description of what was found, not
                a reason it was found.
              </>
            }
          />
        </CardContent>
      </Card>

      <Card className="overflow-hidden py-0">
        <CardHeader className="px-6 pb-2 pt-6">
          <CardTitle className="text-base">Members</CardTitle>
          {data.truncated && (
            <CardDescription>
              Showing the 200 highest-weight members of {num(r.n_members)}.
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Account</TableHead>
                <TableHead>Score</TableHead>
                <TableHead>T</TableHead>
                <TableHead>B</TableHead>
                <TableHead>G</TableHead>
                <TableHead className="text-right">Reviews</TableHead>
                <TableHead className="text-right">Peak/day</TableHead>
                <TableHead className="text-right">Span</TableHead>
                <TableHead className="text-right">Rating</TableHead>
                <TableHead className="text-right">Ring links</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.members.map((m) => (
                <TableRow key={m.reviewer_sk}>
                  <TableCell>
                    <Link
                      href={`/reviewers/${m.reviewer_sk}`}
                      className="block underline-offset-4 hover:underline"
                    >
                      <span className="block font-mono text-xs">{m.reviewerID}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {m.reviewer_name ?? "(no display name)"}
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell>
                    <ScoreBar value={m.score} />
                  </TableCell>
                  <TableCell className="tabular text-xs">
                    {m.score_text?.toFixed(3) ?? "—"}
                  </TableCell>
                  <TableCell className="tabular text-xs">
                    {m.score_behaviour?.toFixed(3) ?? "—"}
                  </TableCell>
                  <TableCell className="tabular text-xs">
                    {m.score_graph?.toFixed(3) ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(m.n_reviews)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(m.max_per_day)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {num(m.lifespan_days)}d
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {m.mean_rating?.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {m.coreview_degree}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
