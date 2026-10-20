"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";

export function ReviewerFilters() {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();

  const [minScore, setMinScore] = useState(Number(params.get("min_score") ?? 0));
  const [minReviews, setMinReviews] = useState(params.get("min_reviews") ?? "");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const inRing = params.get("in_ring");

  const apply = (extra: Record<string, string | undefined> = {}) => {
    const q = new URLSearchParams(params.toString());
    const next: Record<string, string | undefined> = {
      min_score: minScore > 0 ? minScore.toFixed(3) : undefined,
      min_reviews: minReviews || undefined,
      q: query || undefined,
      offset: "0",
      ...extra,
    };
    for (const [k, v] of Object.entries(next)) {
      if (v === undefined) q.delete(k);
      else q.set(k, v);
    }
    router.push(`${path}?${q}`);
  };

  const sortLinks: [string, string][] = [
    ["score", "Score"],
    ["score_text", "Text"],
    ["score_behaviour", "Behaviour"],
    ["score_graph", "Graph"],
    ["max_per_day", "Peak/day"],
    ["n_reviews", "Reviews"],
  ];
  const sort = params.get("sort") ?? "score";

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="grid gap-5 md:grid-cols-[1.3fr_1fr_1fr]">
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground">
            Minimum score{" "}
            <span className="tabular font-medium text-foreground">{minScore.toFixed(3)}</span>
          </label>
          <Slider
            value={[minScore]}
            onValueChange={([v]) => setMinScore(v)}
            onValueCommit={() => apply()}
            min={0}
            max={0.999}
            step={0.001}
          />
        </div>
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground">Minimum reviews</label>
          <Input
            value={minReviews}
            inputMode="numeric"
            placeholder="any"
            onChange={(e) => setMinReviews(e.target.value.replace(/\D/g, ""))}
            onBlur={() => apply()}
            onKeyDown={(e) => e.key === "Enter" && apply()}
          />
        </div>
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground">Search ID or display name</label>
          <Input
            value={query}
            placeholder="e.g. A2SUAM1J3GNN3B"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && apply()}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
        <span className="flex flex-wrap items-center gap-1">
          <span className="text-muted-foreground">Sort by</span>
          {sortLinks.map(([key, label]) => (
            <Button
              key={key}
              size="sm"
              variant={sort === key ? "secondary" : "ghost"}
              onClick={() => apply({ sort: key })}
            >
              {label}
            </Button>
          ))}
        </span>
        <span className="flex items-center gap-1">
          <span className="text-muted-foreground">Ring membership</span>
          {[
            ["", "Any"],
            ["true", "In a ring"],
            ["false", "Not in a ring"],
          ].map(([value, label]) => (
            <Button
              key={label}
              size="sm"
              variant={(inRing ?? "") === value ? "secondary" : "ghost"}
              onClick={() => apply({ in_ring: value || undefined })}
            >
              {label}
            </Button>
          ))}
        </span>
      </div>
    </div>
  );
}
