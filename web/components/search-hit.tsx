import Link from "next/link";
import { dayToDate, num } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

export type Hit = {
  doc_id: number;
  reviewerID: string | null;
  reviewerName: string | null;
  asin: string | null;
  summary: string | null;
  snippet: string;
  matched: string[];
  rating: number | null;
  n_words: number | null;
  n_chars: number | null;
  helpful_yes: number | null;
  helpful_total: number | null;
  reviewer_sk: number | null;
  product_sk: number | null;
  day: number | null;
  suspicion: number | null;
  score: number;
  final_score: number;
  bm25_score?: number;
  rerank_score?: number;
  ring_id: number | null;
  ring_size: number | null;
  neardup_cluster: number | null;
  neardup_jaccard: number | null;
};

/**
 * The API marks query matches with \x02...\x03 rather than HTML, so nothing from a
 * review body is ever interpolated as markup. React renders the segments, which
 * makes injection structurally impossible rather than escaped-by-convention.
 */
function Highlighted({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  let buffer = "";
  let marking = false;
  let key = 0;
  for (const ch of text) {
    if (ch === "\x02") {
      if (buffer) parts.push(buffer);
      buffer = "";
      marking = true;
    } else if (ch === "\x03") {
      if (buffer) {
        parts.push(
          <mark key={key++} className="rounded-sm bg-chart-4/35 px-0.5 text-foreground">
            {buffer}
          </mark>,
        );
      }
      buffer = "";
      marking = false;
    } else {
      buffer += ch;
    }
  }
  if (buffer) parts.push(marking ? <mark key={key++}>{buffer}</mark> : buffer);
  return <>{parts}</>;
}

export function SearchHit({ hit, rank }: { hit: Hit; rank: number }) {
  const suspicion = hit.suspicion ?? 0;
  const suspicious = suspicion >= 0.9;
  const moved =
    hit.rerank_score !== undefined && hit.bm25_score !== undefined;

  return (
    <article className="border-b py-4 last:border-0">
      <div className="mb-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="tabular w-6 shrink-0 text-xs text-muted-foreground">{rank}</span>
        <h3 className="text-sm font-medium">
          {hit.summary || <span className="text-muted-foreground">(no title)</span>}
        </h3>
        {hit.rating !== null && (
          <span className="tabular text-xs text-muted-foreground">{hit.rating}★</span>
        )}
        {hit.day !== null && (
          <span className="tabular text-xs text-muted-foreground">{dayToDate(hit.day)}</span>
        )}
      </div>

      <p className="mb-2 pl-9 text-sm leading-relaxed text-muted-foreground">
        <Highlighted text={hit.snippet} />
      </p>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-9 text-xs">
        {hit.reviewer_sk !== null && (
          <Link
            href={`/reviewers/${hit.reviewer_sk}`}
            className="font-mono text-muted-foreground underline-offset-2 hover:underline"
          >
            {hit.reviewerID}
          </Link>
        )}
        {hit.product_sk !== null && (
          <Link
            href={`/products/${hit.product_sk}`}
            className="font-mono text-muted-foreground underline-offset-2 hover:underline"
          >
            {hit.asin}
          </Link>
        )}
        {(hit.helpful_total ?? 0) > 0 && (
          <span className="tabular text-muted-foreground">
            {hit.helpful_yes}/{hit.helpful_total} found helpful
          </span>
        )}

        {suspicious && (
          <Badge variant="outline" className="border-chart-5/50 text-chart-5">
            suspicious account · {suspicion.toFixed(2)}
          </Badge>
        )}
        {(hit.ring_size ?? 0) > 0 && (
          <Link href={`/rings/${hit.ring_id}`}>
            <Badge variant="secondary" className="tabular">
              in a {num(hit.ring_size)}-account group
            </Badge>
          </Link>
        )}
        {hit.neardup_cluster !== null && (
          <Link href={`/duplicates/loose/${hit.neardup_cluster}`}>
            <Badge variant="secondary">
              text reused elsewhere
              {hit.neardup_jaccard
                ? ` · ${(hit.neardup_jaccard * 100).toFixed(0)}% match`
                : ""}
            </Badge>
          </Link>
        )}
        <Link
          href={`/search/similar/${hit.doc_id}`}
          className="underline underline-offset-2 hover:no-underline"
        >
          find near-copies
        </Link>

        <span className="ml-auto flex items-center gap-2 tabular text-muted-foreground">
          {moved ? (
            <>
              <span title="Neural cross-encoder relevance">
                neural {hit.rerank_score!.toFixed(3)}
              </span>
              <span title="BM25 keyword relevance">bm25 {hit.bm25_score!.toFixed(2)}</span>
            </>
          ) : (
            <span title="BM25 keyword relevance">bm25 {hit.score.toFixed(2)}</span>
          )}
        </span>
      </div>
    </article>
  );
}
