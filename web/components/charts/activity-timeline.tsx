"use client";

import { useMemo } from "react";
import {
  Cell, ResponsiveContainer, Scatter, ScatterChart, CartesianGrid, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";

type Point = {
  day: number;
  rating: number;
  n_words: number;
  helpful_yes: number;
  helpful_total: number;
  asin: string;
};

const RATING_TONE: Record<number, string> = {
  1: "var(--chart-5)",
  2: "var(--chart-4)",
  3: "var(--chart-3)",
  4: "var(--chart-2)",
  5: "var(--chart-1)",
};

/**
 * One account's whole reviewing history: time on x, rating on y, review length
 * as the mark size.
 *
 * The point is the silhouette. A burst account is a vertical wall; a steady
 * reviewer is a scatter spread across years; an account that suddenly changes
 * rating behaviour shows a visible step. None of that is visible in the summary
 * statistics on the same page.
 */
export function ActivityTimeline({ points }: { points: Point[] }) {
  const data = useMemo(
    () =>
      points.map((p, i) => ({
        ...p,
        // jitter the rating a little so overlapping same-day, same-rating reviews
        // remain countable instead of collapsing into one dot
        y: p.rating + (((i * 37) % 11) - 5) / 42,
        z: Math.max(12, Math.min(160, p.n_words)),
      })),
    [points],
  );

  const stats = useMemo(() => {
    if (!points.length) return null;
    const days = points.map((p) => p.day);
    const lo = Math.min(...days);
    const hi = Math.max(...days);
    const perDay = new Map<number, number>();
    for (const p of points) perDay.set(p.day, (perDay.get(p.day) ?? 0) + 1);
    const busiest = [...perDay.entries()].reduce((a, b) => (b[1] > a[1] ? b : a));
    return { lo, hi, span: hi - lo, busiest, activeDays: perDay.size };
  }, [points]);

  if (!points.length) {
    return <p className="text-sm text-muted-foreground">No dated reviews for this account.</p>;
  }

  return (
    <div className="space-y-2">
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 10, right: 16, bottom: 8, left: 4 }}>
            <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" />
            <XAxis
              type="number"
              dataKey="day"
              domain={["dataMin", "dataMax"]}
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              tickFormatter={(d) =>
                new Date(Number(d) * 86400_000).toISOString().slice(0, 7)
              }
              minTickGap={44}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[0.5, 5.5]}
              ticks={[1, 2, 3, 4, 5]}
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              width={32}
              tickFormatter={(v) => `${v}★`}
            />
            <ZAxis type="number" dataKey="z" range={[14, 150]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as Point;
                return (
                  <div className="rounded-md border bg-popover p-2 text-xs shadow-sm">
                    <div className="tabular font-medium">
                      {new Date(p.day * 86400_000).toISOString().slice(0, 10)} · {p.rating}★
                    </div>
                    <div className="font-mono text-muted-foreground">{p.asin}</div>
                    <div className="tabular text-muted-foreground">
                      {p.n_words} words
                      {p.helpful_total > 0
                        ? ` · ${p.helpful_yes}/${p.helpful_total} helpful`
                        : ""}
                    </div>
                  </div>
                );
              }}
            />
            <Scatter data={data} isAnimationActive={false}>
              {data.map((p, i) => (
                <Cell
                  key={i}
                  fill={RATING_TONE[p.rating] ?? "var(--chart-1)"}
                  fillOpacity={0.55}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted-foreground">
        Every dated review: mark size is review length, colour is the rating.{" "}
        {stats && (
          <>
            <span className="tabular font-medium">
              {points.length.toLocaleString("en-US")}
            </span>{" "}
            reviews across{" "}
            <span className="tabular font-medium">
              {stats.activeDays.toLocaleString("en-US")}
            </span>{" "}
            active days spanning{" "}
            <span className="tabular font-medium">
              {stats.span.toLocaleString("en-US")}
            </span>{" "}
            days; the busiest single day carried{" "}
            <span className="tabular font-medium">{stats.busiest[1]}</span> of them
            {stats.busiest[1] >= 10 ? ", which is the burst signal in raw form" : ""}.
          </>
        )}
      </p>
    </div>
  );
}
