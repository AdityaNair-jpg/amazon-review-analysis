/**
 * Typed access to the local FastAPI service.
 *
 * Server Components talk to 127.0.0.1:8000 directly; client components go through
 * the /api/py route handler. Same paths either way. In snapshot mode (the hosted
 * build) both read the precomputed files in data/snapshot instead.
 */
const SERVER_BASE = process.env.BDA_API_URL ?? "http://127.0.0.1:8000";

export const base = () => (typeof window === "undefined" ? SERVER_BASE : "/api/py");

export class ApiDown extends Error {}

/** Snapshot mode: the hosted build, which has no Python service behind it. */
export const snapshotMode = () =>
  process.env.BDA_SNAPSHOT === "1" || process.env.VERCEL === "1";

export async function api<T>(
  path: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<T> {
  if (typeof window === "undefined" && snapshotMode()) {
    // Imported lazily so the file-reading code never enters a browser bundle.
    const { snapshotApi, NotInSnapshot } = await import("./snapshot");
    try {
      return snapshotApi<T>(path, params);
    } catch (error) {
      // Pages treat a "not found" message as a 404, exactly as with the live API.
      if (error instanceof NotInSnapshot) throw new Error(error.message);
      throw error;
    }
  }
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const url = `${base()}${path}${qs.toString() ? `?${qs}` : ""}`;
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch {
    throw new ApiDown(
      "Cannot reach the analysis API on 127.0.0.1:8000. Start it with: pnpm dev:api",
    );
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** Days since epoch -> ISO date. The corpus stores day-granular timestamps. */
export function dayToDate(day: number | null | undefined): string {
  if (day === null || day === undefined) return "—";
  return new Date(day * 86400_000).toISOString().slice(0, 10);
}

export const num = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined || Number.isNaN(n)
    ? "—"
    : n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const pct = (n: number | null | undefined, digits = 1) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(digits)}%`;
