"use client";

import { useMemo } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

type Segment = { label: string; n: number; families: number };

const TONE: Record<string, string> = {
  "Text only": "var(--chart-2)",
  "Behaviour only": "var(--chart-3)",
  "Graph only": "var(--chart-4)",
  "Text + Behaviour": "var(--chart-1)",
  "Text + Graph": "var(--chart-1)",
  "Behaviour + Graph": "var(--chart-1)",
  "All three": "var(--chart-5)",
};

/**
 * How the three families' top-k sets overlap: a proportional Venn alongside the
 * donut, because the Venn shows the shape and the donut shows the magnitudes.
 *
 * The circles are drawn at fixed positions with radii proportional to sqrt(k) --
 * an exactly area-proportional three-set Venn is not generally constructible, so
 * the diagram is a schematic and the numbers beside it are the real answer. That
 * is stated on the page rather than implied.
 */
export function FamilyVenn({ segments, k, union }: {
  segments: Segment[];
  k: number;
  union: number;
}) {
  const by = useMemo(
    () => Object.fromEntries(segments.map((s) => [s.label, s.n])) as Record<string, number>,
    [segments],
  );
  const overlapping = segments
    .filter((s) => s.families > 1)
    .reduce((a, s) => a + s.n, 0);

  const circles = [
    { cx: 88, cy: 78, label: "Text", tone: "var(--chart-2)" },
    { cx: 152, cy: 78, label: "Behaviour", tone: "var(--chart-3)" },
    { cx: 120, cy: 134, label: "Graph", tone: "var(--chart-4)" },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start gap-6">
        <svg viewBox="0 0 240 200" className="h-[200px] w-[240px] shrink-0">
          {circles.map((c) => (
            <circle
              key={c.label}
              cx={c.cx}
              cy={c.cy}
              r={52}
              fill={c.tone}
              fillOpacity={0.22}
              stroke={c.tone}
              strokeWidth={1.5}
            />
          ))}
          <text x={56} y={26} className="fill-muted-foreground" fontSize="10">Text</text>
          <text x={158} y={26} className="fill-muted-foreground" fontSize="10">Behaviour</text>
          <text x={102} y={196} className="fill-muted-foreground" fontSize="10">Graph</text>

          {/* counts placed in their region */}
          <text x={64} y={64} fontSize="11" className="fill-foreground" textAnchor="middle">
            {(by["Text only"] ?? 0).toLocaleString("en-US")}
          </text>
          <text x={176} y={64} fontSize="11" className="fill-foreground" textAnchor="middle">
            {(by["Behaviour only"] ?? 0).toLocaleString("en-US")}
          </text>
          <text x={120} y={166} fontSize="11" className="fill-foreground" textAnchor="middle">
            {(by["Graph only"] ?? 0).toLocaleString("en-US")}
          </text>
          <text x={120} y={70} fontSize="10" className="fill-muted-foreground" textAnchor="middle">
            {(by["Text + Behaviour"] ?? 0).toLocaleString("en-US")}
          </text>
          <text x={88} y={116} fontSize="10" className="fill-muted-foreground" textAnchor="middle">
            {(by["Text + Graph"] ?? 0).toLocaleString("en-US")}
          </text>
          <text x={152} y={116} fontSize="10" className="fill-muted-foreground" textAnchor="middle">
            {(by["Behaviour + Graph"] ?? 0).toLocaleString("en-US")}
          </text>
          <text x={120} y={102} fontSize="11" fontWeight="600" className="fill-foreground" textAnchor="middle">
            {(by["All three"] ?? 0).toLocaleString("en-US")}
          </text>
        </svg>

        <div className="h-[200px] w-[200px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={segments}
                dataKey="n"
                nameKey="label"
                innerRadius="52%"
                outerRadius="90%"
                paddingAngle={1.5}
                stroke="var(--background)"
                strokeWidth={2}
                isAnimationActive={false}
              >
                {segments.map((s) => (
                  <Cell key={s.label} fill={TONE[s.label] ?? "var(--muted-foreground)"} />
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
                  `${Number(value).toLocaleString("en-US")} (${((Number(value) / union) * 100).toFixed(1)}%)`,
                  String(name),
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <ul className="min-w-[180px] flex-1 space-y-1">
          {segments.map((s) => (
            <li key={s.label} className="flex items-center gap-2 text-xs">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ backgroundColor: TONE[s.label] ?? "var(--muted-foreground)" }}
              />
              <span className="flex-1">{s.label}</span>
              <span className="tabular text-muted-foreground">
                {s.n.toLocaleString("en-US")}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-xs text-muted-foreground">
        Each family&rsquo;s own top {k.toLocaleString("en-US")} accounts. If the three were
        looking at the same population the union would be {k.toLocaleString("en-US")}; if they
        were entirely independent it would be close to{" "}
        {(3 * k).toLocaleString("en-US")}. It is{" "}
        <span className="tabular font-medium">{union.toLocaleString("en-US")}</span>, with only{" "}
        <span className="tabular font-medium">{overlapping.toLocaleString("en-US")}</span>{" "}
        accounts seen by more than one family. The families are mostly finding{" "}
        <em>different</em> accounts — which is why the dashboard exposes a consensus score and
        an any-family score separately rather than pretending there is one suspect list. The
        circles are schematic; the counts are the answer.
      </p>
    </div>
  );
}
