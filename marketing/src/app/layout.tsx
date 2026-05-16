import type { Metadata } from 'next';
import { Fraunces, Geist } from 'next/font/google';
import Script from 'next/script';

import { Footer } from '@/components/footer';
import { TopNav } from '@/components/top-nav';
import {
  SITE_DESCRIPTION,
  SITE_NAME,
  SITE_URL,
  jsonLd,
  organizationJsonLd,
  websiteJsonLd,
} from '@/lib/seo';

import './globals.css';

/**
 * Plausible analytics — privacy-first, cookieless, GDPR-compliant
 * without a banner. Loaded only in production so localhost dev
 * traffic doesn't pollute the dashboard.
 *
 * `data-domain` is the slug Plausible uses in its dashboard URL
 * and to match incoming pageviews against. We default to the
 * punycode form of the IDN domain (what HTTP Host headers actually
 * carry on the wire); override via `NEXT_PUBLIC_PLAUSIBLE_DOMAIN`
 * if the Plausible site was set up under a different name.
 *
 * To track outbound link clicks + 404s + file downloads, swap the
 * src to `/js/script.outbound-links.file-downloads.404.js` per
 * https://plausible.io/docs/script-extensions.
 */
const PLAUSIBLE_DOMAIN =
  process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN ?? 'xn--lumcrm-5ua.com';
const PLAUSIBLE_ENABLED = process.env.NODE_ENV === 'production';

const geistSans = Geist({
  variable: '--font-sans',
  subsets: ['latin'],
});

const fraunces = Fraunces({
  variable: '--font-serif',
  subsets: ['latin'],
  axes: ['opsz', 'SOFT'],
});

export const metadata: Metadata = {
  // metadataBase resolves every relative URL in this Metadata object
  // and on every page that extends it — canonical, og:url, og:image,
  // twitter:image. Without it, social previews break and search
  // engines see ambiguous relative references. See lib/seo.ts for
  // the origin used here.
  metadataBase: new URL(SITE_URL),
  title: {
    default: 'Lumè — The CRM for medical spas',
    template: '%s · Lumè',
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  authors: [{ name: SITE_NAME, url: SITE_URL }],
  creator: SITE_NAME,
  publisher: SITE_NAME,
  alternates: {
    canonical: '/',
  },
  icons: {
    icon: [
      { url: '/favicon.png', type: 'image/png' },
    ],
    apple: '/favicon.png',
  },
  manifest: '/manifest.webmanifest',
  openGraph: {
    type: 'website',
    siteName: SITE_NAME,
    title: 'Lumè — The CRM for medical spas',
    description: SITE_DESCRIPTION,
    url: SITE_URL,
    locale: 'en_US',
    // Per-page openGraph.images overrides come from the dynamic
    // opengraph-image.tsx route at the app root.
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Lumè — The CRM for medical spas',
    description: SITE_DESCRIPTION,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  category: 'business',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning on <html>: browser extensions
    // (Scribe, Grammarly, dark-mode injectors, password managers)
    // commonly mutate the <html> element before React hydrates,
    // which would otherwise trigger a hydration mismatch error in
    // the console for every visitor running such an extension.
    // The suppression is scoped to attributes on this single element
    // and does NOT propagate to children — every other component
    // still gets full hydration checking.
    <html
      lang="en"
      className={`${geistSans.variable} ${fraunces.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {PLAUSIBLE_ENABLED ? (
          <Script
            defer
            data-domain={PLAUSIBLE_DOMAIN}
            src="https://plausible.io/js/script.outbound-links.file-downloads.404.js"
            strategy="afterInteractive"
          />
        ) : null}
      </head>
      <body className="min-h-full bg-background text-foreground">
        {/* Site-wide structured data: Organization + WebSite. Page
            files add their own JSON-LD (SoftwareApplication on home,
            BreadcrumbList on deep-dives) without conflict — Google
            reconciles by @id. */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(organizationJsonLd()) }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(websiteJsonLd()) }}
        />
        <TopNav />
        <main className="min-h-[60vh]">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
