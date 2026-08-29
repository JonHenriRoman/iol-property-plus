import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  // Do not let `next build`/`next dev` generate AGENTS.md / CLAUDE.md in the repo root.
  agentRules: false,
  images: {
    // Deny-all by design. Add a specific { protocol, hostname, pathname }
    // entry here when an external image is genuinely required.
    // Never use a wildcard hostname.
    remotePatterns: [],
  },
};

export default nextConfig;
