"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";

type Bin = { family: string; bin_lo: number; bin_hi: number; n: number };

const FAMILIES = [
  { key: "all", label: "Consensus", tone: "var(--chart-1)" },
  { key: "any", label: "Any family", tone: "var(--chart-4)" },
  { key: "T", label: "Text", tone: "var(--chart-2)" },
  { key: "B", label: "Behaviour", tone: "var(--chart-3)" },
  { key: "G", label: "Graph", tone: "var(--chart-5)" },
];

export function ScoreExplorer({
  histogram,
  totalReviewers,
}: {
  histogram: Bin[];
  totalReviewers: number;
}) {
  const [family, setFamily] = useState("all");
  const [threshold, setThreshold] = useState(0.99);
  const tone = FAMILIES.find((f) => f.key === family)?.tone ?? "var(--chart-1)";

  const available = useMemo(
    () => FAMILIES.filter((f) => histogram.some((b) => b.family === f.key)),
    [histogram],
  );

  const bins = useMemo(
    () =>
      histogram
        .filter((b) => b.family === family)
        .sort((a, b) => a.bin_lo - b.bin_lo)
        // Recharts' log axis cannot plot a zero, and an empty bin is genuinely
        // "no accounts" rather than "one account" -- clamping to 1 would draw a
        // floor that is not in the data, so empty bins are simply left out.
        .map((b) => ({ ...b, mid: (b.bin_lo + b.bin_hi) / 2 }))
        .filter((b) => b.n > 0),
    [histogram, family],
  );

  // Exact, because these are the same 200 buckets the pipeline wrote: no round trip.
  const above = useMemo(
    () => bins.filter((b) => b.bin_lo >= threshold).reduce((a, b) => a + b.n, 0),
    [bins, threshold],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1">
        {available.map((f) => (
          <Button
            key={f.key}
            size="sm"
            variant={family === f.key ? "secondary" : "ghost"}
            onClick={() => setFamily(f.key)}
          >
            <span
              className="mr-1.5 inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: f.tone }}
            />
            {f.label}
          </Button>
        ))}
      </div>

      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={bins} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
            <defs>
              <linearGradient id="score-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={tone} stopOpacity={0.55} />
                <stop offset="100%" stopColor={tone} stopOpacity={0.06} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="mid"
              type="number"
              domain={[0, 1]}
              ticks={[0, 0.25, 0.5, 0.75, 1]}
              tickFormatter={(v) => Number(v).toFixed(2)}
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
            />
            <YAxis
              scale="log"
              domain={[1, "auto"]}
              allowDataOverflow
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              width={44}
              tickFormatter={(v) => {
                const n = Number(v);
                return n >= 1e6 ? `${n / 1e6}M` : n >= 1e3 ? `${n / 1e3}k` : String(n);
              }}
            />
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelFormatter={(v) => `score ≈ ${Number(v).toFixed(3)}`}
              formatter={(v) => [Number(v).toLocaleString("en-US"), "accounts"]}
            />
            <ReferenceArea
              x1={threshold}
              x2={1}
              fill="var(--chart-5)"
              fillOpacity={0.08}
              stroke="none"
            />
            <ReferenceLine x={threshold} stroke="var(--chart-5)" strokeDasharray="4 3" />
            <Area
              type="monotone"
              dataKey="n"
              stroke={tone}
              strokeWidth={1.6}
              fill="url(#score-fill)"
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted-foreground">
        Log-scaled count axis. Without it the bulk of ordinary accounts flattens the tail that
        actually matters — and the tail is the entire point of the chart.
      </p>

      <div className="space-y-3 rounded-lg border bg-muted/30 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <span className="text-sm text-muted-foreground">
            Threshold{" "}
            <span className="tabular font-medium text-foreground">{threshold.toFixed(3)}</span>
          </span>
          <span className="text-sm">
            <span className="tabular text-xl font-semibold">
              {above.toLocaleString("en-US")}
            </span>{" "}
            <span className="text-muted-foreground">
              accounts above ({((above / totalReviewers) * 100).toFixed(3)}% of{" "}
              {totalReviewers.toLocaleString("en-US")})
            </span>
          </span>
        </div>
        <Slider
          value={[threshold]}
          onValueChange={([v]) => setThreshold(v)}
          min={0}
          max={0.995}
          step={0.005}
        />
        <Link
          href={`/reviewers?min_score=${threshold.toFixed(3)}`}
          className="inline-block text-sm underline underline-offset-4 hover:no-underline"
        >
          Inspect these accounts &rarr;
        </Link>
      </div>
    </div>
  );
}
