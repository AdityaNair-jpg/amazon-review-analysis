import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dev server only trusts the hostname it started on (`localhost`). Opening the
  // dashboard as 127.0.0.1 -- the address the API itself lives on -- got the HTML but
  // had its dev scripts blocked, so the page rendered and never hydrated: every
  // interactive part, the network graph included, sat as a grey placeholder.
  allowedDevOrigins: ["127.0.0.1"],
  // Browser requests go to /api/py/*, served by app/api/py/[...path]/route.ts: it
  // forwards to the local FastAPI service, or answers from the static snapshot in the
  // hosted build. Same origin either way, so no CORS configuration is needed.
  //
  // The hosted build reads its data from data/snapshot at request time, which file
  // tracing cannot discover on its own (the paths are computed), so it is named here.
  outputFileTracingIncludes: {
    "/**": ["./data/snapshot/**/*"],
  },
};

export default nextConfig;
