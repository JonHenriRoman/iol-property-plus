import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  // Do not let `next build`/`next dev` generate AGENTS.md / CLAUDE.md in the repo root.
  agentRules: false,
};

export default nextConfig;
