"use client";

import { useState } from "react";

const FAMILY_TONE: Record<string, string> = {
  T: "var(--chart-2)",
  B: "var(--chart-3)",
  G: "var(--chart-4)",
};

/**
 * Feature correlation heatmap, diverging around zero.
 *
 * The diverging scale is the whole point: positive and negative correlation are
 * opposite claims, so they must not share a colour ramp. Zero is transparent, so
 * an uncorrelated pair recedes and only real structure draws the eye.
 *
 * Cells the API could not measure — pairs with too few rows where either feature
 * is non-zero — are hatched rather than coloured. Most graph and duplicate
 * features are zero for over 99% of accounts, and a correlation computed across
 * that mass of shared zeros is an artifact of sparsity, not a relationship.
 */
function tone(value: number): string {
  // Rounded to two decimals before interpolation. Math.pow can disagree in the
  // final digit between the Node build that server-renders this and the browser
  // build that hydrates it, and an unrounded percentage bakes that difference
  // into the style string -- 441 cells, 441 hydration mismatches.
  const alpha = (Math.min(1, Math.abs(value)) ** 0.7 * 100).toFixed(2);
  const hue = value >= 0 ? "var(--chart-5)" : "var(--chart-1)";
  return `color-mix(in oklab, ${hue} ${alpha}%, transparent)`;
}

const HATCH =
  "repeating-linear-gradient(45deg, var(--muted) 0 3px, transparent 3px 6px)";

export function CorrelationHeatmap({
  features,
  families,
  matrix,
  activeRows,
  threshold = 0.85,
  minActive = 2000,
}: {
  features: string[];
  families: Record<string, string>;
  matrix: (number | null)[][];
  activeRows?: number[][];
  threshold?: number;
  minActive?: number;
}) {
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null);
  const n = features.length;

  const offenders: [string, string, number][] = [];
  let unmeasurable = 0;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const v = matrix[i][j];
      if (v === null) unmeasurable++;
      else if (Math.abs(v) > threshold) offenders.push([features[i], features[j], v]);
    }
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <div className="inline-block min-w-min">
          <div
            className="grid gap-px"
            style={{ gridTemplateColumns: `168px repeat(${n}, 18px)` }}
          >
            <div />
            {features.map((f, j) => (
              <div key={`h-${f}`} className="h-[110px] w-[18px]" title={f}>
                <div
                  className="origin-bottom-left translate-x-[13px] translate-y-[104px] -rotate-90 whitespace-nowrap text-[10px]"
                  style={{ color: FAMILY_TONE[families[f]] ?? "var(--muted-foreground)" }}
                >
                  {f}
                </div>
              </div>
            ))}

            {features.map((rowName, i) => (
              <div key={rowName} className="contents">
                <div
                  className="flex h-[18px] items-center justify-end pr-2 text-[10px]"
                  style={{
                    color: FAMILY_TONE[families[rowName]] ?? "var(--muted-foreground)",
                  }}
                >
                  {rowName}
                </div>
                {features.map((colName, j) => {
                  const v = matrix[i][j];
                  const rows = activeRows?.[i]?.[j];
                  const active = hover && (hover.i === i || hover.j === j);
                  return (
                    <div
                      key={`${rowName}-${colName}`}
                      className="h-[18px] w-[18px] rounded-[2px]"
                      style={{
                        // Longhands, not the `background` shorthand: React
                        // serialises the shorthand verbatim while the browser
                        // expands it, and every cell then reports a hydration
                        // mismatch.
                        backgroundColor:
                          i === j ? "var(--muted)" : v === null ? undefined : tone(v),
                        backgroundImage: v === null && i !== j ? HATCH : undefined,
                        outline: active ? "1px solid var(--ring)" : undefined,
                      }}
                      title={
                        v === null
                          ? `${rowName} × ${colName}: not measurable (only ${(rows ?? 0).toLocaleString("en-US")} rows where either is non-zero)`
                          : `${rowName} × ${colName} = ${v.toFixed(3)} over ${(rows ?? 0).toLocaleString("en-US")} active rows`
                      }
                      onMouseEnter={() => setHover({ i, j })}
                      onMouseLeave={() => setHover(null)}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="h-3 w-6 rounded-sm" style={{ backgroundColor: tone(-1) }} />
          −1
        </span>
        <span className="flex items-center gap-1">
          <span className="h-3 w-6 rounded-sm border" style={{ backgroundColor: tone(0) }} />0
        </span>
        <span className="flex items-center gap-1">
          <span className="h-3 w-6 rounded-sm" style={{ backgroundColor: tone(1) }} />
          +1
        </span>
        <span className="flex items-center gap-1">
          <span className="h-3 w-6 rounded-sm" style={{ backgroundImage: HATCH }} />
          not measurable
        </span>
        <span className="flex items-center gap-3">
          {Object.entries(FAMILY_TONE).map(([k, c]) => (
            <span key={k} className="flex items-center gap-1">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: c }} />
              {k === "T" ? "Text" : k === "B" ? "Behaviour" : "Graph"}
            </span>
          ))}
        </span>
        {hover && (
          <span className="ml-auto tabular">
            {features[hover.i]} × {features[hover.j]} ={" "}
            {matrix[hover.i][hover.j]?.toFixed(3) ?? "n/a"}
          </span>
        )}
      </div>

      <div className="space-y-2 text-xs text-muted-foreground">
        <p>
          Correlation between the {n} features that survived the cull, computed on their
          percentile-transformed values. Diverging scale: positive and negative correlation are
          opposite claims and do not share a ramp, and zero is transparent so only real
          structure draws the eye.
        </p>
        <p>
          Each cell is measured on its pair&rsquo;s <strong>active subset</strong> &mdash; rows
          where at least one of the two features is non-zero &mdash; which is exactly what the
          cull in <code className="font-mono">09_score.py</code> does. That is not a detail.
          Most graph and duplicate features are zero for well over 99% of accounts, and a
          correlation taken across that mass of shared zeros comes back at 1.000 for{" "}
          <em>any</em> two sparse features regardless of whether they carry the same signal.
          Measuring this chart over the whole population while the cull measured the active
          subset would make the chart accuse the cull of a bug it does not have.
          {unmeasurable > 0 && (
            <>
              {" "}
              {unmeasurable} pair{unmeasurable === 1 ? "" : "s"} had fewer than{" "}
              {minActive.toLocaleString("en-US")} active rows and are hatched rather than
              given a number.
            </>
          )}
        </p>
        <p>
          {offenders.length === 0 ? (
            <>
              No surviving pair exceeds the |ρ| &gt; {threshold} cull threshold, which is what
              the cull was for &mdash; without it, &ldquo;writes a lot&rdquo; would enter the
              score three times under three names and silently triple its own weight.
            </>
          ) : (
            <span className="text-destructive">
              {offenders.length} surviving pair(s) exceed |ρ| &gt; {threshold}:{" "}
              {offenders.map(([a, b, v]) => `${a}×${b} (${v.toFixed(2)})`).join(", ")}. That is
              a bug in the cull, not a feature.
            </span>
          )}
        </p>
      </div>
    </div>
  );
}
