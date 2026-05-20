/**
 * Lumè design tokens for the staff mobile app.
 *
 * Mirrors the web CRM palette (frontend/src/app/globals.css) so operators
 * see one continuous brand across web and phone. The app is locked to
 * light mode — the web CRM ships no dark mode, so a dark variant here
 * would only create drift.
 */

import { Platform } from 'react-native';

export const colors = {
  /** Chef's Hat — page background. */
  background: '#F3F4F5',
  /** Smoky Black — body text. */
  foreground: '#100C08',
  /** Raised surfaces sit slightly above the page (mobile adaptation —
   *  the web uses a flat card + border; phones read better with lift). */
  card: '#FFFFFF',
  cardForeground: '#100C08',
  /** Drifting Cloud — borders + input outlines. */
  border: '#DBE0E1',
  input: '#DBE0E1',
  muted: '#DBE0E1',
  /** ≈ color-mix(oklab, foreground 60%, background) — the web's derived mid-gray. */
  mutedForeground: '#5F6061',
  /** Smoky Black — primary (dark) buttons. */
  primary: '#100C08',
  primaryForeground: '#F3F4F5',
  secondary: '#DBE0E1',
  secondaryForeground: '#100C08',
  /** Bacchic Burgundy — brand accent + focus ring. */
  accent: '#95122C',
  accentForeground: '#F3F4F5',
  /** Sauce Piquante — destructive actions. */
  destructive: '#CA3F16',
  destructiveForeground: '#F3F4F5',
  ring: '#95122C',
} as const;

export type ColorToken = keyof typeof colors;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
  pill: 999,
} as const;

/** Max width for reading-oriented content (forms, charts, detail
 *  screens). Full-width on a phone; a centred column on an iPad. */
export const layout = {
  contentMaxWidth: 620,
} as const;

export const fontSize = {
  xs: 12,
  sm: 13,
  base: 15,
  md: 17,
  lg: 20,
  xl: 24,
  xxl: 30,
} as const;

/** System fonts for now. Brand fonts (Fraunces serif wordmark, Geist
 *  body) get bundled in a later phase via expo-font. */
export const fonts = Platform.select({
  ios: { sans: 'system-ui', serif: 'Georgia', mono: 'ui-monospace' },
  default: { sans: 'sans-serif', serif: 'serif', mono: 'monospace' },
})!;
