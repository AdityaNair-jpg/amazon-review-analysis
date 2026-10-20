"use client";

import { useMemo, useState } from "react";

type Product = {
  product_sk: number;
  asin: string;
  n_reviews: number;
  n_members: number;
  first_day: number;
  last_day: number;
  mean_rating: number;
};
type Review = { product_sk: number; reviewer_sk: number; day: number; rating: number };
type Member = { reviewer_sk: number; reviewerID: string };

const RATING_TONE: Record<number, string> = {
  1: "var(--chart-5)",
  2: "var(--chart-4)",
  3: "var(--chart-3)",
  4: "var(--chart-2)",
  5: "var(--chart-1)",
};

const iso = (day: number) => new Date(day * 86400_000).toISOString().slice(0, 10);

/**
 * The ring exhibit: one row per product, one dot per member review, placed on a
 * shared time axis.
 *
 * A ring reads as vertical stacks — many different accounts hitting the same
 * product within days of each other. Ordinary shared interest reads as dots
 * scattered along the row. No table of aggregates makes that distinction as
 * quickly, which is why this is drawn rather than tabulated.
 *
 * Hand-rolled SVG rather than a chart library: this is a categorical-y
 * strip plot with one mark per observation, which every general charting library
 * makes harder than plain coordinates.
 */
export function RingConvergence({
  products,
  reviews,
  members,
}: {
  products: Product[];
  reviews: Review[];
  members: Member[];
}) {
  const [hovered, setHovered] = useState<Review | null>(null);

  const layout = useMemo(() => {
    if (!products.length || !reviews.length) return null;
    const rowH = 18;
    const padL = 116;
    const padR = 16;
    const padT = 26;
    const padB = 30;
    const width = 860;
    const height = padT + products.length * rowH + padB;

    const days = reviews.map((r) => r.day);
    const lo = Math.min(...days);
    const hi = Math.max(...days);
    const span = Math.max(1, hi - lo);
    const x = (day: number) => padL + ((day - lo) / span) * (width - padL - padR);

    const rowOf = new Map(products.map((p, i) => [p.product_sk, i]));
    const memberIndex = new Map(members.map((m, i) => [m.reviewer_sk, i]));

    // year gridlines
    const ticks: { day: number; label: string }[] = [];
    const startYear = new Date(lo * 86400_000).getUTCFullYear();
    const endYear = new Date(hi * 86400_000).getUTCFullYear();
    for (let y = startYear; y <= endYear; y++) {
      const day = Math.round(Date.UTC(y, 0, 1) / 86400_000);
      if (day >= lo && day <= hi) ticks.push({ day, label: String(y) });
    }
    if (ticks.length < 2) {
      ticks.length = 0;
      ticks.push({ day: lo, label: iso(lo) }, { day: hi, label: iso(hi) });
    }

    return { rowH, padL, padT, width, height, x, rowOf, memberIndex, ticks, lo, hi, span };
  }, [products, reviews, members]);

  if (!layout) {
    return (
      <p className="text-sm text-muted-foreground">
        No product is shared by more than one member of this ring.
      </p>
    );
  }

  const { rowH, padL, padT, width, height, x, rowOf, ticks } = layout;
  const tightest = products.reduce(
    (best, p) => (p.last_day - p.first_day < best.last_day - best.first_day ? p : best),
    products[0],
  );

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full min-w-[720px]">
          {ticks.map((t) => (
            <g key={t.day}>
              <line
                x1={x(t.day)}
                y1={padT - 6}
                x2={x(t.day)}
                y2={height - 24}
                stroke="var(--border)"
                strokeDasharray="2 4"
              />
              <text
                x={x(t.day)}
                y={height - 10}
                fontSize="10"
                textAnchor="middle"
                className="fill-muted-foreground"
              >
                {t.label}
              </text>
            </g>
          ))}

          {products.map((p, i) => {
            const y = padT + i * rowH + rowH / 2;
            return (
              <g key={p.product_sk}>
                <rect
                  x={0}
                  y={padT + i * rowH}
                  width={width}
                  height={rowH}
                  fill={i % 2 ? "var(--muted)" : "transparent"}
                  fillOpacity={i % 2 ? 0.35 : 0}
                />
                <text x={4} y={y + 3.5} fontSize="10" className="fill-foreground font-mono">
                  {p.asin}
                </text>
                <text
                  x={padL - 8}
                  y={y + 3.5}
                  fontSize="9"
                  textAnchor="end"
                  className="fill-muted-foreground"
                >
                  {p.n_members}×
                </text>
                {/* the span this product was hit over */}
                <line
                  x1={x(p.first_day)}
                  y1={y}
                  x2={x(p.last_day)}
                  y2={y}
                  stroke="var(--chart-1)"
                  strokeOpacity={0.35}
                  strokeWidth={2}
                />
              </g>
            );
          })}

          {reviews.map((r, i) => {
            const row = rowOf.get(r.product_sk);
            if (row === undefined) return null;
            const y = padT + row * rowH + rowH / 2;
            return (
              <circle
                key={i}
                cx={x(r.day)}
                cy={y}
                r={3.4}
                fill={RATING_TONE[r.rating] ?? "var(--chart-1)"}
                fillOpacity={0.9}
                stroke="var(--background)"
                strokeWidth={0.8}
                onMouseEnter={() => setHovered(r)}
                onMouseLeave={() => setHovered(null)}
              />
            );
          })}
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>Rating:</span>
        {[1, 2, 3, 4, 5].map((r) => (
          <span key={r} className="flex items-center gap-1">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: RATING_TONE[r] }}
            />
            {r}★
          </span>
        ))}
        {hovered && (
          <span className="ml-auto tabular">
            {iso(hovered.day)} · {hovered.rating}★
          </span>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        One row per product, one dot per review by a ring member, on a shared time axis. The{" "}
        <span className="font-mono">N×</span> figure is how many distinct members reviewed that
        product. Vertical stacks are the signal: the tightest here is{" "}
        <span className="font-mono">{tightest.asin}</span>, hit by{" "}
        <span className="tabular font-medium">{tightest.n_members}</span> accounts inside{" "}
        <span className="tabular font-medium">
          {tightest.last_day - tightest.first_day}
        </span>{" "}
        days at a mean rating of{" "}
        <span className="tabular font-medium">{tightest.mean_rating.toFixed(2)}</span>.
      </p>
    </div>
  );
}
