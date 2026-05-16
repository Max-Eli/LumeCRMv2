/**
 * Web app manifest.
 *
 * Served at `/manifest.webmanifest` (Next 16 convention). Gives
 * mobile browsers + iOS the metadata they need when a visitor
 * adds the site to a home screen, and supplies the brand colors
 * for browser chrome theming (Android Chrome address bar, iOS
 * status bar, Edge titlebar).
 *
 * We're not a PWA — no service worker, no `start_url` workflow —
 * but the manifest still wins us:
 *   - correct theme color in browser chrome
 *   - a proper "Add to home screen" label + icon on mobile
 *   - SEO signals about brand identity
 *
 * Theme + background colors are the MP096 palette from globals.css.
 */

import type { MetadataRoute } from 'next';

import { SITE_NAME } from '@/lib/seo';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${SITE_NAME} — The CRM for medical spas`,
    short_name: SITE_NAME,
    description:
      'A HIPAA-compliant CRM built specifically for medical spas.',
    start_url: '/',
    display: 'browser',
    background_color: '#F3F4F5', // Chef's Hat
    theme_color: '#100C08',      // Smoky Black
    icons: [
      {
        src: '/favicon.png',
        sizes: 'any',
        type: 'image/png',
      },
      {
        src: '/logosquare.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any',
      },
    ],
  };
}
