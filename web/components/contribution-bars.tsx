import { FAMILY, FAMILY_ORDER, featureHint, featureLabel } from "@/lib/labels";

/**
 * What pushed one account's score up, in words rather than column names.
 *
 * Each bar is the account's percentile on one measurement: "higher than 97% of
 * all accounts" is something a reader can act on, where the raw value of
 * `loo_rating_dev` is not.
 */
export function ContributionBars({
  contributions,
}: {
  contributions: { feature: string; percentile: number; family: string }[];
}) {
  const groups = FAMILY_ORDER.filter((f) => contributions.some((c) => c.family === f));

  return (
    <div className="space-y-5">
      {groups.map((key) => {
        const family = FAMILY[key];
        const rows = contributions
          .filter((c) => c.family === key)
          .sort((a, b) => b.percentile - a.percentile);
        const top = rows[0];

        return (
          <div key={key} className="space-y-2">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: family.tone }}
                />
                {family.name}
              </span>
              {top && (
                <span className="text-xs text-muted-foreground">
                  strongest signal: {featureLabel(top.feature).toLowerCase()} &mdash; higher
                  than{" "}
                  <span className="tabular">{((top.percentile ?? 0) * 100).toFixed(0)}%</span>{" "}
                  of accounts
                </span>
              )}
            </div>

            {rows.map((c) => {
              const pct = (c.percentile ?? 0) * 100;
              return (
                <div
                  key={c.feature}
                  className="flex items-center gap-3 text-xs"
                  title={featureHint(c.feature)}
                >
                  <span className="w-56 shrink-0 truncate">{featureLabel(c.feature)}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${pct}%`, backgroundColor: family.tone }}
                    />
                  </div>
                  <span className="w-28 shrink-0 text-right tabular text-muted-foreground">
                    top {(100 - pct).toFixed(0)}%
                  </span>
                </div>
              );
            })}
          </div>
        );
      })}

      <p className="border-t pt-3 text-xs text-muted-foreground">
        Read a bar as &ldquo;this account is more extreme on this than X% of all 3,035,045
        accounts&rdquo;. Hover any row for what it measures. Long bars in{" "}
        <em>more than one colour</em> are what makes an account genuinely unusual &mdash; long
        bars in only one colour usually have an innocent explanation.
      </p>
    </div>
  );
}
