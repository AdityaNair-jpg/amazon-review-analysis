"use client";

import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";

type Sizes = Record<string, { accounts: number; n: number }[]>;
type Jaccard = { config: string; j: number; n: number }[];

const SERIES = [
  { key: "exact", label: "Exact duplicate", color: "var(--chart-5)" },
  { key: "loose", label: "Near-dup J ≥ 0.707", color: "var(--chart-2)" },
  { key: "tight", label: "Near-dup J ≥ 0.878", color: "var(--chart-3)" },
];

export function ClusterSizeChart({ sizes, jaccard }: { sizes: Sizes; jaccard: Jaccard }) {
  const [view, setView] = useState<"sizes" | "jaccard">("sizes");

  const sizeData = useMemo(() => {
    const accounts = new Set<number>();
    for (const rows of Object.values(sizes)) rows.forEach((r) => accounts.add(r.accounts));
    return [...accounts]
      .sort((a, b) => a - b)
      .map((k) => {
        const row: Record<string, number> = { accounts: k };
        for (const { key } of SERIES) {
          row[key] = sizes[key]?.find((r) => r.accounts === k)?.n ?? 0;
        }
        return row;
      })
      .filter((r) => SERIES.some((s) => r[s.key] > 0));
  }, [sizes]);

  const jaccardData = useMemo(() => {
    const bins = new Set(jaccard.map((r) => r.j));
    return [...bins]
      .sort((a, b) => a - b)
      .map((j) => ({
        j,
        loose: jaccard.find((r) => r.config === "loose" && r.j === j)?.n ?? 0,
        tight: jaccard.find((r) => r.config === "tight" && r.j === j)?.n ?? 0,
      }));
  }, [jaccard]);

  const multi = SERIES.map((s) => ({
    ...s,
    n: (sizes[s.key] ?? []).filter((r) => r.accounts > 1).reduce((a, r) => a + r.n, 0),
    total: (sizes[s.key] ?? []).reduce((a, r) => a + r.n, 0),
  }));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1">
        <Button
          size="sm"
          variant={view === "sizes" ? "secondary" : "ghost"}
          onClick={() => setView("sizes")}
        >
          Cluster size
        </Button>
        <Button
          size="sm"
          variant={view === "jaccard" ? "secondary" : "ghost"}
          onClick={() => setView("jaccard")}
        >
          Similarity
        </Button>
      </div>

      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {view === "sizes" ? (
            <LineChart data={sizeData} margin={{ top: 8, right: 12, bottom: 22, left: 4 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="accounts"
                scale="log"
                type="number"
                domain={[1, "dataMax"]}
                allowDataOverflow
                tick={{ fontSize: 11 }}
                stroke="var(--muted-foreground)"
                label={{
                  value: "Distinct accounts in the cluster (log)",
                  position: "insideBottom",
                  offset: -14,
                  style: { fontSize: 11, fill: "var(--muted-foreground)" },
                }}
              />
              <YAxis
                scale="log"
                domain={[1, "auto"]}
                allowDataOverflow
                tick={{ fontSize: 11 }}
                stroke="var(--muted-foreground)"
                width={46}
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
                labelFormatter={(v) => `${v} account${Number(v) === 1 ? "" : "s"} per cluster`}
                formatter={(value, name) => [
                  Number(value).toLocaleString("en-US"),
                  SERIES.find((s) => s.key === name)?.label ?? String(name),
                ]}
              />
              <Legend
                verticalAlign="top"
                height={26}
                iconSize={9}
                formatter={(name) => (
                  <span className="text-xs text-muted-foreground">
                    {SERIES.find((s) => s.key === name)?.label ?? name}
                  </span>
                )}
              />
              {SERIES.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={2}
                  dot={{ r: 2.5, strokeWidth: 0 }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          ) : (
            <BarChart data={jaccardData} margin={{ top: 8, right: 12, bottom: 22, left: 4 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="j"
                tick={{ fontSize: 11 }}
                stroke="var(--muted-foreground)"
                tickFormatter={(v) => Number(v).toFixed(2)}
                label={{
                  value: "Mean Jaccard similarity within the cluster",
                  position: "insideBottom",
                  offset: -14,
                  style: { fontSize: 11, fill: "var(--muted-foreground)" },
                }}
              />
              <YAxis
                scale="log"
                domain={[1, "auto"]}
                allowDataOverflow
                tick={{ fontSize: 11 }}
                stroke="var(--muted-foreground)"
                width={46}
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
                labelFormatter={(v) => `Jaccard ≈ ${Number(v).toFixed(2)}`}
                formatter={(value, name) => [
                  Number(value).toLocaleString("en-US"),
                  name === "loose" ? "J ≥ 0.707" : "J ≥ 0.878",
                ]}
              />
              <Legend
                verticalAlign="top"
                height={26}
                iconSize={9}
                formatter={(name) => (
                  <span className="text-xs text-muted-foreground">
                    {name === "loose" ? "J ≥ 0.707" : "J ≥ 0.878"}
                  </span>
                )}
              />
              <Bar
                dataKey="loose"
                fill="var(--chart-2)"
                radius={[3, 3, 0, 0]}
                isAnimationActive={false}
              />
              <Bar
                dataKey="tight"
                fill="var(--chart-3)"
                radius={[3, 3, 0, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>

      <p className="text-xs text-muted-foreground">
        {view === "sizes" ? (
          <>
            Log-log, because cluster sizes are heavy-tailed and a linear axis would compress
            everything interesting into the first pixel. Most clusters are a single account
            reusing its own words;{" "}
            {multi.map((m, i) => (
              <span key={m.key}>
                {i > 0 ? ", " : ""}
                <span className="tabular font-medium">
                  {m.n.toLocaleString("en-US")}
                </span>{" "}
                of {m.total.toLocaleString("en-US")} {m.label.toLowerCase()} clusters span
                more than one
              </span>
            ))}
            . Those are the ones worth reading.
          </>
        ) : (
          <>
            Verified similarity, not the LSH estimate. Every candidate was re-checked by exact
            Jaccard against its cluster exemplar, and 17.7% of loose candidates (20.6% of
            tight) were thrown out at that step. Reporting LSH candidates as findings would
            have inflated the result by about a fifth.
          </>
        )}
      </p>
    </div>
  );
}
