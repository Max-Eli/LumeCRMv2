/**
 * `/portal` — customer-portal dashboard. The first surface a customer
 * lands on after signing in.
 *
 * Three cards stacked on mobile / 2x2 on desktop:
 *
 *   - **Next appointment** — most-immediate upcoming slot, with the
 *     service/provider/location and a "Cancel" affordance when the
 *     status allows it.
 *   - **Recent activity** — last completed appointment for context.
 *   - **Quick actions** — links into the deeper portal surfaces
 *     (appointments list, profile management).
 *
 * Branding: the layout sets `--portal-brand`; cards use it for
 * accent strokes + button surfaces so each spa looks distinctly
 * theirs.
 */

'use client';

import {
  ArrowRight,
  CalendarClock,
  MapPin,
  Sparkles,
  UserCircle2,
} from 'lucide-react';
import Link from 'next/link';
import { useMemo } from 'react';

import {
  type PortalAppointment,
  usePortalAppointments,
  usePortalMe,
} from '@/lib/portal';

import { Button } from '@/components/ui/button';

export default function PortalHomePage() {
  const { data: me } = usePortalMe();
  const { data: appointments, isLoading } = usePortalAppointments();

  const { nextUpcoming, lastCompleted } = useMemo(() => {
    const list = appointments ?? [];
    const now = Date.now();
    const upcoming = list
      .filter((a) => new Date(a.start_time).getTime() > now && a.status !== 'cancelled' && a.status !== 'no_show')
      .sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime());
    const completed = list
      .filter((a) => a.status === 'completed')
      .sort((a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime());
    return {
      nextUpcoming: upcoming[0] ?? null,
      lastCompleted: completed[0] ?? null,
    };
  }, [appointments]);

  return (
    <div className="max-w-4xl mx-auto w-full px-6 py-10">
      <div className="mb-8">
        <p className="text-sm text-muted-foreground">
          Welcome back{me ? `, ${me.first_name}` : ''}.
        </p>
        <h1 className="font-serif text-3xl font-semibold tracking-tight mt-1">
          Your {me?.tenant.name ?? 'spa'} account
        </h1>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <NextAppointmentCard appointment={nextUpcoming} />
          <RecentActivityCard appointment={lastCompleted} />
          <QuickActionsCard />
          {me ? <ContactCard me={me} /> : null}
        </div>
      )}
    </div>
  );
}

// ── Cards ───────────────────────────────────────────────────────────


function NextAppointmentCard({ appointment }: { appointment: PortalAppointment | null }) {
  return (
    <article className="rounded-xl border bg-card shadow-sm overflow-hidden">
      <div
        className="h-1 w-full"
        style={{ background: 'var(--portal-brand, #1f2937)' }}
        aria-hidden
      />
      <div className="p-5">
        <div className="flex items-center gap-2 mb-3">
          <CalendarClock className="size-4 text-muted-foreground" />
          <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
            Next appointment
          </h2>
        </div>
        {appointment ? (
          <>
            <p className="text-base font-medium">{appointment.service_name}</p>
            <p className="text-sm text-muted-foreground mt-0.5">
              {formatFullDate(appointment.start_time, appointment.location_timezone)}
            </p>
            <div className="text-xs text-muted-foreground mt-3 space-y-1">
              {appointment.provider_name ? (
                <p className="flex items-center gap-1.5">
                  <UserCircle2 className="size-3" />
                  with {appointment.provider_name}
                </p>
              ) : null}
              <p className="flex items-center gap-1.5">
                <MapPin className="size-3" />
                {appointment.location_name}
              </p>
            </div>
            <Button
              render={<Link href="/portal/appointments" />}
              nativeButton={false}
              variant="outline"
              size="sm"
              className="mt-4 w-full"
            >
              Manage appointment
              <ArrowRight className="size-3.5" />
            </Button>
          </>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              You don&apos;t have any appointments scheduled.
            </p>
            <p className="text-xs text-muted-foreground mt-2">
              Reach out to the front desk to book your next visit.
            </p>
          </>
        )}
      </div>
    </article>
  );
}

function RecentActivityCard({ appointment }: { appointment: PortalAppointment | null }) {
  return (
    <article className="rounded-xl border bg-card shadow-sm p-5">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="size-4 text-muted-foreground" />
        <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
          Last visit
        </h2>
      </div>
      {appointment ? (
        <>
          <p className="text-base font-medium">{appointment.service_name}</p>
          <p className="text-sm text-muted-foreground mt-0.5">
            {formatFullDate(appointment.start_time, appointment.location_timezone)}
          </p>
          {appointment.provider_name ? (
            <p className="text-xs text-muted-foreground mt-3 flex items-center gap-1.5">
              <UserCircle2 className="size-3" />
              with {appointment.provider_name}
            </p>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          No past appointments on file yet.
        </p>
      )}
    </article>
  );
}

function QuickActionsCard() {
  return (
    <article className="rounded-xl border bg-card shadow-sm p-5">
      <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-3">
        Quick actions
      </h2>
      <ul className="space-y-1">
        <li>
          <Link
            href="/portal/appointments"
            className="flex items-center justify-between gap-2 px-3 py-2 -mx-3 rounded-md text-sm hover:bg-muted transition-colors"
          >
            <span>View all appointments</span>
            <ArrowRight className="size-3.5 text-muted-foreground" />
          </Link>
        </li>
        <li>
          <Link
            href="/portal/profile"
            className="flex items-center justify-between gap-2 px-3 py-2 -mx-3 rounded-md text-sm hover:bg-muted transition-colors"
          >
            <span>Update contact info &amp; preferences</span>
            <ArrowRight className="size-3.5 text-muted-foreground" />
          </Link>
        </li>
      </ul>
    </article>
  );
}

function ContactCard({ me }: { me: NonNullable<ReturnType<typeof usePortalMe>['data']> }) {
  return (
    <article className="rounded-xl border bg-card shadow-sm p-5">
      <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-3">
        Your details
      </h2>
      <dl className="text-sm space-y-1.5">
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground">Name</dt>
          <dd className="font-medium truncate">{me.first_name} {me.last_name}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground">Email</dt>
          <dd className="truncate">{me.email}</dd>
        </div>
        {me.phone ? (
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">Phone</dt>
            <dd>{me.phone}</dd>
          </div>
        ) : null}
      </dl>
    </article>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────


function formatFullDate(iso: string, _tz: string): string {
  // We intentionally don't honour the location timezone client-side
  // yet — `toLocaleString` uses the browser's, which is the right UX
  // for the customer (they're reading the time in their own context).
  // Future polish: honour location_timezone for travelers crossing
  // zones to attend an appointment.
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
