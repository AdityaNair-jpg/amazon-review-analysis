"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const COLORS: Record<number, string> = {
  1: "var(--chart-5)",
  2: "var(--chart-4)",
  3: "var(--chart-3)",
  4: "var(--chart-2)",
  5: "var(--chart-1)",
};

/**
 * Rating mix as a donut with direct labels around it.
 *
 * Five slices is about the limit of what a pie can communicate, and a rating
 * scale is genuinely a part-of-whole with a natural order, so it is one of the
 * few places a donut beats a bar. The numbers are printed next to it regardless,
 * because nobody can read an angle to two decimal places.
 */
export function RatingDonut({
  ratings,
  height = 220,
  caption,
}: {
  ratings: { rating: number; n: number }[];
  height?: number;
  caption?: React.ReactNode;
}) {
  const total = ratings.reduce((a, r) => a + r.n, 0) || 1;
  const data = [...ratings].sort((a, b) => b.rating - a.rating);
  const mean = ratings.reduce((a, r) => a + r.rating * r.n, 0) / total;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4">
        <div style={{ height, width: height }} className="relative shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="n"
                nameKey="rating"
                innerRadius="58%"
                outerRadius="92%"
                paddingAngle={1.5}
                stroke="var(--background)"
                strokeWidth={2}
                isAnimationActive={false}
              >
                {data.map((d) => (
                  <Cell key={d.rating} fill={COLORS[d.rating]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(value, name) => [
                  `${Number(value).toLocaleString("en-US")} (${((Number(value) / total) * 100).toFixed(2)}%)`,
                  `${name}★`,
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="tabular text-xl font-semibold leading-none">
              {mean.toFixed(2)}
            </span>
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              mean
            </span>
          </div>
        </div>

        <ul className="min-w-[150px] flex-1 space-y-1">
          {data.map((d) => (
            <li key={d.rating} className="flex items-center gap-2 text-xs">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ backgroundColor: COLORS[d.rating] }}
              />
              <span className="w-7 tabular text-muted-foreground">{d.rating}★</span>
              <span className="flex-1 tabular">{((d.n / total) * 100).toFixed(2)}%</span>
              <span className="tabular text-muted-foreground">
                {d.n.toLocaleString("en-US")}
              </span>
            </li>
          ))}
        </ul>
      </div>
      {caption ? <p className="text-xs text-muted-foreground">{caption}</p> : null}
    </div>
  );
}
