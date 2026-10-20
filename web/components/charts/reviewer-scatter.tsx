"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  CartesianGrid, Cell, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { Button } from "@/components/ui/button";

type Point = {
  reviewer_sk: number;
  band: number;
  score: number;
  max_in_7d: number;
  loo_rating_dev: number;
  n_reviews: number;
  lifespan_days: number;
};

const AXES = {
  burst_vs_deviation: {
    x: "max_in_7d",
    y: "loo_rating_dev",
    xLabel: "Peak reviews in any 7 days",
    yLabel: "Rating deviation from product consensus",
    log: true,
    blurb:
      "The two behavioural features Mukherjee et al. found most discriminating (MNR and RD), plotted against each other. Coordinated accounts should sit up and to the right: many reviews in a short window, and ratings that disagree with everyone else who reviewed the same product.",
  },
  volume_vs_tenure: {
    x: "n_reviews",
    y: "lifespan_days",
    xLabel: "Reviews written",
    yLabel: "Days between first and last review",
    log: true,
    blurb:
      "Volume against tenure. The diagonal is ordinary reviewing — more reviews take more time. The bottom-right corner is what matters: many reviews compressed into a short life. The accounts sitting on the floor of this chart wrote everything they ever wrote inside a single day.",
  },
} as const;

type AxisKey = keyof typeof AXES;

const BAND_COLOR = (band: number) =>
  band >= 9 ? "var(--chart-5)"
    : band >= 8 ? "var(--chart-4)"
      : band >= 6 ? "var(--chart-3)"
        : band >= 4 ? "var(--chart-2)"
          : "var(--chart-1)";

export function ReviewerScatter({ points }: { points: Point[] }) {
  const [axes, setAxes] = useState<AxisKey>("burst_vs_deviation");
  const [minBand, setMinBand] = useState(0);
  const config = AXES[axes];

  const data = useMemo(
    () =>
      points
        .filter((p) => p.band >= minBand)
        .map((p) => ({
          ...p,
          // jitter integers a little so identical values do not stack into one dot
          xv: Math.max(0.6, (p[config.x] as number) * (0.94 + ((p.reviewer_sk % 13) / 100))),
          yv: p[config.y] as number,
        })),
    [points, minBand, config],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="flex items-center gap-1">
          {(Object.keys(AXES) as AxisKey[]).map((key) => (
            <Button
              key={key}
              size="sm"
              variant={axes === key ? "secondary" : "ghost"}
              onClick={() => setAxes(key)}
            >
              {key === "burst_vs_deviation" ? "Burst vs deviation" : "Volume vs tenure"}
            </Button>
          ))}
        </span>
        <span className="flex items-center gap-1 text-xs">
          <span className="text-muted-foreground">Show</span>
          {[
            [0, "all"],
            [6, "top 40%"],
            [9, "top 10%"],
          ].map(([value, label]) => (
            <Button
              key={String(label)}
              size="sm"
              variant={minBand === value ? "secondary" : "ghost"}
              onClick={() => setMinBand(value as number)}
            >
              {label}
            </Button>
          ))}
        </span>
      </div>

      <div className="h-[360px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 10, right: 16, bottom: 28, left: 8 }}>
            <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" />
            <XAxis
              type="number"
              dataKey="xv"
              scale={config.log ? "log" : "linear"}
              domain={config.log ? [0.6, "dataMax"] : ["dataMin", "dataMax"]}
              allowDataOverflow
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              tickFormatter={(v) => {
                const n = Number(v);
                return n >= 1000 ? `${Math.round(n / 1000)}k` : String(Math.round(n));
              }}
              label={{
                value: config.xLabel,
                position: "insideBottom",
                offset: -16,
                style: { fontSize: 11, fill: "var(--muted-foreground)" },
              }}
            />
            <YAxis
              type="number"
              dataKey="yv"
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              width={52}
              tickFormatter={(v) => {
                const n = Number(v);
                return n >= 1000 ? `${Math.round(n / 1000)}k` : n.toFixed(n < 10 ? 1 : 0);
              }}
              label={{
                value: config.yLabel,
                angle: -90,
                position: "insideLeft",
                style: { fontSize: 11, fill: "var(--muted-foreground)", textAnchor: "middle" },
              }}
            />
            <ZAxis range={[10, 10]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as Point;
                return (
                  <div className="rounded-md border bg-popover p-2 text-xs shadow-sm">
                    <div className="tabular font-medium">score {p.score.toFixed(3)}</div>
                    <div className="tabular text-muted-foreground">
                      {p.n_reviews.toLocaleString("en-US")} reviews · peak {p.max_in_7d}/7d ·{" "}
                      {p.lifespan_days.toLocaleString("en-US")}d span
                    </div>
                    <div className="tabular text-muted-foreground">
                      rating deviation {p.loo_rating_dev.toFixed(3)}
                    </div>
                    <div className="mt-1 text-muted-foreground">click to open</div>
                  </div>
                );
              }}
            />
            <Scatter
              data={data}
              isAnimationActive={false}
              onClick={(point) => {
                const id = (point as unknown as { reviewer_sk?: number })?.reviewer_sk;
                if (id !== undefined) window.location.href = `/reviewers/${id}`;
              }}
              className="cursor-pointer"
            >
              {data.map((p) => (
                <Cell
                  key={p.reviewer_sk}
                  fill={BAND_COLOR(p.band)}
                  fillOpacity={p.band >= 9 ? 0.85 : 0.4}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>Suspicion score:</span>
        {[
          [0, "low"],
          [4, ""],
          [6, ""],
          [8, ""],
          [9, "high"],
        ].map(([band, label], i) => (
          <span key={i} className="flex items-center gap-1">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: BAND_COLOR(band as number) }}
            />
            {label}
          </span>
        ))}
        <span className="ml-auto">
          {data.length.toLocaleString("en-US")} accounts shown, sampled evenly across ten score
          bands
        </span>
      </div>

      <p className="text-xs text-muted-foreground">{config.blurb}</p>
      <p className="text-xs text-muted-foreground">
        A uniform random sample would be 99% ordinary accounts and would hide the tail
        completely, so points are drawn evenly from each score decile. That makes the{" "}
        <em>shape</em> of each band readable, but it means the density of dots is not the
        density of accounts. Click any point to open that account.{" "}
        <Link href="/reviewers" className="underline underline-offset-2">
          Browse the full ranking instead
        </Link>
        .
      </p>
    </div>
  );
}
