import { readFileSync } from "node:fs";
import path from "node:path";
import { gunzipSync } from "node:zlib";

/**
 * The hosted dashboard's data source: the static snapshot written by
 * pipeline/17_export_snapshot.py, answering the same paths as the local FastAPI service.
 *
 * Detail responses are looked up; list responses are filtered, sorted and paged here
 * with the API's own rules (same sort whitelist, same defaults, same limit clamp), so
 * the pages cannot tell which source they are talking to.
 */

const DIR = path.join(process.cwd(), "data", "snapshot");
const SHARDS = { reviewers: 64, rings: 16, products: 8 } as const;
const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 1000;

// Mirrors SORTABLE in api/db.py. Anything else falls back to the default column.
const SORTABLE: Record<string, Set<string>> = {
  reviewers: new Set(["score", "score_any", "score_text", "score_behaviour", "score_graph",
    "n_reviews", "max_per_day", "lifespan_days", "mean_rating", "ring_size", "first_day", "last_day"]),
  rings: new Set(["density", "n_members", "n_products", "n_reviews", "span_days", "mean_shared",
    "mean_rating", "first_day"]),
  duplicates: new Set(["n_reviewers", "n_reviews", "n_products", "n_words", "span_days",
    "mean_rating", "cluster_id"]),
  neardup: new Set(["n_reviewers", "n_reviews", "n_products", "mean_jaccard", "span_days",
    "mean_rating", "cluster_id"]),
};

export class NotInSnapshot extends Error {}

type Row = Record<string, unknown>;
type Params = Record<string, string | number | boolean | undefined | null>;

const cache = new Map<string, unknown>();
function load<T>(rel: string): T {
  if (!cache.has(rel)) {
    const raw = gunzipSync(readFileSync(path.join(DIR, rel)));
    cache.set(rel, JSON.parse(raw.toString("utf8")));
  }
  return cache.get(rel) as T;
}

function tryLoad<T>(rel: string): T | null {
  try {
    return load<T>(rel);
  } catch {
    return null;
  }
}

const num = (v: unknown, fallback: number) => {
  const n = Number(v);
  return v === undefined || v === null || v === "" || Number.isNaN(n) ? fallback : n;
};
const bool = (v: unknown): boolean | undefined =>
  v === undefined || v === null || v === "" ? undefined : String(v) === "true" || String(v) === "1";

function page(rows: Row[], params: Params, table: string, fallback: string) {
  const limit = Math.min(Math.max(num(params.limit, DEFAULT_LIMIT), 1), MAX_LIMIT);
  const offset = Math.max(num(params.offset, 0), 0);
  const sort = typeof params.sort === "string" && SORTABLE[table]?.has(params.sort)
    ? params.sort : fallback;
  const asc = String(params.dir ?? "desc").toLowerCase() === "asc";
  const sorted = [...rows].sort((a, b) => {
    const x = a[sort] as number | null;
    const y = b[sort] as number | null;
    if (x === null || x === undefined) return y === null || y === undefined ? 0 : 1; // nulls last
    if (y === null || y === undefined) return -1;
    return asc ? (x > y ? 1 : x < y ? -1 : 0) : (x < y ? 1 : x > y ? -1 : 0);
  });
  return { total: rows.length, limit, offset, items: sorted.slice(offset, offset + limit) };
}

function shard<T>(kind: keyof typeof SHARDS, id: number): T | null {
  const file = load<Record<string, T>>(`${kind}/${String(id % SHARDS[kind]).padStart(2, "0")}.json.gz`);
  return file[String(id)] ?? null;
}

const missing = (what: string) =>
  new NotInSnapshot(`${what} not found in the online snapshot. It includes the most suspicious ` +
    `accounts, every group, and the largest copied-text clusters.`);

