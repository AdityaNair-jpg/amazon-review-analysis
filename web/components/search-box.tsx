"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const EXAMPLES = [
  "battery case charges my phone",
  "kids loved this book illustrations",
  "arrived broken waste of money",
  "large print hymnal church",
];

export function SearchBox({ busy }: { busy?: boolean }) {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const [value, setValue] = useState(params.get("q") ?? "");

  const run = (q: string) => {
    const next = new URLSearchParams(params.toString());
    if (q.trim()) next.set("q", q.trim());
    else next.delete("q");
    next.delete("offset");
    router.push(`${path}?${next}`);
  };

  const toggle = (key: string) => {
    const next = new URLSearchParams(params.toString());
    if (next.get(key) === "1") next.delete(key);
    else next.set(key, "1");
    next.delete("offset");
    router.push(`${path}?${next}`);
  };

  const on = (key: string) => params.get(key) === "1";

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run(value)}
          placeholder="Search 41 million reviews…"
          className="h-11 text-base"
          autoFocus
        />
        <Button className="h-11 px-6" onClick={() => run(value)} disabled={busy}>
          Search
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        <span className="flex items-center gap-1">
          <Button
            size="sm"
            variant={on("demote") ? "secondary" : "ghost"}
            onClick={() => toggle("demote")}
            title="Push reviews from suspected coordinated accounts down the ranking"
          >
            {on("demote") ? "✓ " : ""}Demote suspicious reviews
          </Button>
          <Button
            size="sm"
            variant={on("rerank") ? "secondary" : "ghost"}
            onClick={() => toggle("rerank")}
            title="Re-order the top 50 with a neural cross-encoder (adds about a second)"
          >
            {on("rerank") ? "✓ " : ""}Neural reranking
          </Button>
        </span>

        {!params.get("q") && (
          <span className="flex flex-wrap items-center gap-1 text-muted-foreground">
            Try:
            {EXAMPLES.map((e) => (
              <button
                key={e}
                onClick={() => {
                  setValue(e);
                  run(e);
                }}
                className="rounded-md border px-2 py-0.5 hover:bg-secondary"
              >
                {e}
              </button>
            ))}
          </span>
        )}
      </div>
    </div>
  );
}
