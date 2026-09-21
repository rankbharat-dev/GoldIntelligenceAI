import type { NextConfig } from "next";

// The research API (ci-api) runs locally on :8000. Proxying keeps the browser on a
// single origin, so no CORS is needed and the API never has to listen publicly.
const API_ORIGIN = process.env.CI_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // A second dev server (e.g. a preview next to the owner's own) needs its own build dir.
  distDir: process.env.CI_NEXT_DIST ?? ".next",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
