import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiDown, dayToDate, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { Stat } from "@/components/stat";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

type Detail = {
  kind: string;
  cluster: Record<string, number | boolean | null>;
  members: {
    review_sk: number;
    reviewer_sk: number;
    reviewerID: string;
    reviewer_name: string | null;
    asin: string;
    day: number;
    rating: number;
    reviewText: string;
    summary: string;
    jaccard: number;
  }[];
};

export default async function Page({
  params,
}: {
  params: Promise<{ kind: string; id: string }>;
}) {
  const { kind, id } = await params;
  let data: Detail;
  try {
    data = await api<Detail>(`/duplicates/${kind}/${id}`);
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    if (error instanceof Error && error.message.includes("not found")) notFound();
    throw error;
  }

  const c = data.cluster as Record<string, number>;
  const distinctAccounts = new Set(data.members.map((m) => m.reviewer_sk)).size;

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Link
          href={`/duplicates?kind=${kind}`}
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          &larr; All clusters
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">
          Cluster #{id}{" "}
          <span className="text-base font-normal text-muted-foreground">
            ({kind === "exact" ? "exact duplicate" : `near-duplicate, ${kind}`})
          </span>
        </h1>
      </div>

      <Card>
        <CardContent className="grid grid-cols-2 gap-6 pt-6 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Reviews" value={num(c.n_reviews)} />
          <Stat label="Distinct accounts" value={num(c.n_reviewers)} />
          <Stat label="Distinct products" value={num(c.n_products)} />
          <Stat
            label={kind === "exact" ? "Words" : "Mean Jaccard"}
            value={kind === "exact" ? num(c.n_words) : (c.mean_jaccard ?? 0).toFixed(3)}
          />
          <Stat label="Mean rating" value={(c.mean_rating ?? 0).toFixed(2)} />
          <Stat
            label="Span"
            value={`${num(c.span_days)}d`}
            sub={`from ${dayToDate(c.first_day)}`}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">
            The same words, from {distinctAccounts} account
            {distinctAccounts === 1 ? "" : "s"}
          </CardTitle>
          <CardDescription>
            Full text of every member, so you can judge for yourself whether this is
            coordination, boilerplate, or coincidence.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.members.map((m) => (
            <div key={m.review_sk} className="rounded-lg border p-4">
              <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <Link
                  href={`/reviewers/${m.reviewer_sk}`}
                  className="font-mono underline-offset-4 hover:underline"
                >
                  {m.reviewerID}
                </Link>
                <span className="text-muted-foreground">
                  {m.reviewer_name ?? "(no display name)"}
                </span>
                <Link
                  href={`/products/${m.asin}`}
                  className="font-mono text-muted-foreground"
                >
                  {m.asin}
                </Link>
                <span className="tabular text-muted-foreground">{dayToDate(m.day)}</span>
                <Badge variant="secondary" className="tabular">
                  {m.rating}★
                </Badge>
                {kind !== "exact" && (
                  <Badge variant="outline" className="tabular">
                    J = {m.jaccard.toFixed(3)}
                  </Badge>
                )}
              </div>
              <p className="text-sm font-medium">{m.summary}</p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
                {m.reviewText}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
