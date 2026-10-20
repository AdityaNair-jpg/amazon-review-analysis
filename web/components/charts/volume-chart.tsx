"use client";

import { useMemo, useState } from "react";
import {
  Area, AreaChart, CartesianGrid, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";

type Point = {
  day: number;
  r1: number; r2: number; r3: number; r4: number; r5: number;
  total: number;
  mean_rating: number;
};

const BANDS = [
  { key: "r1", label: "1★", color: "var(--chart-5)" },
  { key: "r2", label: "2★", color: "var(--chart-4)" },
  { key: "r3", label: "3★", color: "var(--chart-3)" },
  { key: "r4", label: "4★", color: "var(--chart-2)" },
  { key: "r5", label: "5★", color: "var(--chart-1)" },
];

const year = (d: number) => new Date(d * 86400_000).getUTCFullYear();

export function VolumeChart({ series }: { series: Point[] }) {
  const [mode, setMode] = useState<"stacked" | "share">("stacked");

  const data = useMemo(
    () =>
      series.map((p) => {
        if (mode === "stacked") return { ...p, label: p.day };
        const t = p.total || 1;
        return {
          ...p,
          label: p.day,
          r1: p.r1 / t, r2: p.r2 / t, r3: p.r3 / t, r4: p.r4 / t, r5: p.r5 / t,
        };
      }),
    [series, mode],
  );

  const peak = useMemo(
    () => series.reduce((best, p) => (p.total > best.total ? p : best), series[0]),
    [series],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1">
        <Button
          size="sm"
          variant={mode === "stacked" ? "secondary" : "ghost"}
          onClick={() => setMode("stacked")}
        >
          Volume
        </Button>
        <Button
          size="sm"
          variant={mode === "share" ? "secondary" : "ghost"}
          onClick={() => setMode("share")}
        >
          Share of reviews
        </Button>
      </div>

      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <defs>
              {BANDS.map((b) => (
                <linearGradient key={b.key} id={`vol-${b.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={b.color} stopOpacity={0.9} />
                  <stop offset="100%" stopColor={b.color} stopOpacity={0.55} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="label"
              tickFormatter={(d) => String(year(Number(d)))}
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              minTickGap={32}
            />
            <YAxis
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              width={48}
              tickFormatter={(v) =>
                mode === "share"
                  ? `${Math.round(Number(v) * 100)}%`
                  : Number(v) >= 1e6
                    ? `${(Number(v) / 1e6).toFixed(1)}M`
                    : `${Math.round(Number(v) / 1e3)}k`
              }
            />
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelFormatter={(d) =>
                new Date(Number(d) * 86400_000).toISOString().slice(0, 10)
              }
              formatter={(value, name) => [
                mode === "share"
                  ? `${(Number(value) * 100).toFixed(1)}%`
                  : Number(value).toLocaleString("en-US"),
                BANDS.find((b) => b.key === name)?.label ?? String(name),
              ]}
            />
            <Legend
              verticalAlign="top"
              height={28}
              iconSize={9}
              formatter={(name) => (
                <span className="text-xs text-muted-foreground">
                  {BANDS.find((b) => b.key === name)?.label ?? name}
                </span>
              )}
            />
            {BANDS.map((b) => (
              <Area
                key={b.key}
                type="monotone"
                dataKey={b.key}
                stackId="1"
                stroke={b.color}
                fill={`url(#vol-${b.key})`}
                strokeWidth={0.6}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <p className="text-xs text-muted-foreground">
        {mode === "stacked" ? (
          <>
            Peak bucket:{" "}
            <span className="tabular font-medium">
              {peak?.total.toLocaleString("en-US")}
            </span>{" "}
            reviews around {new Date(peak.day * 86400_000).toISOString().slice(0, 7)}. The
            corpus is overwhelmingly recent — 2013 alone carries 14.79M of 41.1M reviews —
            which is exactly why burst detection has to be de-trended against this curve
            rather than run on raw counts.
          </>
        ) : (
          <>
            As a share, the rating mix is remarkably stable across eighteen years. The
            five-star fraction drifts but never collapses, so a rating <em>level</em> carries
            almost no information about when a review was written — or about whether it is
            genuine.
          </>
        )}
      </p>
    </div>
  );
}
