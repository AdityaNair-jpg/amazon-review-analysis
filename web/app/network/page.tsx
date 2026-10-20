import Link from "next/link";
import { api, ApiDown, num, pct } from "@/lib/api";
import { ApiError } from "@/components/api-error";
import { NetworkExplorer } from "@/components/network-explorer";
import { Stat } from "@/components/stat";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

type Group = {
  label: string;
  accounts: number;
  reviews_checked: number;
  reviews_disclosing: number;
  accounts_disclosing: number;
  review_rate: number;
  account_rate: number;
  vine_review_rate: number;
  vine_account_rate: number;
  examples: { reviewer_sk: number; doc_id: number; summary: string | null; text: string; match: string }[];
};

type Story = {
  summary: {
    all_accounts: number;
    full_graph_accounts: number;
    suspicious_accounts: number;
    linked_accounts: number;
    links: number;
    clusters: number;
    core_accounts: number;
    core_share: number;
    pack_accounts: number;
    pack_clusters: number;
    core_median_reviews: number;
    pack_median_reviews: number;
    core_median_lifespan: number;
    pack_median_lifespan: number;
    group_reviews: Record<string, number>;
  };
  fragmentation: {
    score_cut: number;
    shared_min: number;
    window: string;
    accounts: number;
    largest: number;
    largest_share: number;
  }[];
  disclosure: { core: Group; packs: Group; control: Group; ratio_core_vs_control: number };
  clusters: { id: number; size: number }[];
};

/** Mark the matched disclosure phrase inside an excerpt, without interpreting markup. */
function Excerpt({ text, match }: { text: string; match: string }) {
  const at = text.toLowerCase().indexOf(match.toLowerCase());
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded-sm bg-chart-4/35 px-0.5 text-foreground">
        {text.slice(at, at + match.length)}
      </mark>
      {text.slice(at + match.length)}
    </>
  );
}

