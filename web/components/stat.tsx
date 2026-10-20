import { cn } from "@/lib/utils";

export function Stat({
  label,
  value,
  sub,
  className,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular leading-none">{value}</div>
      {sub ? <div className="text-xs text-muted-foreground tabular">{sub}</div> : null}
    </div>
  );
}