export function snapshotApi<T>(apiPath: string, params: Params = {}): T {
  const p = apiPath.replace(/\/+$/, "");
  const fixed = load<Record<string, unknown>>("fixed.json.gz");

  // Fixed responses: the key carries the parameters the pages actually send.
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${v}`)
    .sort()
    .join("&");
  for (const key of [qs ? `${p}?${qs}` : p, p]) {
    if (key in fixed) return fixed[key] as T;
  }

  let m: RegExpMatchArray | null;

  if (p === "/rings") {
    const minMembers = num(params.min_members, 3);
    const rows = load<Row[]>("lists/rings.json.gz").filter((r) => Number(r.n_members) >= minMembers);
    return page(rows, params, "rings", "density") as T;
  }
  if ((m = p.match(/^\/rings\/(\d+)(\/convergence)?$/))) {
    const entry = shard<{ detail: unknown; convergence: unknown }>("rings", Number(m[1]));
    if (!entry) throw missing("Group");
    return (m[2] ? entry.convergence : entry.detail) as T;
  }

  if (p === "/reviewers") {
    const minScore = num(params.min_score, 0);
    const maxScore = num(params.max_score, 1);
    const minReviews = num(params.min_reviews, 0);
    const inRing = bool(params.in_ring);
    const q = typeof params.q === "string" ? params.q.toLowerCase() : "";
    const rows = load<Row[]>("lists/reviewers.json.gz").filter((r) => {
      const score = Number(r.score);
      if (score < minScore || score > maxScore || Number(r.n_reviews) < minReviews) return false;
      if (inRing === true && !(Number(r.ring_size) > 0)) return false;
      if (inRing === false && Number(r.ring_size) > 0) return false;
      if (q && !String(r.reviewerID ?? "").toLowerCase().includes(q)
            && !String(r.reviewer_name ?? "").toLowerCase().includes(q)) return false;
      return true;
    });
    return page(rows, params, "reviewers", "score") as T;
  }
  if ((m = p.match(/^\/reviewers\/(\d+)(\/timeline)?$/))) {
    const entry = shard<{ detail: unknown; timeline: unknown }>("reviewers", Number(m[1]));
    if (!entry) throw missing("Account");
    return (m[2] ? entry.timeline : entry.detail) as T;
  }

  if (p === "/duplicates") {
    const kind = String(params.kind ?? "exact");
    if (!["exact", "loose", "tight"].includes(kind)) throw new NotInSnapshot("unknown kind");
    let rows = load<Row[]>(`lists/duplicates-${kind}.json.gz`);
    // The snapshot holds cross-account clusters only (the pages' default view).
    if (kind === "exact" && bool(params.substantive) !== false) {
      rows = rows.filter((r) => r.is_substantive);
    }
    const result = page(rows, params, kind === "exact" ? "duplicates" : "neardup", "n_reviewers");
    return { kind, ...result } as T;
  }
  if ((m = p.match(/^\/duplicates\/(exact|loose|tight)\/(\d+)$/))) {
    const entry = load<Record<string, unknown>>(`duplicates/${m[1]}.json.gz`)[m[2]];
    if (!entry) throw missing("Cluster");
    return entry as T;
  }

  if (p === "/products") {
    const minReviews = num(params.min_reviews, 10);
    const rows = load<Row[]>("lists/products.json.gz").filter((r) => Number(r.n_reviews) >= minReviews);
    const limit = Math.min(Math.max(num(params.limit, DEFAULT_LIMIT), 1), MAX_LIMIT);
    const offset = Math.max(num(params.offset, 0), 0);
    return { total: rows.length, limit, offset, items: rows.slice(offset, offset + limit) } as T;
  }
  if ((m = p.match(/^\/products\/([^/]+)(\/ratings)?$/))) {
    let sk = /^\d+$/.test(m[1]) ? Number(m[1]) : null;
    if (sk === null) {
      const index = tryLoad<Record<string, number>>("products/asin-index.json.gz") ?? {};
      sk = index[decodeURIComponent(m[1])] ?? null;
    }
    const entry = sk === null ? null : shard<{ detail: unknown; ratings: unknown }>("products", sk);
    if (!entry) throw missing("Product");
    return (m[2] ? entry.ratings : entry.detail) as T;
  }

  throw new NotInSnapshot(`${p} is not part of the online snapshot.`);
}

/** True when pages should read the snapshot rather than the local API. */
export const useSnapshot = () => process.env.BDA_SNAPSHOT === "1" || process.env.VERCEL === "1";
