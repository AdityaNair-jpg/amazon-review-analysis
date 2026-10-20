"use client";

import { useMemo } from "react";
import {
  Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

type Point = {
  day: number;
  n_reviews: number;
  mean_rating: number;
  expected: number;
  z: number;
};

const MAX_MARKS = 2000;

export function ProductTimeline({ series }: { series: Point[] }) {
  // Never hand the browser more marks than it can draw usefully. If a product has
  // more active days than that, aggregate into equal-width buckets rather than
  // dropping points, so no burst can vanish through sampling.
  const { data, bucketed } = useMemo(() => {
    if (series.length <= MAX_MARKS) {
      return { data: series.map((p) => ({ ...p, label: p.day })), bucketed: 0 };
    }
    const width = Math.ceil(series.length / MAX_MARKS);
    const out: (Point & { label: number })[] = [];
    for (let i = 0; i < series.length; i += width) {
      const chunk = series.slice(i, i + width);
      out.push({
        day: chunk[0].day,
        label: chunk[0].day,
        n_reviews: chunk.reduce((a, c) => a + c.n_reviews, 0),
        expected: chunk.reduce((a, c) => a + c.expected, 0),
        mean_rating:
          chunk.reduce((a, c) => a + c.mean_rating * c.n_reviews, 0) /
          Math.max(chunk.reduce((a, c) => a + c.n_reviews, 0), 1),
        z: Math.max(...chunk.map((c) => c.z)),
      });
    }
    return { data: out, bucketed: width };
  }, [series]);

  const peak = useMemo(
    () => data.reduce((best, p) => (p.z > best.z ? p : best), data[0]),
    [data],
  );

  if (!series.length) {
    return <p className="text-sm text-muted-foreground">No dated reviews for this product.</p>;
  }

  return (
    <div className="space-y-2">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <defs>
              <linearGradient id="pt-obs" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={1} />
                <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.45} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="label"
              tickFormatter={(d: number) => new Date(d * 86400_000).toISOString().slice(0, 7)}
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              minTickGap={40}
            />
            <YAxis tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" width={36} />
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
                name === "expected"
                  ? Number(value).toFixed(2)
                  : Number(value).toLocaleString("en-US"),
                name === "n_reviews" ? "observed" : "expected",
              ]}
            />
            <Bar
              dataKey="n_reviews"
              fill="url(#pt-obs)"
              radius={[2, 2, 0, 0]}
              isAnimationActive={false}
            />
            <Line
              dataKey="expected"
              stroke="var(--chart-5)"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted-foreground">
        Peak de-trended z of <span className="tabular font-medium">{peak?.z.toFixed(1)}</span>{" "}
        on {new Date(peak.day * 86400_000).toISOString().slice(0, 10)}.
        {bucketed > 0 && (
          <> Aggregated into {bucketed}-day buckets ({series.length.toLocaleString("en-US")} active
          days would exceed the {MAX_MARKS.toLocaleString("en-US")}-mark budget); buckets sum rather
          than sample, so no burst is hidden.</>
        )}
      </p>
    </div>
  );
}
