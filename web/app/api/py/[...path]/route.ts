import type { NextRequest } from "next/server";
import { snapshotMode } from "@/lib/api";

const API = process.env.BDA_API_URL ?? "http://127.0.0.1:8000";

/**
 * The browser's path to the data. Locally it forwards to the FastAPI service; in the
 * hosted build it answers from the static snapshot. It replaces a next.config rewrite,
 * which could only ever point at the Python service.
 */
export async function GET(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const apiPath = `/${path.join("/")}`;

  if (snapshotMode()) {
    const { snapshotApi } = await import("@/lib/snapshot");
    try {
      const params = Object.fromEntries(request.nextUrl.searchParams);
      return Response.json(snapshotApi(apiPath, params), {
        headers: { "cache-control": "public, max-age=3600, s-maxage=86400" },
      });
    } catch (error) {
      return Response.json({ error: (error as Error).message }, { status: 404 });
    }
  }

  try {
    const upstream = await fetch(`${API}${apiPath}${request.nextUrl.search}`, { cache: "no-store" });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ error: "analysis API not reachable on 127.0.0.1:8000" }, { status: 502 });
  }
}
