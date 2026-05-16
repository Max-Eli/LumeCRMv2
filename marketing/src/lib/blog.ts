/**
 * Blog post metadata.
 *
 * Single source of truth for: the blog index, the per-post Article
 * JSON-LD, the sitemap, and the "related posts" bottom-of-page rail.
 *
 * Content lives in the individual post files under `app/blog/<slug>/
 * page.tsx` because each post composes structured React (callouts,
 * tables, pull-quotes) inline. Metadata travels in this file so
 * touching a post slug never requires editing five places.
 *
 * Ordering: newest first. The index page renders in array order.
 */

export interface BlogPostMeta {
  slug: string;
  title: string;
  /** Card-deck summary, ~25 words. Used on index, OG, meta description. */
  summary: string;
  /** ISO 8601. Used in JSON-LD `datePublished` and on the post hero. */
  publishedAt: string;
  /** Update timestamp, ISO 8601. Defaults to publishedAt when unset. */
  updatedAt?: string;
  /** Word-count-derived; rounded to nearest minute. */
  readMinutes: number;
  /** Editorial category. One per post. */
  category:
    | 'Compliance'
    | 'Operations'
    | 'Software selection'
    | 'Industry';
  /** Author display name. */
  author: string;
}

export const POSTS: BlogPostMeta[] = [
  {
    slug: 'hipaa-checklist-for-medspas',
    title:
      'The HIPAA checklist for medspas: what you actually need before paying clients walk in',
    summary:
      'A line-by-line breakdown of HIPAA Security Rule obligations for medical spas, the state-law overlays in California, New York, Texas, and Massachusetts, and the vendor BAA cascade most operators miss.',
    publishedAt: '2026-05-15',
    readMinutes: 12,
    category: 'Compliance',
    author: 'The Lumè team',
  },
  {
    slug: 'reducing-medspa-no-shows',
    title:
      'Reducing medspa no-shows: the data, the math, and what actually works',
    summary:
      'No-show rates above 20% are common in spas without deposits. Reminders and deposit-on-book together can cut that to 5-8%. The math, the studies, and the operational playbook.',
    publishedAt: '2026-05-14',
    readMinutes: 9,
    category: 'Operations',
    author: 'The Lumè team',
  },
  {
    slug: 'when-to-migrate-off-a-salon-crm',
    title:
      'When to migrate off Mindbody, Vagaro, or Boulevard (and how to scope the transition)',
    summary:
      'Three signals you have outgrown a salon-first CRM, the data you must export before you sign anywhere new, and the realistic timeline for a 2-4 week migration.',
    publishedAt: '2026-05-13',
    readMinutes: 10,
    category: 'Software selection',
    author: 'The Lumè team',
  },
  {
    slug: 'what-a-baa-actually-covers',
    title:
      'What a Business Associate Agreement actually covers (and why some CRMs charge extra for one)',
    summary:
      'HIPAA §164.504(e) sets out eight things every BAA must address. Here is the plain-English version, the common loopholes, and how to read a vendor BAA before signing.',
    publishedAt: '2026-05-12',
    readMinutes: 8,
    category: 'Compliance',
    author: 'The Lumè team',
  },
];

export function findPost(slug: string): BlogPostMeta | undefined {
  return POSTS.find((p) => p.slug === slug);
}

/** Get up to N posts other than the one passed in. */
export function relatedPosts(currentSlug: string, n = 2): BlogPostMeta[] {
  return POSTS.filter((p) => p.slug !== currentSlug).slice(0, n);
}

/** Pretty-print an ISO date as "May 15, 2026". */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  const months = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];
  return `${months[m - 1]} ${d}, ${y}`;
}
