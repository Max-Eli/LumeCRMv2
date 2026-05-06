/**
 * Job-title data hooks.
 *
 * Job titles are tenant-scoped reference data — Nurse Practitioner, Aesthetician,
 * Receptionist, etc. Read-only from the frontend for now (mutations happen in
 * Django admin during onboarding; UI lands with tenant settings, Phase 1H).
 *
 * Used today to populate the eligibility selector when configuring service
 * categories. When the booking calendar lands, will also drive the provider
 * dropdown filtered by category eligibility.
 */

'use client';

import { useQuery } from '@tanstack/react-query';

import { api } from './api';

export interface JobTitle {
  id: number;
  name: string;
  is_clinical: boolean;
  sort_order: number;
}

export function useJobTitles() {
  return useQuery<JobTitle[]>({
    queryKey: ['job-titles'],
    queryFn: () => api.get<JobTitle[]>('/api/job-titles/'),
    staleTime: 5 * 60 * 1000,
  });
}
