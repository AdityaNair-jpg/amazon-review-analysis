/** Rating mix as labelled bars. Direct labels beat a legend for five categories. */
export function RatingBars({
  ratings,
  total,
}: {
  ratings: { rating: number; n: number }[];
  total: number;
}) {
  const max = Math.max(...ratings.map((r) => r.n));
  return (
    <div className="space-y-2">
      {[...ratings].sort((a, b) => b.rating - a.rating).map((r) => (
        <div key={r.rating} className="flex items-center gap-3 text-sm">
          <span className="w-8 shrink-0 tabular text-muted-foreground">{r.rating}★</span>
          <div className="h-5 flex-1 overflow-hidden rounded bg-muted">
            <div
              className="h-full rounded bg-chart-1"
              style={{ width: `${(r.n / max) * 100}%` }}
            />
          </div>
          <span className="w-24 shrink-0 text-right tabular text-xs text-muted-foreground">
            {((r.n / total) * 100).toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
}
