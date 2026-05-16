/**
 * robots.txt route.
 *
 * The marketing site is fully public and aggressively pre-rendered;
 * we want every page indexed. The CRM (a different deployment at
 * `<tenant>.lumècrm.com`) handles its own de-indexing in its own
 * `robots.ts`. Nothing on this host serves PHI, so the policy here
 * is a simple "allow all + here's the sitemap."
 *
 * Specific bots that we've had reason to block (scrapers training
 * on copy, etc.) can be added per-user-agent. Empty list for now.
 */

import type { MetadataRoute } from 'next';

import { SITE_URL_ASCII } from '@/lib/seo';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
      },
    ],
    sitemap: `${SITE_URL_ASCII}/sitemap.xml`,
    host: SITE_URL_ASCII,
  };
}
