"use client";

import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";

type Row = {
  k: number;
  pair: string;
  observed: number;
  expected: number;
  lift: number | null;
  informative: boolean;
};

/**
 * Observed overlap between the signal families against what chance alone predicts.
 *
 * Plotted on a log axis with observed and expected side by side, because the
 * claim being made is a ratio ("seven times chance"), and a ratio is only
 * readable when both terms are visible. Cut-offs where the chance expectation
 * is below five are drawn muted and labelled uninformative rather than silently
 * shown as an impressive-looking zero.
 */
export function AgreementChart({
  rows,
  spearman,
}: {
  rows: Row[];
  spearman: Record<string, number>;
}) {
  const ks = useMemo(() => [...new Set(rows.map((r) => r.k))].sort((a, b) => a - b), [rows]);
  const [k, setK] = useState(() => ks[Math.min(2, ks.length - 1)] ?? ks[0]);

  const data = rows.filter((r) => r.k === k);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1">
        <span className="mr-2 text-xs text-muted-foreground">Top-k cut-off</span>
        {ks.map((value) => (
          <Button
            key={value}
            size="sm"
            variant={k === value ? "secondary" : "ghost"}
            onClick={() => setK(value)}
          >
            {value.toLocaleString("en-US")}
          </Button>
        ))}
      </div>

      <div className="h-60 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <defs>
              <linearGradient id="agr-obs" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={1} />
                <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.55} />
              </linearGradient>
              <linearGradient id="agr-all" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-5)" stopOpacity={1} />
                <stop offset="100%" stopColor="var(--chart-5)" stopOpacity={0.55} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="pair"
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
            />
            <YAxis
              scale="log"
              domain={[0.1, "auto"]}
              allowDataOverflow
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              width={48}
              tickFormatter={(v) =>
                Number(v) >= 1000 ? `${Math.round(Number(v) / 1000)}k` : String(Number(v))
              }
            />
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(value, name) => [
                Number(value).toLocaleString("en-US", { maximumFractionDigits: 1 }),
                name === "observed" ? "observed" : "expected by chance",
              ]}
            />
            <Legend
              verticalAlign="top"
              height={26}
              iconSize={9}
              formatter={(name) => (
                <span className="text-xs text-muted-foreground">
                  {name === "observed" ? "observed overlap" : "expected by chance"}
                </span>
              )}
            />
            <Bar
              dataKey="expected"
              fill="var(--muted-foreground)"
              radius={[3, 3, 0, 0]}
              isAnimationActive={false}
            >
              {data.map((r) => (
                <Cell key={`e-${r.pair}`} fillOpacity={r.informative ? 0.45 : 0.18} />
              ))}
            </Bar>
            <Bar dataKey="observed" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {data.map((r) => (
                <Cell
                  key={`o-${r.pair}`}
                  fill={r.pair === "all three" ? "url(#agr-all)" : "url(#agr-obs)"}
                  fillOpacity={r.informative ? 0.9 : 0.3}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid gap-2 text-xs sm:grid-cols-2">
        <ul className="space-y-1">
          {data.map((r) => (
            <li key={r.pair} className="flex items-baseline justify-between gap-2 border-b py-1">
              <span className="text-muted-foreground">{r.pair}</span>
              <span className="tabular">
                {r.informative ? (
                  <>
                    {r.observed.toLocaleString("en-US")} vs{" "}
                    {r.expected.toLocaleString("en-US", { maximumFractionDigits: 1 })}{" "}
                    <strong>({r.lift}×)</strong>
                  </>
                ) : (
                  <span className="text-muted-foreground">
                    {r.observed.toLocaleString("en-US")} observed — chance expectation below
                    5, not informative
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
        <ul className="space-y-1">
          {Object.entries(spearman).map(([key, value]) => (
            <li key={key} className="flex items-baseline justify-between gap-2 border-b py-1">
              <span className="text-muted-foreground">
                Spearman {key.replace("spearman_", "").split("").join(" ↔ ")}
              </span>
              <span className="tabular">{value.toFixed(4)}</span>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-xs text-muted-foreground">
        The families share no input feature, so overlap between them is evidence rather than
        circularity. They do agree above chance — but the rank correlations are low
        (0.04&ndash;0.16), so they are largely finding different accounts. At small cut-offs
        the chance expectation drops below one account and the comparison stops meaning
        anything; those bars are dimmed and labelled rather than presented as a result.
      </p>
    </div>
  );
}
