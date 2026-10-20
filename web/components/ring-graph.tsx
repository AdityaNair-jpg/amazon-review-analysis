"use client";

import { useMemo } from "react";

type Member = { reviewer_sk: number; reviewerID: string; score: number | null };
type Edge = { r1: number; r2: number; shared: number };

/**
 * A ring drawn on a circle rather than force-directed.
 *
 * For 3-200 accounts a circular layout beats a force simulation on every axis that
 * matters here: node positions are deterministic, two runs never disagree, and the
 * question the eye actually needs to answer - how close is this to a complete
 * graph - is exactly what a circle makes legible. A force layout would spend a
 * second of animation to communicate less.
 */
export function RingGraph({ members, edges }: { members: Member[]; edges: Edge[] }) {
  const { nodes, lines, maxShared } = useMemo(() => {
    const size = 420;
    const radius = size / 2 - 46;
    const cx = size / 2;
    const cy = size / 2;
    const pos = new Map<number, { x: number; y: number }>();
    members.forEach((m, i) => {
      const angle = (2 * Math.PI * i) / members.length - Math.PI / 2;
      // Rounded deliberately: Math.cos/Math.sin can disagree in the final ULP
      // between the Node build that server-renders this and the browser build
      // that hydrates it, and React reports every such edge as a mismatch.
      pos.set(m.reviewer_sk, {
        x: Math.round((cx + radius * Math.cos(angle)) * 100) / 100,
        y: Math.round((cy + radius * Math.sin(angle)) * 100) / 100,
      });
    });
    const max = Math.max(1, ...edges.map((e) => e.shared));
    return {
      nodes: members.map((m) => ({ ...m, ...pos.get(m.reviewer_sk)! })),
      lines: edges
        .filter((e) => pos.has(e.r1) && pos.has(e.r2))
        .map((e) => ({ ...e, a: pos.get(e.r1)!, b: pos.get(e.r2)! })),
      maxShared: max,
    };
  }, [members, edges]);

  if (members.length === 0) {
    return <p className="text-sm text-muted-foreground">No members.</p>;
  }

  return (
    <div className="space-y-2">
      <svg viewBox="0 0 420 420" className="mx-auto block h-auto w-full max-w-[420px]">
        {lines.map((l, i) => (
          <line
            key={i}
            x1={l.a.x}
            y1={l.a.y}
            x2={l.b.x}
            y2={l.b.y}
            stroke="var(--chart-1)"
            strokeOpacity={0.25 + 0.55 * (l.shared / maxShared)}
            strokeWidth={0.6 + 2.6 * (l.shared / maxShared)}
          />
        ))}
        {nodes.map((n) => (
          <g key={n.reviewer_sk}>
            <circle
              cx={n.x}
              cy={n.y}
              r={6}
              fill="var(--chart-5)"
              fillOpacity={0.35 + 0.65 * (n.score ?? 0)}
              stroke="var(--background)"
              strokeWidth={1.5}
            />
            <title>{`${n.reviewerID} — score ${(n.score ?? 0).toFixed(3)}`}</title>
          </g>
        ))}
      </svg>
      <p className="text-center text-xs text-muted-foreground">
        {members.length} accounts, {lines.length} co-review links (the busiest pair shares{" "}
        {maxShared} products). Node opacity is the suspicion score.
      </p>
    </div>
  );
}
