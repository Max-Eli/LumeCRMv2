import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * URL of the CRM application. In production this is the per-tenant
 * subdomain root (e.g. `https://app.lumècrm.com` if we use a single
 * staff-facing subdomain, or the explicit `<tenant>.lumècrm.com` if
 * the operator already knows their slug). In dev it's the local CRM
 * Next app on port 3000.
 *
 * Set via NEXT_PUBLIC_APP_URL env var; defaults to localhost:3000.
 */
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000';
