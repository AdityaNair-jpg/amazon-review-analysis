"use client";

import { useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NetworkCanvas } from "@/components/network-canvas";

/** The two views of the suspicious network, which are different kinds of thing. */
export function NetworkExplorer({
  packAccounts,
  packClusters,
  coreAccounts,
  pairs,
}: {
  packAccounts: number;
  packClusters: number;
  coreAccounts: number;
  pairs: number;
}) {
  const [view, setView] = useState<"packs" | "core">("packs");
  // Two-account pairs are the weakest possible "pack" and, drawn, they are 285 identical
  // dumbbells that bury every real group. Off by default, one click away, and counted.
  const [withPairs, setWithPairs] = useState(false);
  const n = (v: number) => v.toLocaleString("en-US");

  return (
    <div className="space-y-3">
      <Tabs value={view} onValueChange={(v) => setView(v as "packs" | "core")}>
        <TabsList>
          <TabsTrigger value="packs">
            Small packs · {n(packAccounts)} accounts in {n(packClusters)} groups
          </TabsTrigger>
          <TabsTrigger value="core">The linked core · {n(coreAccounts)} accounts</TabsTrigger>
        </TabsList>
      </Tabs>
      <p className="text-sm text-muted-foreground">
        {view === "packs" ? (
          <>
            Each knot is a separate group that kept reviewing the same products within days of
            each other, and is linked to no other suspicious account. Bigger knots, more
            accounts. Hover to see who, click to open one.
          </>
        ) : (
          <>
            One connected mass. Every account here is linked, directly or through others, to
            every other one. Drawn anyway so you can see why it is shown separately: there is
            no &ldquo;group&rdquo; to point at, just density.
          </>
        )}
      </p>
      {view === "packs" && (
        <label className="flex w-fit cursor-pointer items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={withPairs}
            onChange={(e) => setWithPairs(e.target.checked)}
            className="accent-foreground"
          />
          Also show the {n(pairs)} groups of just two accounts (hidden by default: two accounts
          alone are the weakest kind of group, and they crowd out the rest)
        </label>
      )}
      <NetworkCanvas view={view} minSize={view === "packs" && !withPairs ? 3 : 0} />
    </div>
  );
}
