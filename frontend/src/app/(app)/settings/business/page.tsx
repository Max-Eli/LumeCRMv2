/**
 * `/settings/business` — legacy redirect kept for old bookmarks. The
 * business profile lives at `/org/business` now (renamed during the
 * multi-location rollout, Phase 4E session 2). Per-site fields
 * (address, hours, phone) moved to per-location editing at
 * `/org/locations/[id]`.
 */

import { redirect } from 'next/navigation';

export default function LegacyBusinessSettingsRedirect() {
  redirect('/org/business');
}
