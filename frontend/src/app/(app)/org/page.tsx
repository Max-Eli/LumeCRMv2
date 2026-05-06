/**
 * `/org` — redirects to `/org/dashboard`. The organization surface is
 * sub-page-driven (Dashboard / Business profile / Locations today;
 * Online booking + Integrations land in later sessions); the bare
 * `/org` URL just bounces to the default sub-page so a typed link
 * always lands somewhere coherent. Dashboard is the natural default
 * because it gives both owners and managers a useful read-only view;
 * Business profile + Locations are owner-gated.
 */

import { redirect } from 'next/navigation';

export default function OrgIndex() {
  redirect('/org/dashboard');
}
