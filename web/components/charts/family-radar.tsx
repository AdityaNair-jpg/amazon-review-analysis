"use client";

import {
  PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip,
} from "recharts";

/**
 * One account's three family scores, against the corpus median.
 *
 * Three axes is the minimum for a radar and normally an argument against using
 * one — but here the *shape* is the message: a spike on one axis means a single
 * family flagged this account, a filled triangle means all three did, and those
 * two cases mean very different things.
 */
export function FamilyRadar({
  text,
  behaviour,
  graph,
  height = 240,
}: {
  text: number;
  behaviour: number;
  graph: number;
  height?: number;
}) {
  const data = [
    { axis: "Text", value: text, median: 0.5 },
    { axis: "Behaviour", value: behaviour, median: 0.5 },
    { axis: "Graph", value: graph, median: 0.5 },
  ];
  const spread = Math.max(text, behaviour, graph) - Math.min(text, behaviour, graph);

  return (
    <div className="space-y-2">
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={data} outerRadius="72%">
            <PolarGrid stroke="var(--border)" />
            <PolarAngleAxis
              dataKey="axis"
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
            />
            <PolarRadiusAxis
              domain={[0, 1]}
              tickCount={5}
              tick={{ fontSize: 9, fill: "var(--muted-foreground)" }}
              axisLine={false}
            />
            <Radar
              name="corpus median"
              dataKey="median"
              stroke="var(--muted-foreground)"
              strokeDasharray="3 3"
              fill="none"
              isAnimationActive={false}
            />
            <Radar
              name="this account"
              dataKey="value"
              stroke="var(--chart-5)"
              fill="var(--chart-5)"
              fillOpacity={0.3}
              strokeWidth={2}
              isAnimationActive={false}
            />
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(value, name) => [Number(value).toFixed(3), String(name)]}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted-foreground">
        {spread < 0.12
          ? "All three families agree on this account — the strongest evidence available here, since they share no input feature."
          : "The families disagree about this account: the shape is a spike, not a triangle. One family is driving the score, which is weaker evidence than agreement across three."}{" "}
        The dashed triangle is the corpus median.
      </p>
    </div>
  );
}
