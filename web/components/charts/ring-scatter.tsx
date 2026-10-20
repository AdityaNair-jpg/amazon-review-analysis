"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid, Cell, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { Button } from "@/components/ui/button";

type Ring = {
  ring_id: number;
  n_members: number;
  density: number;
  n_reviews: number;
  n_products: number;
  span_days: number;
  mean_rating: number;
  mean_shared: number;
  first_day: number;
};

const tone = (r: Ring) =>
  r.density >= 0.999 ? "var(--chart-5)"
    : r.density >= 0.8 ? "var(--chart-4)"
      : r.density >= 0.5 ? "var(--chart-3)"
        : "var(--chart-1)";

export function RingScatter({ rings }: { rings: Ring[] }) {
  const [yKey, setYKey] = useState<"density" | "mean_shared">("density");

  const data = useMemo(
    () => rings.map((r) => ({ ...r, xv: Math.max(1, r.span_days), z: r.n_reviews })),
    [rings],
  );
  const perfect = rings.filter((r) => r.density >= 0.999).length;
  const tight = rings.filter((r) => r.span_days <= 90 && r.n_members >= 4).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1">
        <span className="mr-2 text-xs text-muted-foreground">Vertical axis</span>
        <Button
          size="sm"
          variant={yKey === "density" ? "secondary" : "ghost"}
          onClick={() => setYKey("density")}
        >
          Internal density
        </Button>
        <Button
          size="sm"
          variant={yKey === "mean_shared" ? "secondary" : "ghost"}
          onClick={() => setYKey("mean_shared")}
        >
          Shared products per pair
        </Button>
      </div>

      <div className="h-[340px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 10, right: 16, bottom: 28, left: 8 }}>
            <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" />
            <XAxis
              type="number"
              dataKey="xv"
              scale="log"
              domain={[1, "dataMax"]}
              allowDataOverflow
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              tickFormatter={(v) => {
                const n = Number(v);
                return n >= 365 ? `${(n / 365).toFixed(0)}y` : `${Math.round(n)}d`;
              }}
              label={{
                value: "Ring lifespan (log scale)",
                position: "insideBottom",
                offset: -16,
                style: { fontSize: 11, fill: "var(--muted-foreground)" },
              }}
            />
            <YAxis
              type="number"
              dataKey={yKey}
              tick={{ fontSize: 11 }}
              stroke="var(--muted-foreground)"
              width={48}
              tickFormatter={(v) => Number(v).toFixed(yKey === "density" ? 2 : 0)}
              label={{
                value: yKey === "density" ? "Internal density" : "Shared products per pair",
                angle: -90,
                position: "insideLeft",
                style: { fontSize: 11, fill: "var(--muted-foreground)", textAnchor: "middle" },
              }}
            />
            <ZAxis type="number" dataKey="z" range={[16, 340]} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as Ring;
                return (
                  <div className="rounded-md border bg-popover p-2 text-xs shadow-sm">
                    <div className="font-medium">Ring #{r.ring_id}</div>
                    <div className="tabular text-muted-foreground">
                      {r.n_members} accounts · density {r.density.toFixed(3)} ·{" "}
                      {r.mean_shared.toFixed(1)} shared/pair
                    </div>
                    <div className="tabular text-muted-foreground">
                      {r.n_products.toLocaleString("en-US")} products ·{" "}
                      {r.n_reviews.toLocaleString("en-US")} reviews ·{" "}
                      {r.span_days.toLocaleString("en-US")}d · {r.mean_rating.toFixed(2)}★
                    </div>
                    <div className="mt-1 text-muted-foreground">click to open</div>
                  </div>
                );
              }}
            />
            <Scatter
              data={data}
              isAnimationActive={false}
              className="cursor-pointer"
              onClick={(point) => {
                const id = (point as unknown as { ring_id?: number })?.ring_id;
                if (id !== undefined) window.location.href = `/rings/${id}`;
              }}
            >
              {data.map((r) => (
                <Cell key={r.ring_id} fill={tone(r)} fillOpacity={0.6} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>Density:</span>
        {[
          ["var(--chart-1)", "0.30–0.50"],
          ["var(--chart-3)", "0.50–0.80"],
          ["var(--chart-4)", "0.80–1.00"],
          ["var(--chart-5)", "exactly 1.00"],
        ].map(([c, label]) => (
          <span key={label} className="flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: c }} />
            {label}
          </span>
        ))}
        <span className="ml-auto">bubble area = reviews written by the ring</span>
      </div>

      <p className="text-xs text-muted-foreground">
        All {rings.length.toLocaleString("en-US")} rings.{" "}
        <span className="tabular font-medium">{perfect.toLocaleString("en-US")}</span> are
        complete graphs — every member co-reviewed every other member.{" "}
        <span className="tabular font-medium">{tight}</span> have four or more accounts
        operating inside 90 days, which is the corner of this chart worth reading first:
        short-lived, dense, and multi-account is the shape a paid campaign leaves. Long-lived
        dense rings on the right are more often genuine communities — a book club, a hobby
        forum — and the chart does not distinguish those on its own.
      </p>
    </div>
  );
}
