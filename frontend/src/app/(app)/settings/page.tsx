/**
 * `/settings` — legacy redirect kept for old bookmarks. The settings
 * surface was renamed to `/org/*` as part of the multi-location
 * rollout (Phase 4E session 2): business profile + locations now live
 * under "Organization" in the sidebar. New code should link to
 * `/org/business` directly.
 */

import { redirect } from 'next/navigation';

export default function SettingsIndex() {
  redirect('/org/business');
}
