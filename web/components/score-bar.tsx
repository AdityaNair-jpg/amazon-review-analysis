import { cn } from "@/lib/utils";

/**
 * A score rendered as a filled bar plus its number. The bar carries the
 * comparison; the number carries the value. Colour steps only at meaningful
 * thresholds so the eye is not asked to decode a continuous gradient.
 */
export function ScoreBar({ value, className }: { value: number | null; className?: string }) {
  const v = value ?? 0;
  const tone =
    v >= 0.99 ? "bg-chart-5" : v >= 0.95 ? "bg-chart-4" : v >= 0.85 ? "bg-chart-3" : "bg-chart-1";
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${v * 100}%` }} />
      </div>
      <span className="tabular text-xs text-muted-foreground">{v.toFixed(3)}</span>
    </div>
  );
}
