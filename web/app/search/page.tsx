import Link from "next/link";
import { api, ApiDown, num } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { SearchBox } from "@/components/search-box";
import { SearchHit, type Hit } from "@/components/search-hit";
import { Pager } from "@/components/pager";
import { Card, CardContent } from "@/components/ui/card";
import { SearchExposure, type Exposure } from "@/components/search-exposure";

export const dynamic = "force-dynamic";

type Results = {
  query: string;
  terms: { term: string; df: number; idf: number }[];
  unknown: string[];
  ignored: { term: string; df: number }[];
  total: number;
  limit: number;
  offset: number;
  items: Hit[];
  reranked: boolean;
  demoted: boolean;
  flagged_in_top10: number;
  group: "core" | "packs" | null;
  timing_ms: { bm25?: number; rerank?: number; total?: number };
};

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const q = sp.q ?? "";
  const limit = Number(sp.limit ?? 20);
  const offset = Number(sp.offset ?? 0);

  const group = sp.group === "core" || sp.group === "packs" ? sp.group : undefined;

  let data: Results | null = null;
  let exposure: Exposure | null = null;
  try {
    if (q.trim()) {
      data = await api<Results>("/search", {
        q,
        limit,
        offset,
        demote: sp.demote === "1",
        rerank: sp.rerank === "1",
        group,
      });
    } else {
      // The story is optional: if stage 16 has not been run, the page still works.
      exposure = await api<Exposure>("/story/search-exposure").catch(() => null);
    }
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    throw error;
  }

  const withoutGroup = (() => {
    const next = new URLSearchParams();
    for (const [k, v] of Object.entries(sp)) if (v && k !== "group" && k !== "offset") next.set(k, v);
    return `/search?${next}`;
  })();

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Search the reviews</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Keyword search across all 41,135,700 review texts, ranked by BM25. Every result
          carries what the spam analysis already worked out about the account that wrote it,
          so you can see coordinated content sitting in the results rather than having to go
          looking for it.
        </p>
      </div>

      <SearchBox />

      {group && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-chart-5/40 bg-chart-5/5 px-4 py-2.5 text-sm">
          <span>
            Searching only reviews by{" "}
            <Link href="/network" className="font-medium underline underline-offset-2">
              {group === "core"
                ? "the linked core of the suspicious network"
                : "the small packs of the suspicious network"}
            </Link>
            , not the whole corpus.
          </span>
          <Link href={withoutGroup} className="text-muted-foreground underline underline-offset-2">
            Search all 41.1M reviews instead
          </Link>
        </div>
      )}

      {!data && exposure && (
        <Card>
          <CardContent className="pt-6">
            <SearchExposure data={exposure} />
          </CardContent>
        </Card>
      )}

      {!data && (
        <Card>
          <CardContent className="space-y-3 pt-6 text-sm text-muted-foreground">
            <p>
              The index holds <strong className="text-foreground">1.87 billion</strong> entries
              — one for every (word, review) pair in the corpus, after stopword removal and
              Porter stemming. Searching it takes a fraction of a second; scanning the raw
              text for the same thing takes <strong className="text-foreground">128
              seconds</strong>, which is the entire reason an index exists.
            </p>
            <p>
              Two toggles change the ranking.{" "}
              <strong className="text-foreground">Neural reranking</strong> re-orders the top
              50 with a cross-encoder that reads the query and the review together, which
              catches meaning that keyword overlap misses.{" "}
              <strong className="text-foreground">Demote suspicious reviews</strong> multiplies
              each result&rsquo;s relevance by how independent its author looks — the search
              equivalent of what a platform does about review farms.
            </p>
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b pb-3 text-xs text-muted-foreground">
            <span>
              <span className="tabular font-medium text-foreground">
                {num(data.total)}
              </span>
              {data.total >= 1000 ? "+" : ""} matching reviews
            </span>
            {data.terms.length > 0 && (
              <span>
                searched for{" "}
                {data.terms.map((t, i) => (
                  <span key={t.term}>
                    {i > 0 && ", "}
                    <span
                      className="font-mono text-foreground"
                      title={`appears in ${t.df.toLocaleString("en-US")} reviews · idf ${t.idf}`}
                    >
                      {t.term}
                    </span>
                  </span>
                ))}{" "}
                (word stems)
              </span>
            )}
            {data.unknown.length > 0 && (
              <span className="text-chart-5">
                not in the index: {data.unknown.join(", ")}
              </span>
            )}
            {data.ignored?.length > 0 && (
              <span
                title={data.ignored
                  .map((t) => `${t.term} appears in ${t.df.toLocaleString("en-US")} reviews`)
                  .join(" · ")}
              >
                too common to narrow anything down, so skipped:{" "}
                <span className="font-mono text-foreground">
                  {data.ignored.map((t) => t.term).join(", ")}
                </span>
              </span>
            )}
            <span className="tabular">
              {data.timing_ms.total?.toFixed(0)} ms
              {data.reranked && data.timing_ms.rerank
                ? ` (${data.timing_ms.bm25?.toFixed(0)} ms search + ${data.timing_ms.rerank.toFixed(0)} ms neural)`
                : ""}
            </span>
            {data.reranked && <span className="text-chart-2">neural reranking on</span>}
            {data.demoted && <span className="text-chart-4">suspicious results demoted</span>}
          </div>

          {/* Inside a group-scoped search every result is by a flagged account by
              construction, so the warning would be true, useless and misleading. */}
          {data.flagged_in_top10 > 0 && !data.group && (
            <p className="rounded-md border-l-2 border-chart-5 bg-muted/40 px-4 py-2.5 text-xs text-muted-foreground">
              <strong className="text-foreground">
                {data.flagged_in_top10} of the top 10 results
              </strong>{" "}
              were written by accounts in the most suspicious 1% of the corpus.
              {!data.demoted && " Turn on “Demote suspicious reviews” to push them down."}
            </p>
          )}

          <Card className="py-0">
            <CardContent className="px-6 py-2">
              {data.items.length === 0 ? (
                <p className="py-12 text-center text-sm text-muted-foreground">
                  Nothing matched. Try fewer or more common words.
                </p>
              ) : (
                data.items.map((hit, i) => (
                  <SearchHit key={hit.doc_id} hit={hit} rank={offset + i + 1} />
                ))
              )}
            </CardContent>
          </Card>

          {data.items.length > 0 && (
            <Pager
              total={Math.min(data.total, 1000)}
              limit={data.limit}
              offset={data.offset}
            />
          )}

          <p className="text-xs text-muted-foreground">
            Ranked by BM25 over the top 1,000 candidates.{" "}
            <Link href="/methodology" className="underline underline-offset-4">
              How the suspicion scores are built
            </Link>
            .
          </p>
        </>
      )}
    </div>
  );
}
