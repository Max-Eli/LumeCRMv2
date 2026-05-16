/**
 * Site-wide SEO constants and JSON-LD builders.
 *
 * One source of truth for: production origin, brand name, default
 * social-share copy, and the structured-data envelopes we attach to
 * specific pages. Pages import what they need; the root layout
 * imports the defaults; the sitemap/robots routes import the origin.
 *
 * Production origin is the IDN form `https://lumècrm.com`. The URL
 * constructor serializes that to its punycode `xn--lumcrm-5ua.com`
 * form when set as `metadataBase`, which is what search engines
 * normalize to internally — so canonical URLs and og:url tags end
 * up in punycode without us writing it by hand.
 */

export const SITE_NAME = 'Lumè';
export const SITE_LEGAL_NAME = 'Lumè CRM';

/** Brand-facing origin (with the IDN accent). Used in human-facing
 *  copy and as the seed for `metadataBase`, where Next normalizes
 *  via the `URL` constructor. Override via `NEXT_PUBLIC_SITE_URL`
 *  for preview deployments. */
export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? 'https://lumècrm.com';

/** ASCII-normalized origin (punycode for the IDN). Use this in
 *  sitemap.xml, robots.txt, and any other place that goes straight
 *  into a wire-level response without passing through Next's
 *  metadata layer — so the sitemap stays consistent with the
 *  punycode form crawlers see in canonical / og:url tags. The URL
 *  constructor strips the trailing slash via `origin`, giving us a
 *  pure scheme + host. */
export const SITE_URL_ASCII = new URL(SITE_URL).origin;

/** Tagline used in the social-share OG image and meta description
 *  fallback. Kept short — six words, claims the category. */
export const SITE_TAGLINE = 'The CRM for medical spas.';

/** Default share-card description. Page-level metadata overrides this. */
export const SITE_DESCRIPTION =
  'A HIPAA-compliant CRM built specifically for medical spas. Booking, client charts, e-signed consent forms, payments, and 22 real-time reports — designed for the way medspas actually run.';

/** Founding year — used in Organization JSON-LD. */
export const SITE_FOUNDED = 2026;

// ── JSON-LD builders ────────────────────────────────────────────────

/** Render a `<script type="application/ld+json">` payload. Pass the
 *  return value into a `<script>` tag's `dangerouslySetInnerHTML` —
 *  Next 16 handles deduping inside the head. */
export function jsonLd(payload: Record<string, unknown>): string {
  return JSON.stringify(payload);
}

/** The site-wide Organization record. One per page is fine; Google
 *  reconciles by `@id`. */
export function organizationJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    '@id': `${SITE_URL_ASCII}#organization`,
    name: SITE_LEGAL_NAME,
    url: SITE_URL_ASCII,
    logo: `${SITE_URL_ASCII}/logosquare.png`,
    foundingDate: String(SITE_FOUNDED),
    description: SITE_DESCRIPTION,
  };
}

/** WebSite record with a search action — eligible for sitelinks
 *  search box treatment in SERPs once we have site search. We don't
 *  yet, so we omit the `potentialAction` for now. */
export function websiteJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    '@id': `${SITE_URL_ASCII}#website`,
    url: SITE_URL_ASCII,
    name: SITE_NAME,
    description: SITE_DESCRIPTION,
    publisher: { '@id': `${SITE_URL_ASCII}#organization` },
  };
}

/** SoftwareApplication record for the home page. `BusinessApplication`
 *  category is correct for B2B SaaS; the `applicationSubCategory`
 *  narrows it to the vertical so Google's product knowledge graph
 *  treats it as a medspa CRM rather than a generic SaaS. */
export function softwareApplicationJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    '@id': `${SITE_URL_ASCII}#software`,
    name: SITE_LEGAL_NAME,
    applicationCategory: 'BusinessApplication',
    applicationSubCategory: 'Medical Spa CRM',
    operatingSystem: 'Web',
    description: SITE_DESCRIPTION,
    url: SITE_URL_ASCII,
    publisher: { '@id': `${SITE_URL_ASCII}#organization` },
    offers: {
      '@type': 'Offer',
      priceCurrency: 'USD',
      // No public price; pricing is request-a-quote. We omit `price`
      // entirely rather than fake one — Google docs explicitly
      // permit Offers without a price for quote-based products.
      availability: 'https://schema.org/InStock',
      url: `${SITE_URL_ASCII}/pricing`,
    },
    featureList: [
      'Multi-provider booking calendar',
      'Client charts with treatment history',
      'E-signed consent forms with audit trail',
      'Invoicing and end-of-day reconciliation',
      '22 financial, staff, guest, and operations reports',
      'Multi-location org rollup',
      'HIPAA-compliant architecture with BAA',
    ],
  };
}

/** BreadcrumbList for feature deep-dive pages. Pages pass `(label,
 *  href)` pairs in document order. */
export function breadcrumbJsonLd(
  items: { name: string; path: string }[],
) {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: item.name,
      item: `${SITE_URL_ASCII}${item.path}`,
    })),
  };
}
