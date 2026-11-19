import type { NextConfig } from "next";

import { securityHeaders } from "./src/lib/securityHeaders";

const nextConfig: NextConfig = {
  // Do not advertise the framework in response headers.
  poweredByHeader: false,
  // Content Security Policy and other defensive headers (P8-M1, ADR-035).
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders(process.env.NODE_ENV) }];
  },
  // Stop `next dev` from writing an AGENTS.md file into the repository.
  agentRules: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
