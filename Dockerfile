# syntax=docker/dockerfile:1

# ── base ──────────────────────────────────────────────────────────────────────
# Node 24 to match .nvmrc (24.19.0).
# §9: pin the digest once the base image is formally approved —
#   node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df
FROM node:24.19.0-bookworm-slim AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

# ── deps ──────────────────────────────────────────────────────────────────────
# Full install (dev deps are needed for `next build`); pnpm is pinned by
# package.json's packageManager field, never pnpm@latest.
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# ── builder ───────────────────────────────────────────────────────────────────
FROM base AS builder
ENV NODE_ENV=production
# NEXT_PUBLIC_* is inlined at build time; §9's pipeline passes the real value.
ARG NEXT_PUBLIC_SITE_URL=http://localhost:3000
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm run build

# ── runner ────────────────────────────────────────────────────────────────────
# Standalone runtime only: no source tree, no pnpm store, no dev dependencies.
FROM node:24.19.0-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN groupadd --system --gid 1001 nodejs \
  && useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
