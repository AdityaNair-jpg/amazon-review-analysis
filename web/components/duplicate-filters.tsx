"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";

const KINDS: [string, string][] = [
  ["exact", "Exact"],
  ["loose", "Near-dup (J ≥ 0.707)"],
  ["tight", "Near-dup (J ≥ 0.878)"],
];

export function DuplicateFilters() {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const kind = params.get("kind") ?? "loose";
  const crossReviewer = (params.get("cross_reviewer") ?? "true") === "true";
  const substantive = (params.get("substantive") ?? "true") === "true";

  const set = (patch: Record<string, string | undefined>) => {
    const q = new URLSearchParams(params.toString());
    q.set("offset", "0");
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) q.delete(k);
      else q.set(k, v);
    }
    router.push(`${path}?${q}`);
  };

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border p-4 text-xs">
      <span className="flex flex-wrap items-center gap-1">
        <span className="text-muted-foreground">Similarity</span>
        {KINDS.map(([value, label]) => (
          <Button
            key={value}
            size="sm"
            variant={kind === value ? "secondary" : "ghost"}
            onClick={() => set({ kind: value })}
          >
            {label}
          </Button>
        ))}
      </span>
      <span className="flex items-center gap-1">
        <Button
          size="sm"
          variant={crossReviewer ? "secondary" : "ghost"}
          onClick={() => set({ cross_reviewer: crossReviewer ? "false" : "true" })}
        >
          {crossReviewer ? "✓ " : ""}Multiple accounts only
        </Button>
        {kind === "exact" && (
          <Button
            size="sm"
            variant={substantive ? "secondary" : "ghost"}
            onClick={() => set({ substantive: substantive ? "false" : "true" })}
          >
            {substantive ? "✓ " : ""}20+ words only
          </Button>
        )}
      </span>
      <span className="text-muted-foreground">
        One account reposting its own text is a much weaker signal than several accounts
        posting the same words, so the two are separated rather than pooled.
      </span>
    </div>
  );
}
