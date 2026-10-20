import Link from "next/link";
import { pct } from "@/lib/api";

export type Exposure = {
  summary: {
    queries: number;
    top_k: number;
    base_rate: number;
    share: number;
    lift: number;
    share_demoted: number;
    clean_queries: number;
    clean_queries_demoted: number;
    worst: string;
    worst_flagged: number;
  };
  rows: { query: string; n: number; flagged: number; flagged_demoted: number }[];
};

const href = (q: string, demote = false) =>
  `/search?q=${encodeURIComponent(q)}${demote ? "&demote=1" : ""}`;

/** Ten squares, one per result slot, so "3 of the top 10" is something you can see. */
function Slots({ flagged, total }: { flagged: number; total: number }) {
  return (
    <span className="flex gap-0.5" aria-label={`${flagged} of ${total} results flagged`}>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`size-3 rounded-[3px] ${i < flagged ? "bg-chart-5" : "bg-muted"}`}
        />
      ))}
    </span>
  );
}

/**
 * Where suspicious reviews reach shoppers: 40 ordinary searches, every one shown.
 *
 * The finding is concentration rather than contamination, so the chart has to show
 * the clean searches too. Only showing the hit ones would make a 1.3x effect look
 * like a flood.
 */
export function SearchExposure({ data }: { data: Exposure }) {
  const s = data.summary;
  const hit = data.rows.filter((r) => r.flagged > 0);
  const clean = data.rows.filter((r) => r.flagged === 0);
  const example = clean.find((r) => r.query === "coffee maker") ?? clean[0];

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight">
          Most searches are clean. A few categories are not.
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          A fake review only does harm when somebody reads it, and that happens here, in search.
          So {s.queries} ordinary shopping searches were run, and in each first page of{" "}
          {s.top_k} results the reviews written by a top-1% suspicious account were counted.
        </p>
      </div>

      <div className="grid gap-4 rounded-lg border p-4 sm:grid-cols-3">
        <div>
          <div className="text-2xl font-semibold tabular">{pct(s.share, 1)}</div>
          <div className="text-xs text-muted-foreground">
            of first-page results come from flagged accounts, against {pct(s.base_rate, 1)} of all
            reviews — only {s.lift.toFixed(1)}× what chance would give
          </div>
        </div>
        <div>
          <div className="text-2xl font-semibold tabular">
            {s.clean_queries} of {s.queries}
          </div>
          <div className="text-xs text-muted-foreground">
            searches had no flagged reviews on the first page at all
          </div>
        </div>
        <div>
          <div className="text-2xl font-semibold tabular">
            {s.worst_flagged} of {s.top_k}
          </div>
          <div className="text-xs text-muted-foreground">
            for &ldquo;{s.worst}&rdquo;, the worst search —{" "}
            {Math.round((100 * s.worst_flagged) / s.top_k)}% of its first page
          </div>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="grid grid-cols-[minmax(0,11rem)_13rem_1fr] items-center gap-x-4 px-1 text-xs text-muted-foreground">
          <span>Search</span>
          <span>First {s.top_k} results</span>
          <span>With demotion on</span>
        </div>
        {hit.map((r) => (
          <div
            key={r.query}
            className="grid grid-cols-[minmax(0,11rem)_13rem_1fr] items-center gap-x-4 rounded-md px-1 py-1 text-sm hover:bg-muted/50"
          >
            <Link href={href(r.query)} className="truncate underline-offset-2 hover:underline">
              {r.query}
            </Link>
            <Link href={href(r.query)} className="flex items-center gap-2">
              <Slots flagged={r.flagged} total={r.n} />
              <span className="tabular text-xs text-muted-foreground">
                {r.flagged}/{r.n}
              </span>
            </Link>
            <Link
              href={href(r.query, true)}
              className="tabular text-xs text-muted-foreground underline-offset-2 hover:underline"
            >
              {r.flagged_demoted}/{r.n} &rarr; see it
            </Link>
          </div>
        ))}
      </div>

      <div className="space-y-1.5">
        <div className="text-xs text-muted-foreground">
          The other {clean.length} searches had none on the first page:
        </div>
        <div className="flex flex-wrap gap-1.5">
          {clean.map((r) => (
            <Link
              key={r.query}
              href={href(r.query)}
              className="rounded-md border px-2 py-0.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              {r.query}
            </Link>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Link
          href={href(s.worst)}
          className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground hover:opacity-90"
        >
          Try the worst: &ldquo;{s.worst}&rdquo; &rarr;
        </Link>
        {example && (
          <Link href={href(example.query)} className="rounded-md border px-3 py-2 text-sm hover:bg-secondary">
            Compare a clean one: &ldquo;{example.query}&rdquo;
          </Link>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        With <em>Demote suspicious reviews</em> on, flagged results drop from {pct(s.share, 1)} to{" "}
        {pct(s.share_demoted, 1)} of first pages. Nothing is hidden: they move further down, and are
        still there. That drop is the toggle doing what it says — it lowers exactly the reviews this
        score flags — so it shows what demotion does, not that anything new was found. The{" "}
        {s.queries} searches were picked before any results were looked at, and none was added or
        removed afterwards.
      </p>
    </div>
  );
}
