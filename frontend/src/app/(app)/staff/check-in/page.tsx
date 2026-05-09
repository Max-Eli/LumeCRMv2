/**
 * `/staff/check-in` — manager-only time-tracking admin surface.
 *
 * The mobile-friendly clock-in panel for individual employees lives
 * at `/clock-in`. This page is for the manager: review who's
 * currently on the clock, audit recent shifts, fix forgot-to-
 * clock-out entries, and (future) kick into payroll export.
 *
 * Non-managers who land here only see their own entries (the
 * backend filters by membership for non-MANAGE_STAFF callers).
 */

'use client';

import {
  AlertCircle,
  Clock,
  Loader2,
  Pencil,
  Trash2,
  UserCircle2,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type TimeEntry,
  SOURCE_LABELS,
  elapsedSeconds,
  formatDuration,
  totalSeconds,
  useActiveShifts,
  useDeleteTimeEntry,
  useTimeEntries,
  useUpdateTimeEntry,
} from '@/lib/timetracking';
import { cn } from '@/lib/utils';

type StateFilter = 'all' | 'open' | 'closed';

export default function StaffCheckInPage() {
  const me = useCurrentMembership();
  const isManager = me?.role === 'owner' || me?.role === 'manager';

  const [filter, setFilter] = useState<StateFilter>('all');
  const [days, setDays] = useState(7);
  // Snap to start-of-today at mount, then compute the from-ISO
  // off that fixed reference. Lazy useState initializers are
  // allowed by the React Compiler purity rule because they run
  // exactly once at mount; reading `Date.now()` directly during
  // render is not.
  const [refMs] = useState<number>(() =>
    new Date(new Date().setHours(0, 0, 0, 0)).getTime(),
  );
  const fromIso = useMemo(
    () =>
      new Date(refMs - (days - 1) * 24 * 60 * 60 * 1000).toISOString(),
    [refMs, days],
  );

  const entries = useTimeEntries({
    from: fromIso,
    open: filter === 'all' ? undefined : filter === 'open',
  });
  const active = useActiveShifts();

  return (
    <div className="px-8 py-8 space-y-6">
      <PageHeader
        title="Staff check-in"
        description={
          isManager
            ? 'Review who is on the clock, audit recent shifts, and correct missing punches.'
            : 'Your recent shifts. Use the mobile clock-in page to start or end a shift.'
        }
        actions={
          <Button render={<Link href="/clock-in" />} nativeButton={false}>
            <Clock className="size-4" />
            Clock-in panel
          </Button>
        }
      />

      <ActiveStrip
        entries={active.data ?? []}
        isLoading={active.isLoading}
      />

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="inline-flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
          {(['all', 'open', 'closed'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 h-8 rounded-md text-sm transition-colors capitalize',
                filter === f
                  ? 'bg-card text-foreground shadow-sm font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="inline-flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Last</span>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border bg-card px-2 h-8 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value={1}>1 day</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </div>
      </div>

      {entries.error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Could not load shifts.
        </div>
      ) : entries.isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin mx-auto mb-2" />
          Loading shifts…
        </div>
      ) : (entries.data ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed bg-muted/20 p-10 text-center">
          <Clock className="size-8 mx-auto text-muted-foreground/50 mb-3" />
          <p className="text-sm text-muted-foreground">
            No shifts in the selected range.
          </p>
        </div>
      ) : (
        <ShiftsTable
          entries={entries.data!}
          canEdit={!!isManager}
        />
      )}
    </div>
  );
}

// ── Active strip ────────────────────────────────────────────────────

function ActiveStrip({
  entries,
  isLoading,
}: {
  entries: TimeEntry[];
  isLoading: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (entries.length === 0) return;
    const id = setInterval(() => setNow(Date.now()), 1000 * 30);
    return () => clearInterval(id);
  }, [entries.length]);

  if (isLoading) return null;
  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-muted/20 px-6 py-5 text-sm text-muted-foreground inline-flex items-center gap-2">
        <Clock className="size-4" />
        Nobody is on the clock right now.
      </div>
    );
  }
  return (
    <section>
      <header className="mb-2">
        <h2 className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
          On the clock
        </h2>
      </header>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {entries.map((entry) => {
          const fullName = (
            `${entry.membership_user_first_name ?? ''} ${entry.membership_user_last_name ?? ''}`
              .trim() || entry.membership_user_email
          );
          return (
            <div
              key={entry.id}
              className="rounded-lg border bg-emerald-50/60 px-4 py-3 flex items-start gap-3"
            >
              <span className="size-2 rounded-full bg-emerald-500 animate-pulse mt-1.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{fullName}</p>
                <p className="text-xs text-muted-foreground capitalize truncate">
                  {entry.membership_role.replace('_', ' ')}
                </p>
                <p className="text-xs text-emerald-800 mt-1 font-mono tabular-nums">
                  {formatDuration(elapsedSeconds(entry, now))} ·{' '}
                  since{' '}
                  {new Date(entry.clock_in_at).toLocaleTimeString(undefined, {
                    hour: 'numeric',
                    minute: '2-digit',
                  })}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ── Shifts table ────────────────────────────────────────────────────

function ShiftsTable({
  entries,
  canEdit,
}: {
  entries: TimeEntry[];
  canEdit: boolean;
}) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const total = totalSeconds(entries);

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {entries.length} shift{entries.length === 1 ? '' : 's'} · total{' '}
        <span className="font-mono">{formatDuration(total)}</span>
      </p>
      <div className="rounded-lg border bg-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/30 hover:bg-muted/30">
              <TableHead className="w-[24%]">Employee</TableHead>
              <TableHead className="w-[140px]">Date</TableHead>
              <TableHead className="w-[110px]">Clock in</TableHead>
              <TableHead className="w-[110px]">Clock out</TableHead>
              <TableHead className="w-[100px] text-right">Duration</TableHead>
              <TableHead className="w-[110px]">Source</TableHead>
              <TableHead>Notes</TableHead>
              {canEdit ? <TableHead className="w-[90px]" /> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) =>
              editingId === entry.id ? (
                <EditRow
                  key={entry.id}
                  entry={entry}
                  onClose={() => setEditingId(null)}
                />
              ) : (
                <ShiftRow
                  key={entry.id}
                  entry={entry}
                  canEdit={canEdit}
                  onEdit={() => setEditingId(entry.id)}
                />
              ),
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function ShiftRow({
  entry,
  canEdit,
  onEdit,
}: {
  entry: TimeEntry;
  canEdit: boolean;
  onEdit: () => void;
}) {
  const remove = useDeleteTimeEntry();
  const fullName = (
    `${entry.membership_user_first_name ?? ''} ${entry.membership_user_last_name ?? ''}`
      .trim() || entry.membership_user_email
  );

  const onDelete = () => {
    if (
      !confirm(
        `Delete ${fullName}'s shift on ${new Date(entry.clock_in_at).toLocaleDateString()}? This is logged in the audit trail.`,
      )
    ) {
      return;
    }
    remove.mutate(entry.id, {
      onSuccess: () => toast.success('Shift deleted'),
      onError: () => toast.error("Couldn't delete shift."),
    });
  };

  return (
    <TableRow>
      <TableCell className="py-3.5">
        <div className="flex items-center gap-3">
          <div className="size-8 rounded-full bg-stone-100 text-stone-700 flex items-center justify-center text-xs font-medium uppercase shrink-0">
            <UserCircle2 className="size-4" />
          </div>
          <div className="min-w-0">
            <p className="font-medium truncate">{fullName}</p>
            <p className="text-xs text-muted-foreground capitalize truncate">
              {entry.membership_role.replace('_', ' ')}
            </p>
          </div>
        </div>
      </TableCell>
      <TableCell className="text-xs">
        {new Date(entry.clock_in_at).toLocaleDateString(undefined, {
          weekday: 'short',
          month: 'short',
          day: 'numeric',
        })}
      </TableCell>
      <TableCell className="text-xs font-mono tabular-nums">
        {new Date(entry.clock_in_at).toLocaleTimeString(undefined, {
          hour: 'numeric',
          minute: '2-digit',
        })}
      </TableCell>
      <TableCell className="text-xs font-mono tabular-nums">
        {entry.clock_out_at ? (
          new Date(entry.clock_out_at).toLocaleTimeString(undefined, {
            hour: 'numeric',
            minute: '2-digit',
          })
        ) : (
          <span className="inline-flex items-center gap-1 text-amber-700">
            <span className="size-1.5 rounded-full bg-amber-500 animate-pulse" />
            open
          </span>
        )}
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">
        {formatDuration(entry.duration_seconds)}
      </TableCell>
      <TableCell>
        <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {SOURCE_LABELS[entry.source]}
        </span>
      </TableCell>
      <TableCell className="max-w-md text-xs text-muted-foreground">
        {entry.edited_at ? (
          <p className="inline-flex items-center gap-1 text-amber-700 mb-0.5">
            <AlertCircle className="size-3" />
            Edited{' '}
            {new Date(entry.edited_at).toLocaleDateString()}
            {entry.edited_by_email ? <> by {entry.edited_by_email}</> : null}
          </p>
        ) : null}
        <p className="truncate">{entry.notes || '—'}</p>
      </TableCell>
      {canEdit ? (
        <TableCell>
          <div className="inline-flex items-center gap-1">
            <button
              type="button"
              onClick={onEdit}
              className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              aria-label="Edit shift"
            >
              <Pencil className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={onDelete}
              disabled={remove.isPending}
              className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive transition-colors disabled:opacity-50"
              aria-label="Delete shift"
            >
              {remove.isPending ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Trash2 className="size-3.5" />
              )}
            </button>
          </div>
        </TableCell>
      ) : null}
    </TableRow>
  );
}

function EditRow({
  entry,
  onClose,
}: {
  entry: TimeEntry;
  onClose: () => void;
}) {
  const update = useUpdateTimeEntry(entry.id);
  const [clockIn, setClockIn] = useState(toLocalInput(entry.clock_in_at));
  const [clockOut, setClockOut] = useState(
    entry.clock_out_at ? toLocalInput(entry.clock_out_at) : '',
  );
  const [notes, setNotes] = useState(entry.notes);

  const onSave = () => {
    if (!clockIn) {
      toast.error('Clock-in time is required.');
      return;
    }
    update.mutate(
      {
        clock_in_at: fromLocalInput(clockIn),
        clock_out_at: clockOut ? fromLocalInput(clockOut) : null,
        notes,
      },
      {
        onSuccess: () => {
          toast.success('Shift updated');
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as Record<string, unknown>;
            const detail =
              typeof body.detail === 'string'
                ? body.detail
                : typeof body.clock_out_at === 'string'
                  ? body.clock_out_at as string
                  : null;
            toast.error(detail ?? "Couldn't save.");
          } else {
            toast.error("Couldn't save.");
          }
        },
      },
    );
  };

  return (
    <TableRow className="bg-amber-50/40">
      <TableCell className="py-3" colSpan={8}>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <div>
            <label className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
              Clock in
            </label>
            <Input
              type="datetime-local"
              value={clockIn}
              onChange={(e) => setClockIn(e.target.value)}
              className="mt-1 font-mono text-base"
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
              Clock out
            </label>
            <Input
              type="datetime-local"
              value={clockOut}
              onChange={(e) => setClockOut(e.target.value)}
              className="mt-1 font-mono text-base"
            />
          </div>
          <div className="md:col-span-2">
            <label className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
              Notes
            </label>
            <Input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="mt-1"
              placeholder="e.g. forgot to clock out — corrected"
            />
          </div>
          <div className="md:col-span-4 flex items-center justify-end gap-2">
            <Button variant="outline" onClick={onClose} disabled={update.isPending}>
              Cancel
            </Button>
            <Button onClick={onSave} disabled={update.isPending}>
              {update.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : null}
              Save
            </Button>
          </div>
        </div>
      </TableCell>
    </TableRow>
  );
}

// ── datetime-local <-> ISO helpers ──────────────────────────────────

/** Convert ISO 8601 to "YYYY-MM-DDTHH:MM" for <input type="datetime-local">.
 *  The input ignores timezone — we render in the user's local time. */
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
    + `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** Convert "YYYY-MM-DDTHH:MM" (local) back to ISO 8601 (UTC). */
function fromLocalInput(local: string): string {
  return new Date(local).toISOString();
}
