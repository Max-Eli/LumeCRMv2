/**
 * Service-category eligibility helpers.
 *
 * Mirrors the backend rule in `AppointmentSerializer.validate`: a provider can
 * perform a service if the service has no category, or its category has no
 * eligible-job-title rules, or the provider's job_title_id is in the
 * category's `eligible_job_titles` whitelist.
 *
 * Used by the calendar drag-drop to show a "this provider can't do that"
 * affordance before a drop is attempted, and by future create-appointment
 * flows to filter the provider dropdown.
 */

import type { ServiceCategory } from './services';

interface CategoryRefLite {
  id: number;
}

interface ProviderRefLite {
  job_title_id: number | null;
}

interface ServiceRefLite {
  category: CategoryRefLite | null;
}

export interface EligibilityResult {
  ok: boolean;
  /** Human-readable reason when `!ok`. Empty otherwise. */
  reason: string;
}

/**
 * Returns whether the given provider is eligible to perform the given
 * service, based on the provider's job-title membership and the service
 * category's eligibility rules in the supplied list of categories.
 *
 * Categories whose `eligible_job_titles` is empty impose no restriction.
 */
export function isProviderEligible(
  service: ServiceRefLite | null | undefined,
  provider: ProviderRefLite | null | undefined,
  categories: ServiceCategory[] | null | undefined,
): EligibilityResult {
  if (!service || !provider) return { ok: true, reason: '' };
  if (!service.category) return { ok: true, reason: '' };

  const category = (categories ?? []).find((c) => c.id === service.category!.id);
  if (!category) return { ok: true, reason: '' };

  const allowed = category.eligible_job_titles ?? [];
  if (allowed.length === 0) return { ok: true, reason: '' };

  if (!provider.job_title_id) {
    return {
      ok: false,
      reason: 'Provider has no job title set; this category requires one.',
    };
  }

  const match = allowed.some((jt) => jt.id === provider.job_title_id);
  if (match) return { ok: true, reason: '' };

  const allowedNames = allowed.map((jt) => jt.name).join(', ');
  return {
    ok: false,
    reason: `This service can only be performed by: ${allowedNames}.`,
  };
}
