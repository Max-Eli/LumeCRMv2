# syntax=docker/dockerfile:1.7
#
# Lumè CRM frontend image — Next 16 + Turbopack-built React SPA.
#
# Three-stage build:
#
#   1. `deps`     — install npm dependencies. Cached separately so
#                   source-only changes don't invalidate the install.
#   2. `builder`  — run `next build` against the dep-installed tree.
#                   Produces `.next/standalone/` and `.next/static/`.
#   3. `runtime`  — `node:22-alpine` slim image, non-root user,
#                   exactly the minimum needed to run the standalone
#                   server. Final image ~150 MB vs ~1.5 GB for a
#                   full-deps image.
#
# Why standalone output (not static export): Next 16's static export
# requires `generateStaticParams` on every dynamic route segment, and
# the CRM has 24+ dynamic routes that resolve from runtime data.
# Static export workarounds (server-shell + client-child split,
# next/dynamic wrappers) fought Next's page-collection logic in
# multiple subtle ways. Containerized standalone is the well-trodden
# pattern professional deployments use.
#
# Why Alpine (not Debian slim): the standalone bundle has zero
# native-extension dependencies; we want the smallest possible image
# for fast Fargate cold starts. Alpine + node:22 = ~120 MB before
# our app, plus ~30 MB for the bundle.
#
# At runtime the container expects:
#
#   PORT                    server port (default 3000)
#   HOSTNAME                bind interface (set to '0.0.0.0' below)
#   NEXT_PUBLIC_API_URL     https://api.xn--lumcrm-5ua.com (punycode of
#                           api.lumècrm.com) -- baked at build time via
#                           build-arg below; changing it requires a rebuild.
#
# `NEXT_PUBLIC_*` env vars are inlined into the client bundle by Next
# at build time. We accept them as build-args so CI can switch them
# per environment without changing source.

ARG NODE_VERSION=22

# ── Deps ────────────────────────────────────────────────────────────
FROM node:${NODE_VERSION}-alpine AS deps

WORKDIR /app

# Install only production + build deps. Caching via layer: the deps
# layer is only invalidated when package.json or the lockfile change.
COPY package.json package-lock.json* yarn.lock* pnpm-lock.yaml* ./
RUN if [ -f package-lock.json ]; then \
      npm ci; \
    elif [ -f yarn.lock ]; then \
      corepack enable && yarn --frozen-lockfile; \
    elif [ -f pnpm-lock.yaml ]; then \
      corepack enable && pnpm i --frozen-lockfile; \
    else \
      echo "No lockfile found — refusing to install with floating deps in prod build" && exit 1; \
    fi

# ── Builder ─────────────────────────────────────────────────────────
FROM node:${NODE_VERSION}-alpine AS builder

WORKDIR /app

# Build-time env vars. NEXT_PUBLIC_* are inlined into the client
# bundle, so changing them requires a rebuild + redeploy. CI passes
# them via `--build-arg` per environment.
ARG NEXT_PUBLIC_API_URL=https://api.xn--lumcrm-5ua.com
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Telemetry off — Next doesn't need to phone home from CI/Fargate
# builds. (Plus: telemetry endpoints aren't on the AWS BAA.)
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Standalone output writes to `.next/standalone/` + `.next/static/`.
# We rely on `output: 'standalone'` in next.config.ts.
RUN npm run build

# ── Runtime ─────────────────────────────────────────────────────────
FROM node:${NODE_VERSION}-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user. Alpine's busybox `adduser` differs from the Debian
# version — the flags below are the Alpine-correct invocation.
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 --ingroup nodejs --disabled-password --no-create-home --shell /sbin/nologin nextjs

WORKDIR /app

# Standalone server + its tracked node_modules + public assets +
# pre-built static chunks. The standalone output is self-contained;
# we don't copy package.json or the full node_modules tree.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget --quiet --spider http://localhost:${PORT}/ || exit 1

# `server.js` is the standalone bundle's entry point.
CMD ["node", "server.js"]
