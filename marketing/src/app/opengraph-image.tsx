/**
 * Default Open Graph share-card image (1200x630).
 *
 * Served at `/opengraph-image` and `/twitter-image` automatically
 * by Next 16 when a page doesn't specify its own. Generated at
 * build time via `next/og` (Vercel's edge-renderable Satori
 * subset of CSS).
 *
 * Design intent: brand-aligned and editorial — not the gradient-blob
 * SaaS card every Stripe-style site ships. A cream MP096 background,
 * the serif wordmark in burgundy + black, a single italic accent
 * phrase, a fine ruled line, and a small-caps compliance strip
 * along the foot. Reads like a magazine cover plate, not a banner.
 *
 * Per-page overrides can be added by creating an `opengraph-image.tsx`
 * inside that page's route folder.
 */

import { ImageResponse } from 'next/og';

export const runtime = 'edge';
export const alt = 'Lumè — The CRM for medical spas';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '72px 88px',
          background: '#F3F4F5',
          color: '#100C08',
          fontFamily: 'serif',
        }}
      >
        {/* Top row: eyebrow + brand monogram */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: 18,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            color: '#100C08',
            opacity: 0.6,
          }}
        >
          <span>Lumè · For medical spas</span>
          <span>HIPAA-compliant</span>
        </div>

        {/* Centerpiece: serif headline with italic burgundy accent */}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div
            style={{
              fontSize: 96,
              lineHeight: 1.02,
              letterSpacing: '-0.02em',
              fontWeight: 500,
              display: 'flex',
              flexWrap: 'wrap',
            }}
          >
            <span>Run your medspa from&nbsp;</span>
            <span
              style={{
                fontStyle: 'italic',
                color: '#95122C',
                fontWeight: 400,
              }}
            >
              one platform.
            </span>
          </div>
          <div
            style={{
              marginTop: 32,
              maxWidth: 880,
              fontSize: 28,
              lineHeight: 1.45,
              color: '#100C08',
              opacity: 0.78,
              fontFamily: 'sans-serif',
            }}
          >
            Booking, client charts, e-signed consent, payments, and
            22 reports — built specifically for medspa workflows.
          </div>
        </div>

        {/* Bottom: fine rule + small-caps row */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div style={{ height: 1, width: '100%', background: '#DBE0E1' }} />
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              fontSize: 18,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: '#100C08',
              opacity: 0.6,
              fontFamily: 'sans-serif',
            }}
          >
            <span>lumècrm.com</span>
            <span>Booking · Charts · Forms · Payments · Reports</span>
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
