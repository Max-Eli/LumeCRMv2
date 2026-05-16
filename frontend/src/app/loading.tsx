/**
 * Root-level loading.tsx — Next.js shows this fallback whenever a
 * server component in any route is suspending. Per-group loading
 * files (e.g. `(app)/loading.tsx`) can override with chrome-aware
 * variants; this catches everything else (auth, marketing,
 * one-offs).
 */

import { BrandLoader } from '@/components/brand-loader';

export default function Loading() {
  return <BrandLoader />;
}
