/**
 * Appointment activity log — full audit trail for a single appointment.
 *
 * Reachable from the calendar's appointment popover via the small "Logs"
 * button, which opens this page in a new tab so the calendar stays in
 * the original window. Pulls from `/api/appointments/{id}/activity/`,
 * which returns the most recent 50 audit entries (filtered server-side
 * to entries the requesting user is allowed to see).
 *
 * Audit entries are immutable (`apps.audit.AuditLog` rejects UPDATE /
 * DELETE at the model layer) — this page is read-only by design. Any
 * editing of the appointment itself happens back on the calendar.
 */

'use client';

import { Activity, Calendar, Clock, User } from 'lucide-react';
import { use } from 'react';

import { PageHeader } from '@/components/page-header';
import { Card, CardContent } from '@/components/ui/card';
import {
  STATUS_LABELS,
  type ActivityEntry,
  type AppointmentStatus,
  useAppointment,
  useAppointmentActivity,
} from '@/lib/appointments';

const DEFAULT_TIMEZONE = 'America/New_York';

interface LogsPageProps {
  params: Promise<{ id: string }>;
}

export default function AppointmentLogsPage({ params }: LogsPageProps) {
  const { id: idStr } = use(params);
  const id = Number(idStr);

  const { data: appointment, isLoading: loadingAppt } = useAppointment(id);
  const { data: activity, isLoading: loadingActivity } = useAppointmentActivity(id, true);
  const entries = activity ?? [];

  const tz = DEFAULT_TIMEZONE;
  const customer = appointment?.customer.full_name ?? '';
  const service = appointment?.service.name ?? '';
  const start = appointment ? formatLongDateTime(appointment.start_time, tz) : '';

  return (
    <div className="px-10 py-10 max-w-3xl">
      <PageHeader
        title="Activity log"
        description={
          appointment
            ? `${customer} · ${service} · ${start}`
            : 'Loading appointment context…'
        }
        back={{ href: '/calendar', label: 'Back to calendar' }}
      />

      <Card>
        <CardContent className="p-0">
          {loadingActivity && entries.length === 0 ? (
            <p className="px-6 py-8 text-sm text-muted-foreground">Loading activity…</p>
          ) : !loadingAppt && entries.length === 0 ? (
            <EmptyState />
          ) : (
            <ol className="divide-y divide-border/60">
              {entries.map((entry) => (
                <LogRow key={entry.id} entry={entry} timezone={tz} />
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      {entries.length === 50 ? (
        <p className="text-[11px] text-muted-foreground/80 mt-3">
          Showing the most recent 50 entries. Older history is in the admin
          audit log.
        </p>
      ) : null}
    </div>
  );
}

function LogRow({ entry, timezone }: { entry: ActivityEntry; timezone: string }) {
  const description = describeEntry(entry, timezone);
  const ago = formatRelative(entry.timestamp);
  const exact = formatExactDateTime(entry.timestamp, timezone);
  const actor = actorName(entry);

  return (
    <li className="flex items-start gap-3 px-6 py-4">
      <ActionGlyph action={entry.action} />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-foreground">{description}</p>
        <p className="text-[11px] text-muted-foreground mt-1 font-mono tabular-nums">
          {exact} · {ago}
          {actor ? <span className="text-muted-foreground/80"> · {actor}</span> : null}
        </p>
      </div>
    </li>
  );
}

function ActionGlyph({ action }: { action: string }) {
  const icon =
    action === 'create' ? (
      <Calendar className="size-3.5" />
    ) : action === 'read' ? (
      <User className="size-3.5" />
    ) : action === 'update' ? (
      <Activity className="size-3.5" />
    ) : (
      <Clock className="size-3.5" />
    );
  return (
    <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground mt-0.5">
      {icon}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="px-6 py-12 text-center">
      <div className="inline-flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground mb-3">
        <Activity className="size-4" />
      </div>
      <p className="text-sm text-foreground font-medium">No activity yet</p>
      <p className="text-xs text-muted-foreground mt-1">
        Audit entries appear here as the appointment is updated.
      </p>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

function describeEntry(entry: ActivityEntry, timezone: string): string {
  if (entry.action === 'create') return 'Appointment created';
  if (entry.action === 'delete') return 'Appointment deleted';
  if (entry.action === 'read') return 'Viewed';

  if (entry.action === 'update') {
    const m = entry.metadata ?? {};
    // A single PATCH can carry multiple semantic events: a status
    // transition AND a reschedule, etc. Render them as a stacked phrase
    // joined by " · " so all the changes show in one row.
    const parts: string[] = [];

    if (m.transition && m.to_status) {
      const from = STATUS_LABELS[m.from_status as AppointmentStatus] ?? '?';
      const to = STATUS_LABELS[m.to_status as AppointmentStatus] ?? '?';
      const reason =
        typeof m.cancelled_reason === 'string' ? m.cancelled_reason : '';
      // Surface the undo-check-in flow with its verb, not "Confirmed."
      if (m.from_status === 'checked_in' && m.to_status === 'confirmed') {
        parts.push('Check-in undone');
      } else if (m.to_status === 'cancelled' && reason) {
        // Show why it was cancelled — the audit trail's whole point
        // for accidental / duplicate bookings.
        parts.push(`Status: ${from} → ${to} · ${reason}`);
      } else {
        parts.push(`Status: ${from} → ${to}`);
      }
    }

    if (m.rescheduled && m.from_start && m.to_start) {
      const before = formatExactDateTime(String(m.from_start), timezone);
      const after = formatExactDateTime(String(m.to_start), timezone);
      parts.push(`Rescheduled ${before} → ${after}`);
    }

    if (m.provider_changed) {
      parts.push(
        `Provider changed (id ${m.from_provider_id ?? '?'} → ${m.to_provider_id ?? '?'})`,
      );
    }

    if (parts.length > 0) return parts.join(' · ');

    // Fallback for plain edits we didn't enrich (notes update, etc.)
    const fields = m.fields_changed ?? [];
    return fields.length ? `Edited ${fields.join(', ')}` : 'Edited';
  }

  return entry.action;
}

function actorName(entry: ActivityEntry): string {
  if (entry.user_first_name) {
    return `by ${`${entry.user_first_name} ${entry.user_last_name ?? ''}`.trim()}`;
  }
  if (entry.user_email) return `by ${entry.user_email}`;
  return '';
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const diffSec = Math.floor((Date.now() - then) / 1000);
  if (diffSec < 30) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}h ago`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatExactDateTime(iso: string, timezone: string): string {
  return new Date(iso).toLocaleString('en-US', {
    timeZone: timezone,
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

function formatLongDateTime(iso: string, timezone: string): string {
  return new Date(iso).toLocaleString('en-US', {
    timeZone: timezone,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}
