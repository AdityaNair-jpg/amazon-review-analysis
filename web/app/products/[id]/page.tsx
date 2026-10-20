import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Stat } from "@/components/stat";
import { ProductTimeline } from "@/components/product-timeline";
import { RatingDonut } from "@/components/charts/rating-donut";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

type Detail = {
  product: Record<string, number | string | null>;
  series: { day: number; n_reviews: number; mean_rating: number; expected: number; z: number }[];
};

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let data: Detail;
  let ratings: { ratings: { rating: number; n: number }[] };
  try {
    [data, ratings] = await Promise.all([
      api<Detail>(`/products/${id}`),
      api<typeof ratings>(`/products/${id}/ratings`),
    ]);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    if (error instanceof Error && error.message.includes("not found")) notFound();
    throw error;
  }
  const p = data.product as Record<string, number>;

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Link
          href="/products"
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          &larr; All products
        </Link>
        <h1 className="font-mono text-2xl font-semibold tracking-tight">
          {data.product.asin as string}
        </h1>
        <p className="text-sm text-muted-foreground">
          This corpus carries no product metadata, so products are identified by ASIN only.
        </p>
      </div>

      <Card>
        <CardContent className="grid grid-cols-2 gap-6 pt-6 sm:grid-cols-4 lg:grid-cols-7">
          <Stat label="Reviews" value={num(p.n_reviews)} />
          <Stat label="Mean rating" value={p.mean_rating?.toFixed(2)} />
          <Stat label="Rating entropy" value={p.rating_entropy?.toFixed(3)} />
          <Stat
            label="Peak day z"
            value={p.max_daily_z?.toFixed(1)}
            sub={dayToDate(p.peak_day)}
          />
          <Stat label="Peak 7-day z" value={p.max_7d_z?.toFixed(1)} />
          <Stat label="Duplicate text" value={`${((p.dup_text_rate ?? 0) * 100).toFixed(1)}%`} />
          <Stat
            label="Graph degree"
            value={num(p.pg_degree)}
            sub="co-reviewed products"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Rating mix for this product</CardTitle>
          <CardDescription>
            A J-shape — mostly fives with a one-star tail — is the ordinary Amazon pattern. A
            flat wall of fives arriving inside a short window is not.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RatingDonut ratings={ratings.ratings} height={200} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Daily review volume against expectation</CardTitle>
          <CardDescription>
            Bars are observed reviews per day. The line underneath is what the corpus-wide
            daily volume predicts for a product of this size. The gap between them &mdash;
            not the bar height &mdash; is the burst signal.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ProductTimeline series={data.series} />
        </CardContent>
      </Card>
    </div>
  );
}
