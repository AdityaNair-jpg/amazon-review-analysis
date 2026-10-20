import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiDown, dayToDate } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

type Similar = {
  source: {
    doc_id: number;
    reviewerID: string | null;
    asin: string | null;
    summary: string | null;
    snippet: string;
    rating: number | null;
  };
  items: {
    doc_id: number;
    jaccard: number;
    rating: number | null;
    day: number | null;
    reviewerID: string | null;
    asin: string | null;
    suspicion: number | null;
    summary: string | null;
    snippet: string;
  }[];
  note: string;
};

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let data: Similar;
  try {
    data = await api<Similar>(`/search/similar/${id}`);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    if (error instanceof Error && error.message.includes("not found")) notFound();
    throw error;
  }

  const accounts = new Set(data.items.map((i) => i.reviewerID)).size;

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Link
          href="/search"
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          &larr; Back to search
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Near-copies of this review</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Found with MinHash and locality-sensitive hashing, then confirmed word by word.
          Similarity below is measured exactly, not estimated.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">The review you started from</CardTitle>
          <CardDescription className="flex flex-wrap gap-x-3 gap-y-1">
            <span className="font-mono">{data.source.reviewerID}</span>
            <span className="font-mono">{data.source.asin}</span>
            {data.source.rating !== null && <span className="tabular">{data.source.rating}★</span>}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm font-medium">{data.source.summary}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
            {data.source.snippet}
          </p>
        </CardContent>
      </Card>

      {data.items.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No near-copies. This review&rsquo;s wording does not appear anywhere else in the
            corpus &mdash; which is what the overwhelming majority of reviews look like.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              {data.items.length} near-identical {data.items.length === 1 ? "review" : "reviews"}{" "}
              across {accounts} other {accounts === 1 ? "account" : "accounts"}
            </CardTitle>
            <CardDescription>
              Different accounts posting the same words is the least ambiguous signal in this
              project. Judge for yourself.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.items.map((item) => (
              <div key={item.doc_id} className="rounded-lg border p-4">
                <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                  <Badge variant="outline" className="tabular">
                    {(item.jaccard * 100).toFixed(0)}% identical
                  </Badge>
                  <span className="font-mono text-muted-foreground">{item.reviewerID}</span>
                  <span className="font-mono text-muted-foreground">{item.asin}</span>
                  {item.day !== null && (
                    <span className="tabular text-muted-foreground">{dayToDate(item.day)}</span>
                  )}
                  {item.rating !== null && (
                    <span className="tabular text-muted-foreground">{item.rating}★</span>
                  )}
                  {(item.suspicion ?? 0) >= 0.9 && (
                    <Badge variant="outline" className="border-chart-5/50 text-chart-5">
                      suspicious account
                    </Badge>
                  )}
                </div>
                <p className="text-sm font-medium">{item.summary}</p>
                <p className="mt-1 text-sm text-muted-foreground">{item.snippet}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
