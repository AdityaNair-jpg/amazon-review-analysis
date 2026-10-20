"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";

export function Pager({
  total,
  limit,
  offset,
}: {
  total: number;
  limit: number;
  offset: number;
}) {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();

  const go = (next: number) => {
    const q = new URLSearchParams(params.toString());
    q.set("offset", String(Math.max(0, next)));
    router.push(`${path}?${q}`);
  };

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="tabular text-muted-foreground">
        {total === 0
          ? "no results"
          : `${(offset + 1).toLocaleString("en-US")}–${Math.min(offset + limit, total).toLocaleString("en-US")} of ${total.toLocaleString("en-US")}`}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" disabled={offset <= 0} onClick={() => go(0)}>
          First
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={offset <= 0}
          onClick={() => go(offset - limit)}
        >
          Previous
        </Button>
        <span className="tabular px-1 text-muted-foreground">
          {page} / {pages.toLocaleString("en-US")}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={offset + limit >= total}
          onClick={() => go(offset + limit)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
