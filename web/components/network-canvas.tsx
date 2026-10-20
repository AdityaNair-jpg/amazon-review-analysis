"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FAMILY, type FamilyKey } from "@/lib/labels";
import { Skeleton } from "@/components/ui/skeleton";

type Node = { id: number; u: string; x: number; y: number; s: number; f: FamilyKey; n: number; c: number };
type Cluster = { id: number; size: number };
type Graph = {
  width: number;
  height: number;
  nodes: Node[];
  edges: [number, number, number][];
  clusters?: Cluster[];
};

const TONE_VAR: Record<FamilyKey, string> = { T: "--chart-2", B: "--chart-3", G: "--chart-4" };

/**
 * The suspicious-account network, drawn on a canvas.
 *
 * Positions come precomputed from pipeline/15_story_network.py, so there is no force
 * simulation here: the picture is identical on every load, nothing jitters, and a
 * 2,479-node view with 16,403 links draws in a few milliseconds. Canvas rather than
 * SVG because that is ~19,000 elements, which SVG handles badly on pan and zoom.
 *
 * Colour is the signal family that scored the account highest, using the same tones
 * as every other page, so "amber" means "moves in a pack" everywhere on the site.
 */
export function NetworkCanvas({ view, minSize = 0 }: { view: "packs" | "core"; minSize?: number }) {
  const router = useRouter();
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<{ node: Node; px: number; py: number } | null>(null);
  // Pan and zoom, in data units: screen = (data - origin) * scale.
  const view_ = useRef({ scale: 1, ox: 0, oy: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; moved: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setGraph(null);
    setHover(null);
    setError(null);
    fetch(`/api/py/story/network/graph?view=${view}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((g: Graph) => !cancelled && setGraph(g))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [view]);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  // What is actually drawn. Clusters were packed largest-first in the pipeline, so
  // hiding the small ones removes whole trailing rows and the view can refit to the
  // groups that remain instead of leaving a gap where the pairs were.
  const shown = useMemo<Graph | null>(() => {
    if (!graph) return null;
    const sizes = new Map((graph.clusters ?? []).map((c) => [c.id, c.size]));
    const keep = graph.nodes.map((n) => (sizes.get(n.c) ?? Infinity) >= minSize);
    const remap = new Map<number, number>();
    const nodes: Node[] = [];
    graph.nodes.forEach((n, i) => {
      if (keep[i]) {
        remap.set(i, nodes.length);
        nodes.push(n);
      }
    });
    const edges = graph.edges
      .filter(([a, b]) => keep[a] && keep[b])
      .map(([a, b, w]) => [remap.get(a)!, remap.get(b)!, w] as [number, number, number]);
    const pad = 14;
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const x0 = Math.min(...xs) - pad;
    const y0 = Math.min(...ys) - pad;
    return {
      nodes: nodes.map((n) => ({ ...n, x: n.x - x0, y: n.y - y0 })),
      edges,
      width: Math.max(...xs) - x0 + pad,
      height: Math.max(...ys) - y0 + pad,
    };
  }, [graph, minSize]);

  const height = shown ? Math.min(640, Math.max(320, Math.round((width * shown.height) / shown.width))) : 520;

  const neighbours = useMemo(() => {
    const adj = new Map<number, Set<number>>();
    shown?.edges.forEach(([a, b]) => {
      if (!adj.has(a)) adj.set(a, new Set());
      if (!adj.has(b)) adj.set(b, new Set());
      adj.get(a)!.add(b);
      adj.get(b)!.add(a);
    });
    return adj;
  }, [shown]);

  const radius = useCallback(
    (n: Node) => Math.max(1.6, Math.min(5.5, 1.1 * Math.log2(n.n))) * (view === "core" ? 0.75 : 1),
    [view],
  );

  const fit = useCallback(() => {
    if (!shown || !width) return;
    const scale = Math.min(width / shown.width, height / shown.height);
    view_.current = {
      scale,
      ox: -(width / scale - shown.width) / 2,
      oy: -(height / scale - shown.height) / 2,
    };
  }, [shown, width, height]);

  // Which data and canvas size the current pan/zoom was fitted for. Refitting is keyed on
  // this rather than left to an effect, because switching views swaps the data and the
  // canvas size in the same render, and relying on effect order drew the new view with
  // the previous view's transform: the core came up shifted and clipped at two edges
  // until a double-click reset it. Keyed like this, hover redraws keep the user's pan
  // and zoom, and anything that changes what is drawn always refits first.
  const fittedFor = useRef<{ shown: Graph | null; width: number; height: number } | null>(null);

  const draw = useCallback(() => {
    const el = canvas.current;
    if (!el || !shown || !width) return;
    const f = fittedFor.current;
    if (!f || f.shown !== shown || f.width !== width || f.height !== height) {
      fit();
      fittedFor.current = { shown, width, height };
    }
    const dpr = window.devicePixelRatio || 1;
    el.width = width * dpr;
    el.height = height * dpr;
    const ctx = el.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const css = getComputedStyle(document.documentElement);
    const tone = (f: FamilyKey) => css.getPropertyValue(TONE_VAR[f]).trim() || "#888";
    const ink = css.getPropertyValue("--muted-foreground").trim() || "#888";
    const fg = css.getPropertyValue("--foreground").trim() || "#000";
    const { scale, ox, oy } = view_.current;
    const sx = (x: number) => (x - ox) * scale;
    const sy = (y: number) => (y - oy) * scale;

    const focus = hover ? shown.nodes.indexOf(hover.node) : -1;
    const near = focus >= 0 ? neighbours.get(focus) ?? new Set<number>() : null;

    ctx.strokeStyle = ink;
    for (const [a, b, w] of shown.edges) {
      const lit = near !== null && (a === focus || b === focus);
      ctx.globalAlpha = near === null ? (view === "core" ? 0.08 : 0.55) : lit ? 0.9 : 0.04;
      ctx.lineWidth = Math.min(3.5, (view === "core" ? 0.4 : 0.9) + w / 6) * (lit ? 1.6 : 1);
      ctx.beginPath();
      ctx.moveTo(sx(shown.nodes[a].x), sy(shown.nodes[a].y));
      ctx.lineTo(sx(shown.nodes[b].x), sy(shown.nodes[b].y));
      ctx.stroke();
    }

    const r0 = Math.max(0.7, Math.min(2.4, Math.sqrt(scale)));
    shown.nodes.forEach((n, i) => {
      const dim = near !== null && i !== focus && !near.has(i);
      ctx.globalAlpha = dim ? 0.15 : 0.95;
      ctx.fillStyle = tone(n.f);
      ctx.beginPath();
      ctx.arc(sx(n.x), sy(n.y), radius(n) * r0, 0, Math.PI * 2);
      ctx.fill();
    });
    if (focus >= 0) {
      const n = shown.nodes[focus];
      ctx.globalAlpha = 1;
      ctx.strokeStyle = fg;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(sx(n.x), sy(n.y), radius(n) * r0 + 2.5, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }, [shown, width, height, hover, neighbours, radius, view, fit]);

  useEffect(() => draw(), [draw]);

  // Redraw when the site theme flips, since every colour here is read from CSS.
  useEffect(() => {
    const mo = new MutationObserver(() => draw());
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => mo.disconnect();
  }, [draw]);

  const toData = (e: React.MouseEvent) => {
    const rect = canvas.current!.getBoundingClientRect();
    const { scale, ox, oy } = view_.current;
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    return { px, py, x: px / scale + ox, y: py / scale + oy };
  };

  const pick = (e: React.MouseEvent) => {
    if (!shown) return null;
    const { px, py, x, y } = toData(e);
    const reach = 7 / view_.current.scale;
    let best: Node | null = null;
    let bestD = reach * reach;
    for (const n of shown.nodes) {
      const d = (n.x - x) ** 2 + (n.y - y) ** 2;
      if (d < bestD) {
        bestD = d;
        best = n;
      }
    }
    return best ? { node: best, px, py } : null;
  };

  const onWheel = (e: React.WheelEvent) => {
    if (!shown) return;
    const { x, y, px, py } = toData(e);
    const v = view_.current;
    const scale = Math.min(40, Math.max(0.2, v.scale * (e.deltaY < 0 ? 1.18 : 1 / 1.18)));
    view_.current = { scale, ox: x - px / scale, oy: y - py / scale };
    draw();
  };

  // A wheel listener must be non-passive to stop the page scrolling under the shown.
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const stop = (e: WheelEvent) => e.preventDefault();
    el.addEventListener("wheel", stop, { passive: false });
    return () => el.removeEventListener("wheel", stop);
  }, [shown]);

  if (error) {
    return (
      <div className="flex h-72 items-center justify-center rounded-lg border text-sm text-muted-foreground">
        Could not load the network: {error}
      </div>
    );
  }

  return (
    <div ref={wrap} className="relative w-full">
      {!shown ? (
        <Skeleton className="w-full rounded-lg" style={{ height }} />
      ) : (
        <canvas
          ref={canvas}
          style={{ width, height, cursor: hover ? "pointer" : drag.current ? "grabbing" : "grab" }}
          className="touch-none rounded-lg border bg-card"
          onWheel={onWheel}
          onMouseDown={(e) => {
            drag.current = { x: e.clientX, y: e.clientY, ox: view_.current.ox, oy: view_.current.oy, moved: false };
          }}
          onMouseMove={(e) => {
            const d = drag.current;
            if (d) {
              const dx = e.clientX - d.x;
              const dy = e.clientY - d.y;
              if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
              view_.current = { ...view_.current, ox: d.ox - dx / view_.current.scale, oy: d.oy - dy / view_.current.scale };
              draw();
              return;
            }
            setHover(pick(e));
          }}
          onMouseUp={(e) => {
            const d = drag.current;
            drag.current = null;
            if (d && !d.moved) {
              const hit = pick(e);
              if (hit) router.push(`/reviewers/${hit.node.id}`);
            }
          }}
          onMouseLeave={() => {
            drag.current = null;
            setHover(null);
          }}
          onDoubleClick={() => {
            fit();
            draw();
          }}
        />
      )}

      {hover && (
        <div
          className="pointer-events-none absolute z-10 w-60 rounded-md border bg-popover px-3 py-2 text-xs shadow-md"
          style={{
            left: Math.min(hover.px + 14, width - 250),
            top: Math.max(hover.py - 10, 0),
          }}
        >
          <div className="font-mono text-foreground">{hover.node.u}</div>
          <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 tabular text-muted-foreground">
            <span>suspicion</span>
            <span className="text-foreground">{hover.node.s.toFixed(3)}</span>
            <span>reviews</span>
            <span className="text-foreground">{hover.node.n.toLocaleString("en-US")}</span>
            <span>linked to</span>
            <span className="text-foreground">
              {(neighbours.get(shown!.nodes.indexOf(hover.node))?.size ?? 0).toLocaleString("en-US")} others
            </span>
          </div>
          <div className="mt-1.5 flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: FAMILY[hover.node.f].tone }} />
            <span>strongest signal: {FAMILY[hover.node.f].name.toLowerCase()}</span>
          </div>
          <div className="mt-1 text-muted-foreground">click to open the account</div>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>Colour = the signal that flagged the account most strongly:</span>
        {(Object.keys(FAMILY) as FamilyKey[]).map((k) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: FAMILY[k].tone }} />
            {FAMILY[k].name}
          </span>
        ))}
        <span className="ml-auto">Scroll to zoom · drag to pan · double-click to reset</span>
      </div>
    </div>
  );
}
