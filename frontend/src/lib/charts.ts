/**
 * Chart notes hooks — provider-only treatment record API.
 *
 * Wraps `/api/chart-notes/`. Read access requires `VIEW_CHART`
 * (provider, owner, manager); write access requires `SIGN_CHART`.
 * Front desk + bookkeeper + marketing get a 403 from the backend
 * — the customer profile's Notes tab handles that with a "no
 * access" UI rather than an error.
 *
 * See [ADR 0015 — Clinical chart notes](../../../docs/decisions/0015-clinical-chart-notes.md)
 * for the design rationale, edit-window semantics, and audit
 * posture.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

export interface ChartNote {
  id: number;
  customer: number;
  appointment_id: number | null;
  appointment_date: string | null;
  appointment_service_name: string;
  body: string;
  author_id: number;
  author_first_name: string;
  author_last_name: string;
  author_email: string;
  author_job_title: string;
  /** Snapshot of the author's clinical-flag at signing. The
   *  legal-status anchor on the record (see ADR 0015). */
  author_was_clinical: boolean;
  signed_at: string;
  /** True once the 60-min typo-correction window has closed. */
  is_locked: boolean;
  /** ISO timestamp of the lock deadline. */
  edit_window_ends_at: string;

  /** When set, this note is an addendum attached to the given
   *  parent. Null for top-level notes. */
  parent_note_id: number | null;

  /** Voided notes survive in the DB but are excluded from clinical
   *  reads when `?include_voided=false`. UI renders struck-through. */
  is_voided: boolean;
  voided_at: string | null;
  voided_reason: string;
  voided_by_first_name: string;
  voided_by_last_name: string;
  voided_by_email: string;

  created_at: string;
  updated_at: string;
}

export interface CreateChartNoteInput {
  customer_id: number;
  appointment_id?: number | null;
  body: string;
}

export interface UpdateChartNoteInput {
  body: string;
}

const CHART_NOTES_KEY = ['chart-notes'] as const;
const customerNotesKey = (customerId: number) =>
  [...CHART_NOTES_KEY, 'customer', customerId] as const;

// ── Read hooks ──────────────────────────────────────────────────────

/** List all chart notes for a customer. Sorted newest first. */
export function useCustomerChartNotes(customerId: number | undefined) {
  return useQuery<ChartNote[]>({
    queryKey: customerNotesKey(customerId ?? 0),
    queryFn: () =>
      api.get<ChartNote[]>(`/api/chart-notes/?customer=${customerId}`),
    enabled: typeof customerId === 'number' && customerId > 0,
    // Notes thread is a hot screen for clinical sessions; refresh
    // when the tab regains focus so a teammate's signature shows up.
    refetchOnWindowFocus: true,
  });
}

// ── Mutations ───────────────────────────────────────────────────────

export function useCreateChartNote() {
  const qc = useQueryClient();
  return useMutation<ChartNote, Error, CreateChartNoteInput>({
    mutationFn: (input) => api.post<ChartNote>('/api/chart-notes/', input),
    onSuccess: (note) => {
      qc.invalidateQueries({ queryKey: customerNotesKey(note.customer) });
    },
  });
}

/** Update a chart note's body. Only valid within the 60-min edit
 *  window AND only for the original author. The backend returns
 *  403 with a message explaining which gate failed (locked vs.
 *  not-the-author); the Notes tab surfaces the message inline. */
export function useUpdateChartNote(noteId: number) {
  const qc = useQueryClient();
  return useMutation<ChartNote, Error, UpdateChartNoteInput>({
    mutationFn: (input) =>
      api.patch<ChartNote>(`/api/chart-notes/${noteId}/`, input),
    onSuccess: (note) => {
      qc.invalidateQueries({ queryKey: customerNotesKey(note.customer) });
    },
  });
}

export interface AddAddendumInput {
  body: string;
}

/** Sign an addendum attached to a locked parent note. Backend
 *  rejects (400) if the parent is unlocked, voided, or itself
 *  an addendum. Any clinical signer can contribute — addenda are
 *  not author-locked. */
export function useAddAddendum(parentId: number) {
  const qc = useQueryClient();
  return useMutation<ChartNote, Error, AddAddendumInput>({
    mutationFn: (input) =>
      api.post<ChartNote>(`/api/chart-notes/${parentId}/addendum/`, input),
    onSuccess: (note) => {
      qc.invalidateQueries({ queryKey: customerNotesKey(note.customer) });
    },
  });
}

export interface VoidNoteInput {
  reason: string;
}

/** Void a chart note (owner / manager only). The note remains in
 *  the DB and the UI renders it struck-through; `?include_voided=false`
 *  excludes it from a clinical read. One-way — there's no un-void. */
export function useVoidChartNote(noteId: number) {
  const qc = useQueryClient();
  return useMutation<ChartNote, Error, VoidNoteInput>({
    mutationFn: (input) =>
      api.post<ChartNote>(`/api/chart-notes/${noteId}/void/`, input),
    onSuccess: (note) => {
      qc.invalidateQueries({ queryKey: customerNotesKey(note.customer) });
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────

/** Role-based UI gate for showing the Notes tab content. The backend
 *  is the security boundary — this is just to hide a tab the user
 *  can't use, mirroring the ROLE_DEFAULTS table in
 *  apps/tenants/permissions.py. Keep in sync if either side changes. */
export function canViewCharts(
  role: 'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing' | undefined,
): boolean {
  return role === 'owner' || role === 'manager' || role === 'provider';
}

/** Role-based UI gate for the "sign new note" form. Same defaults as
 *  the read gate today; kept separate so a future "read-only clinical
 *  reviewer" role can be added without flipping write access too. */
export function canSignCharts(
  role: 'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing' | undefined,
): boolean {
  return role === 'owner' || role === 'manager' || role === 'provider';
}

/** Role-based UI gate for the void button. Mirrors EDIT_SIGNED_CHART
 *  in apps/tenants/permissions.py — owner + manager only. Providers
 *  who need to correct a locked note use addenda instead. */
export function canVoidCharts(
  role: 'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing' | undefined,
): boolean {
  return role === 'owner' || role === 'manager';
}

/** Display name for an author — first + last, falling back to email. */
export function chartAuthorName(note: ChartNote): string {
  const full = `${note.author_first_name} ${note.author_last_name}`.trim();
  return full || note.author_email;
}

/** Minutes remaining in the edit window. Negative when locked. */
export function chartEditMinutesRemaining(note: ChartNote): number {
  if (note.is_locked) return -1;
  const deadline = new Date(note.edit_window_ends_at).getTime();
  const now = Date.now();
  return Math.max(0, Math.ceil((deadline - now) / 60000));
}
