import type { NextConfig } from 'next';

/**
 * Next config — production deploy is a containerized Next on AWS
 * Fargate, behind the same ALB as the Django backend.
 *
 * `output: 'standalone'` produces a self-contained server bundle in
 * `.next/standalone/` that we copy into the runtime image. The
 * standalone output trims `node_modules` to only what's actually
 * needed at runtime — typically <100 MB for our app, vs ~600 MB for
 * a full `npm install`.
 *
 * Why not static export: Next 16's static export requires
 * `generateStaticParams` on every dynamic segment with no clean way
 * to declare "any param at runtime, build-time enumerate nothing"
 * for an SPA-style app. The CRM has 24+ dynamic routes; the workaround
 * shells fight Next's page-collection logic in subtle ways. Static
 * export saves ~$50-100/mo of Fargate compute, which isn't worth the
 * deploy-time fragility for a solo team.
 */
const nextConfig: NextConfig = {
  output: 'standalone',
};

export default nextConfig;
