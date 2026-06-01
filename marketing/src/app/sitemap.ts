/**
 * sitemap.xml route, generated from the live page set.
 *
 * Next 16 convention: an `app/sitemap.ts` that default-exports an
 * array of entries is automatically served at `/sitemap.xml` with
 * the correct `Content-Type`. The values are absolute URLs — we
 * rely on `metadataBase` for the origin but Next sitemap entries
 * need the full URL, so we compose them from `SITE_URL` directly.
 *
 * When new pages land, add them here. Feature deep-dives are
 * itemized rather than glob-collected so we keep the priority
 * + change-frequency knobs explicit per page.
 */

import type { MetadataRoute } from 'next';

import { POSTS } from '@/lib/blog';
import { SITE_URL_ASCII } from '@/lib/seo';

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();

  // Higher-priority pages: home, demo (the conversion endpoint),
  // and the entry-point category pages. Feature deep-dives are
  // 0.7. Legal pages (when they exist) will be 0.3.
  return [
    { url: `${SITE_URL_ASCII}/`, lastModified: now, changeFrequency: 'weekly', priority: 1 },
    { url: `${SITE_URL_ASCII}/medspas`, lastModified: now, changeFrequency: 'monthly', priority: 0.9 },
    { url: `${SITE_URL_ASCII}/features`, lastModified: now, changeFrequency: 'monthly', priority: 0.9 },
    { url: `${SITE_URL_ASCII}/pricing`, lastModified: now, changeFrequency: 'monthly', priority: 0.9 },
    { url: `${SITE_URL_ASCII}/security`, lastModified: now, changeFrequency: 'monthly', priority: 0.8 },
    { url: `${SITE_URL_ASCII}/about`, lastModified: now, changeFrequency: 'monthly', priority: 0.6 },
    { url: `${SITE_URL_ASCII}/demo`, lastModified: now, changeFrequency: 'monthly', priority: 0.9 },

    // Compare page — high priority: targets competitor-search queries
    // and AI search engines looking for direct comparisons.
    { url: `${SITE_URL_ASCII}/compare`, lastModified: now, changeFrequency: 'monthly', priority: 0.9 },

    { url: `${SITE_URL_ASCII}/features/booking`, lastModified: now, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL_ASCII}/features/charts`, lastModified: now, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL_ASCII}/features/forms`, lastModified: now, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL_ASCII}/features/payments`, lastModified: now, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL_ASCII}/features/reports`, lastModified: now, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${SITE_URL_ASCII}/features/multi-location`, lastModified: now, changeFrequency: 'monthly', priority: 0.7 },

    // Journal index + individual posts. High priority because the
    // blog is one of the main inbound surfaces. Per-post lastModified
    // comes from the published date in lib/blog.ts.
    { url: `${SITE_URL_ASCII}/blog`, lastModified: now, changeFrequency: 'weekly', priority: 0.8 },
    ...POSTS.map((p) => ({
      url: `${SITE_URL_ASCII}/blog/${p.slug}`,
      lastModified: new Date(p.updatedAt ?? p.publishedAt),
      changeFrequency: 'monthly' as const,
      priority: 0.7,
    })),

    // Legal pages — lower priority because they don't earn organic
    // traffic, but indexed so footer-driven and direct hits resolve.
    { url: `${SITE_URL_ASCII}/privacy`, lastModified: now, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${SITE_URL_ASCII}/terms`, lastModified: now, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${SITE_URL_ASCII}/baa`, lastModified: now, changeFrequency: 'yearly', priority: 0.3 },
  ];
}
