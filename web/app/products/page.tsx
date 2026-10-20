import Link from "next/link";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Pager } from "@/components/pager";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export const dynamic = "force-dynamic";

type Product = {
  product_sk: number;
  asin: string;
  n_reviews: number;
  mean_rating: number;
  max_daily_z: number;
  max_7d_z: number;
  peak_day: number;
  dup_text_rate: number;
  rating_shift: number;
};

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  let data: { total: number; limit: number; offset: number; items: Product[] };
  try {
    data = await api("/products", {
      limit: Number(sp.limit ?? 50),
      offset: Number(sp.offset ?? 0),
      min_reviews: Number(sp.min_reviews ?? 10),
    });
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    throw error;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Products by review burst</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Ranked by the largest single-day burst z-score, <em>de-trended</em> against the
          corpus-wide daily volume.
        </p>
        <p className="max-w-3xl rounded-md border-l-2 border-chart-4 bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
          <strong className="text-foreground">Why de-trending is not optional.</strong> 2013
          alone holds 14.79M of the 41.1M reviews in this corpus; 1997 holds 2,707. Without
          correcting for that, a &ldquo;burst detector&rdquo; is just a detector for the year
          2013. Expected volume is{" "}
          <code className="font-mono">E = n_product × daily_volume(d) / 41,135,700</code> and
          the score is <code className="font-mono">z = (observed − E) / √E</code>. The
          resulting correlation between burst score and calendar year is +0.093.
        </p>
      </div>

      <Card className="overflow-hidden py-0">
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Product</TableHead>
                <TableHead className="text-right">Reviews</TableHead>
                <TableHead className="text-right">Mean rating</TableHead>
                <TableHead className="text-right">Peak day z</TableHead>
                <TableHead className="text-right">Peak 7-day z</TableHead>
                <TableHead>Peak date</TableHead>
                <TableHead className="text-right">Duplicate text</TableHead>
                <TableHead className="text-right">Rating shift</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((p) => (
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
                    {num(p.n_reviews)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {p.mean_rating.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs font-medium">
                    {p.max_daily_z.toFixed(1)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {p.max_7d_z.toFixed(1)}
                  </TableCell>
                  <TableCell className="tabular text-xs text-muted-foreground">
                    {dayToDate(p.peak_day)}
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {(p.dup_text_rate * 100).toFixed(1)}%
                  </TableCell>
                  <TableCell className="text-right tabular text-xs">
                    {p.rating_shift.toFixed(2)}
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