export default async function Page() {
  let data: Story;
  try {
    data = await api<Story>("/story/network");
  } catch (error) {
    if (error instanceof ApiDown) return <ApiError message={error.message} />;
    throw error;
  }
  const s = data.summary;
  const d = data.disclosure;
  const rows = [
    { key: "core", group: d.core, name: "The linked core", tone: "var(--chart-5)",
      note: `${num(s.core_accounts)} suspicious accounts, median ${num(s.core_median_reviews)} reviews each` },
    { key: "control", group: d.control, name: "Comparison group", tone: "var(--muted-foreground)",
      note: `${num(d.control.accounts)} accounts just as prolific, but not suspicious — every one, not a sample` },
    { key: "packs", group: d.packs, name: "The small packs", tone: "var(--chart-4)",
      note: `${num(s.pack_accounts)} suspicious accounts, median ${num(s.pack_median_reviews)} reviews each` },
  ];
  const maxRate = Math.max(...rows.map((r) => r.group.review_rate));
  const minShare = Math.min(...data.fragmentation.map((f) => f.largest_share));
  const maxShare = Math.max(...data.fragmentation.map((f) => f.largest_share));

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">The network of suspicious accounts</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          The full map of who-reviewed-alongside-whom covers {num(s.full_graph_accounts)} accounts
          and is one solid tangle, so drawing it shows nothing. This draws only the most suspicious{" "}
          1% of accounts, linked when two of them reviewed at least three of the same products
          within 30 days — the same rule used to find groups.
        </p>
      </section>

      <section className="grid grid-cols-2 gap-6 rounded-lg border p-5 sm:grid-cols-4">
        <Stat label="Flagged accounts" value={num(s.suspicious_accounts)}
              sub={`top 1% of ${num(s.all_accounts)}`} />
        <Stat label="Linked to another" value={num(s.linked_accounts)}
              sub={`${num(s.links)} links between them`} />
        <Stat label="Separate groups" value={num(s.clusters)}
              sub="clusters with no link to each other" />
        <Stat label="Largest one holds" value={pct(s.core_share, 0)}
              sub={`${num(s.core_accounts)} accounts in one piece`} />
      </section>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Two shapes, not one</CardTitle>
          <CardDescription className="max-w-3xl">
            Most linked accounts fall into one connected mass. The rest form hundreds of small,
            separate groups. These turn out to be different kinds of behaviour, so they are
            drawn separately.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <NetworkExplorer
            packAccounts={s.pack_accounts}
            packClusters={s.pack_clusters}
            coreAccounts={s.core_accounts}
            pairs={data.clusters.filter((c) => c.size === 2).length}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Why are the core accounts linked? Read what they wrote.</CardTitle>
          <CardDescription className="max-w-3xl">
            The network only shows <em>that</em> these accounts keep reviewing the same things at
            the same time. To find out <em>why</em>, their reviews were searched for anyone
            saying they got the product free or discounted in exchange for the review. Up to{" "}
            {SAMPLE} reviews were checked per account.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-3">
            {rows.map((r) => (
              <div key={r.key} className="space-y-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
                  <span className="font-medium">{r.name}</span>
                  <span className="tabular text-muted-foreground">
                    <strong className="text-foreground">{pct(r.group.review_rate, 2)}</strong> of
                    reviews · {pct(r.group.account_rate, 1)} of accounts
                  </span>
                </div>
                <div className="h-3 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.max(0.6, (100 * r.group.review_rate) / maxRate)}%`,
                      backgroundColor: r.tone,
                    }}
                  />
                </div>
                <div className="text-xs text-muted-foreground">{r.note}</div>
              </div>
            ))}
          </div>

          <p className="rounded-md border-l-2 border-chart-5 bg-muted/40 px-4 py-3 text-sm">
            The core says it was given the product{" "}
            <strong>{d.ratio_core_vs_control.toFixed(1)}× as often</strong> as equally active
            accounts that are not suspicious. The small packs almost never say so — far less
            often than the comparison group. The same score flagged two different things: the core
            looks like reviewers who were all sent the same free products, and the packs look
            like groups coordinating quietly.
          </p>

          {d.core.examples.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                In their own words — from the core
              </div>
              {d.core.examples.slice(0, 3).map((x) => (
                <figure key={x.doc_id} className="rounded-md border p-3">
                  <blockquote className="text-sm leading-relaxed text-muted-foreground">
                    <Excerpt text={x.text} match={x.match} />
                  </blockquote>
                  <figcaption className="mt-1.5 text-xs">
                    <Link href={`/reviewers/${x.reviewer_sk}`} className="underline underline-offset-2">
                      open this account
                    </Link>
                  </figcaption>
                </figure>
              ))}
            </div>
          )}

        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">What this does and does not show</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            <strong className="text-foreground">The core is not a drawing choice.</strong> A
            stricter rule for what counts as a link was tried six ways. Every time, the largest
            piece still held {pct(minShare, 0)}–{pct(maxShare, 0)} of the accounts:
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs tabular">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b">
                  <th className="py-1.5 pr-4 font-medium">Suspicion at least</th>
                  <th className="py-1.5 pr-4 font-medium">Shared products at least</th>
                  <th className="py-1.5 pr-4 font-medium">Within</th>
                  <th className="py-1.5 pr-4 font-medium">Linked accounts</th>
                  <th className="py-1.5 font-medium">Largest piece</th>
                </tr>
              </thead>
              <tbody>
                {data.fragmentation.map((f) => (
                  <tr key={`${f.score_cut}-${f.shared_min}-${f.window}`} className="border-b last:border-0">
                    <td className="py-1.5 pr-4">{f.score_cut}</td>
                    <td className="py-1.5 pr-4">{f.shared_min}</td>
                    <td className="py-1.5 pr-4">{f.window === "shared_7d" ? "7 days" : "30 days"}</td>
                    <td className="py-1.5 pr-4">{num(f.accounts)}</td>
                    <td className="py-1.5 text-foreground">
                      {num(f.largest)} ({pct(f.largest_share, 0)})
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="ml-5 list-disc space-y-1">
            <li>
              <strong className="text-foreground">Disclosure is a floor.</strong> Only{" "}
              {pct(d.core.account_rate, 1)} of core accounts ever say they got something free.
              Reviews that were paid for and did not say so cannot be seen, so this explains part
              of the core, not all of it.
            </li>
            <li>
              <strong className="text-foreground">In 2014 this was allowed.</strong> Amazon
              permitted free-product reviews that disclosed it until late 2016. Being in the core
              is not evidence of breaking a rule at the time.
            </li>
            <li>
              <strong className="text-foreground">Amazon&rsquo;s own Vine program is not the
              explanation.</strong> It would also send many reviewers the same products at once,
              but core accounts mention Vine in {pct(d.core.vine_review_rate, 2)} of reviews against{" "}
              {pct(d.control.vine_review_rate, 2)} for the comparison group — about the same.
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

const SAMPLE = 60;
