"use client";

import {
  Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

type Decile = {
  decile: number;
  n_reviews: number;
  mean_rating: number;
  frac_5: number;
  frac_1: number;
  frac_extreme: number;
};

/**
 * Rating behaviour across suspicion deciles.
 *
 * This is the chart that earns the score its credibility, because it is not
 * circular: NO rating level enters the score at all (a unit test enforces it),
 * so the gradient here is an independent relationship the model was never told
 * about.
 */
export function DecileChart({ deciles }: { deciles: Decile[] }) {
  const data = deciles.map((d) => ({
    ...d,
    five: d.frac_5 * 100,
    one: d.frac_1 * 100,
  }));
  const lo = data[0];
  const hi = data[data.length - 1];

  return (
    <div className="space-y-3">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 44, bottom: 4, left: 4 }}>
            <defs>
              <linearGradient id="dec-five" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-2)" stopOpacity={1} />
                <stop offset="100%" stopColor="var(--chart-2)" stopOpacity={0.5} />
              </linearGradient>
              <linearGradient id="dec-one" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-5)" stopOpacity={1} />
                <stop offset="100%" stopColor="var(--chart-5)" stopOpacity={0.5} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="decile"
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              tickFormatter={(v) => `D${v}`}
            />
            <YAxis
              yAxisId="pct"
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              width={40}
              domain={[0, 80]}
              tickFormatter={(v) => `${v}%`}
            />
            <YAxis
              yAxisId="mean"
              orientation="right"
              tick={{ fontSize: 11 }}
              stroke="var(--chart-1)"
              width={40}
              domain={[3.8, 4.5]}
              tickFormatter={(v) => Number(v).toFixed(1)}
            />
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelFormatter={(d) => `Suspicion decile ${d} of 10`}
              formatter={(value, name) =>
                name === "mean_rating"
                  ? [Number(value).toFixed(3), "mean rating"]
                  : [`${Number(value).toFixed(1)}%`, name === "five" ? "five-star" : "one-star"]
              }
            />
            <Legend
              verticalAlign="top"
              height={26}
              iconSize={9}
              formatter={(name) => (
                <span className="text-xs text-muted-foreground">
                  {name === "five" ? "five-star share" : name === "one" ? "one-star share" : "mean rating"}
                </span>
              )}
            />
            <Bar
              yAxisId="pct"
              dataKey="five"
              fill="url(#dec-five)"
              radius={[3, 3, 0, 0]}
              isAnimationActive={false}
            />
            <Bar
              yAxisId="pct"
              dataKey="one"
              fill="url(#dec-one)"
              radius={[3, 3, 0, 0]}
              isAnimationActive={false}
            />
            <Line
              yAxisId="mean"
              type="monotone"
              dataKey="mean_rating"
              stroke="var(--chart-1)"
              strokeWidth={2}
              dot={{ r: 3, fill: "var(--background)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted-foreground">
        Decile 1 is the least suspicious tenth of accounts, decile 10 the most. Five-star share
        climbs monotonically from{" "}
        <span className="tabular font-medium">{lo?.frac_5 !== undefined ? `${(lo.frac_5 * 100).toFixed(1)}%` : "—"}</span>{" "}
        to{" "}
        <span className="tabular font-medium">{hi?.frac_5 !== undefined ? `${(hi.frac_5 * 100).toFixed(1)}%` : "—"}</span>{" "}
        while one-star share falls from{" "}
        <span className="tabular font-medium">{lo?.frac_1 !== undefined ? `${(lo.frac_1 * 100).toFixed(1)}%` : "—"}</span>{" "}
        to{" "}
        <span className="tabular font-medium">{hi?.frac_1 !== undefined ? `${(hi.frac_1 * 100).toFixed(1)}%` : "—"}</span>.
        <strong className="text-foreground"> This is not circular.</strong> No rating level
        enters the score — a unit test fails the build if one does — so the gradient is a
        relationship the model was never given.
      </p>
    </div>
  );
}
