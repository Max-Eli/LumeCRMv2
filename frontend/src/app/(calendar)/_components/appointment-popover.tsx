/**
 * Appointment popover — opens anchored to a clicked appointment block.
 *
 * Layout (top to bottom):
 *   1. Customer header — avatar, name, phone, view-profile link
 *   2. Service summary — service / code / price / provider / time
 *   3. Status transitions — only valid next states are rendered as buttons
 *   4. Action row — Message / Take payment / Edit / Reschedule (placeholders for the
 *      not-yet-built features, with explicit phase labels in the tooltip)
 *   5. Notes — inline editor with optimistic save
 *   6. Activity — last few audit entries (created / status transitions / edits)
 *
 * The popover handles its own data — it pulls activity lazily when opened, drives
 * status transitions through `useUpdateAppointment`, and saves notes inline.
 */

'use client';

import {
  Activity,
  CalendarClock,
  Check,
  CreditCard,
  ExternalLink,
  Loader2,
  Lock,
  Plus,
  Search,
  Undo2,
  X,
} from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { InitialsAvatar } from '@/components/initials-avatar';
import { StatusBadge } from '@/components/status-badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet';
import { ApiError } from '@/lib/api';
import {
  STATUS_LABELS,
  STATUS_TONE,
  STATUS_TRANSITIONS,
  STATUS_TRANSITION_VERBS,
  type Appointment,
  type AppointmentStatus,
  useAddAppointmentService,
  useChangeAppointmentService,
  useRemoveAppointmentExtraService,
  useUpdateAppointment,
} from '@/lib/appointments';
import { useServices } from '@/lib/services';
import { useEmailSubmission, useFormSubmissions } from '@/lib/form-submissions';
import { openTreatmentRecordWindow, useAppointmentTreatmentRecords } from '@/lib/treatments';
import {
  INVOICE_STATUS_LABELS,
  formatMoneyCents,
  openInvoiceWindow,
  useInvoiceForAppointment,
} from '@/lib/invoices';
import { cn } from '@/lib/utils';

export interface AppointmentPopoverProps {
  appointment: Appointment;
  timezone: string;
  /** The trigger element — usually the appointment block on the calendar or
   *  a row in the list view. Passed via the popover trigger's `render` prop. */
  trigger: React.ReactElement;
}

export function AppointmentPopover({ appointment, timezone, trigger }: AppointmentPopoverProps) {
  const [open, setOpen] = useState(false);
  const isMobile = useIsMobileViewport();

  // On phones, anchored popovers next to a tiny appointment block render
  // off-screen or in a cramped corner. Bottom-sheet is the native mobile
  // pattern for action-rich detail surfaces — full-width, full-content,
  // dismissable by swipe-down or tap-outside.
  if (isMobile) {
    return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger render={trigger} />
        <SheetContent side="bottom" className="max-h-[85vh] overflow-y-auto p-0">
          <PopoverBody
            appointment={appointment}
            timezone={timezone}
            onClose={() => setOpen(false)}
          />
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={trigger} />
      <PopoverContent
        side="right"
        align="start"
        sideOffset={8}
        className="w-[380px] p-0 max-h-[80vh] overflow-y-auto"
      >
        <PopoverBody
          appointment={appointment}
          timezone={timezone}
          onClose={() => setOpen(false)}
        />
      </PopoverContent>
    </Popover>
  );
}

/** Live-tracks the `(max-width: 639px)` breakpoint (Tailwind sm boundary).
 *  Starts as `false` to match SSR-assumes-desktop; flips on mount via
 *  matchMedia. Used to switch the appointment surface between Popover
 *  (desktop) and bottom Sheet (phone). */
function useIsMobileViewport(): boolean {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mql = window.matchMedia('(max-width: 639px)');
    const update = () => setIsMobile(mql.matches);
    update();
    mql.addEventListener('change', update);
    return () => mql.removeEventListener('change', update);
  }, []);
  return isMobile;
}

// ── Body ─────────────────────────────────────────────────────────────────

function PopoverBody({
  appointment,
  timezone,
  onClose,
}: {
  appointment: Appointment;
  timezone: string;
  onClose: () => void;
}) {
  const update = useUpdateAppointment(appointment.id);
  const transitions = STATUS_TRANSITIONS[appointment.status];

  const handleTransition = (
    next: AppointmentStatus,
    cancelledReason?: string,
  ) => {
    const verb = STATUS_TRANSITION_VERBS[`${appointment.status}->${next}`];
    update.mutate(
      {
        status: next,
        ...(cancelledReason ? { cancelled_reason: cancelledReason } : {}),
      },
      {
        onSuccess: () => {
          toast.success(verb ?? `Marked ${STATUS_LABELS[next].toLowerCase()}`);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
            const body = err.body as { status?: string[] | string };
            const detail = Array.isArray(body.status) ? body.status[0] : body.status;
            toast.error(detail ?? 'Could not change status. Please try again.');
          } else {
            toast.error('Could not change status. Please try again.');
          }
        },
      },
    );
  };

  return (
    <>
      <CustomerHeader appointment={appointment} onClose={onClose} />
      <Divider />
      <ServiceSummary appointment={appointment} timezone={timezone} />
      <Divider />

      {transitions.length > 0 ? (
        <>
          <StatusTransitions
            current={appointment.status}
            options={transitions}
            disabled={update.isPending}
            onTransition={handleTransition}
          />
          <Divider />
        </>
      ) : null}

      <ActionGroup
        appointmentId={appointment.id}
        durationMinutes={appointment.duration_minutes}
        onClose={onClose}
      />
      <Divider />

      <FormsSection
        appointmentId={appointment.id}
        customerId={appointment.customer.id}
      />
      <Divider />

      <TreatmentRecordSection
        appointmentId={appointment.id}
        customerId={appointment.customer.id}
      />
      <Divider />

      <NotesEditor
        appointmentId={appointment.id}
        initialNotes={appointment.notes}
      />
      <Divider />

      <LogsLinkRow appointmentId={appointment.id} />
    </>
  );
}

// ── Sections ─────────────────────────────────────────────────────────────

function CustomerHeader({
  appointment,
  onClose,
}: {
  appointment: Appointment;
  onClose: () => void;
}) {
  const c = appointment.customer;
  return (
    // Burgundy banner header — `bg-accent` is Bacchic Burgundy, paired
    // with `text-accent-foreground` (Chef's Hat near-white) which is the
    // mandated foreground for any `bg-accent` surface (see ADR 0006 —
    // Smoky Black on burgundy fails contrast at 2.2:1, white on burgundy
    // hits 8.6:1 AAA). `rounded-t-lg` matches the popover's rounded
    // corners so the burgundy doesn't bleed past the curve.
    <div className="px-4 pt-3 pb-3 flex items-start gap-3 bg-accent text-accent-foreground rounded-t-lg">
      <InitialsAvatar name={c.full_name} size="lg" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="font-serif text-base font-semibold tracking-tight truncate">
            {c.full_name}
          </h3>
          <StatusBadge
            tone={STATUS_TONE[appointment.status]}
            className="text-accent-foreground/90"
          >
            {STATUS_LABELS[appointment.status]}
          </StatusBadge>
        </div>
        <p className="text-xs text-accent-foreground/75 mt-0.5 truncate">
          {[c.phone, c.full_name && c.preferred_name && `legal: ${c.first_name} ${c.last_name}`]
            .filter(Boolean)
            .join(' · ') || 'No contact info on file'}
        </p>
        <Link
          href={`/clients/${c.id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-accent-foreground/90 hover:text-accent-foreground hover:underline mt-1"
        >
          View customer profile
          <ExternalLink className="size-3" aria-hidden />
          <span className="sr-only">(opens in new tab)</span>
        </Link>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="inline-flex size-7 items-center justify-center rounded-md text-accent-foreground/80 hover:bg-accent-foreground/15 hover:text-accent-foreground transition-colors"
        aria-label="Close"
      >
        <X className="size-4" />
      </button>
    </div>
  );
}

/** Pull a human-readable message out of an API error for the service
 *  add/change/remove flows — 409 sends `{detail}`, 400 sends field
 *  errors like `{service_id: [...]}`. */
function serviceErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.body && typeof err.body === 'object') {
    const body = err.body as Record<string, unknown>;
    if (typeof body.detail === 'string') return body.detail;
    const first = Object.values(body)[0];
    if (Array.isArray(first) && typeof first[0] === 'string') return first[0];
    if (typeof first === 'string') return first;
  }
  return fallback;
}

/** One service row inside the popover's Services list. */
function ServiceLine({
  name,
  code,
  color,
  priceCents,
  durationMinutes,
  providerLabel,
  pending,
  changeLabel,
  onChange,
  onRemove,
}: {
  name: string;
  code: string;
  color: string | null;
  priceCents: number;
  durationMinutes: number;
  /** Per-service provider name — rendered only when this service has
   *  an override (different from the appointment's primary provider).
   *  Surfacing it here so staff can see "this Botox by Dr. A, this
   *  facial by Esthetician B" without leaving the popover. */
  providerLabel?: string;
  pending: boolean;
  changeLabel?: string;
  onChange?: () => void;
  onRemove?: () => void;
}) {
  const dot = color ?? 'currentColor';
  return (
    <div className="flex items-center gap-2 py-1.5">
      <span
        className="size-2 rounded-full shrink-0"
        style={{ backgroundColor: dot }}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-sm truncate" style={{ color: dot }}>
          {name}
        </p>
        {providerLabel ? (
          <p className="text-[11px] text-muted-foreground truncate">
            by {providerLabel}
          </p>
        ) : code ? (
          <p className="text-[11px] text-muted-foreground font-mono tabular-nums">
            {code}
          </p>
        ) : null}
      </div>
      <div className="text-right shrink-0">
        <p className="font-mono text-sm font-semibold tabular-nums">
          ${(priceCents / 100).toFixed(2)}
        </p>
        <p className="text-[11px] text-muted-foreground tabular-nums">
          {durationMinutes}m
        </p>
      </div>
      {onChange ? (
        <button
          type="button"
          onClick={onChange}
          disabled={pending}
          className="shrink-0 text-[11px] font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {changeLabel ?? 'Change'}
        </button>
      ) : null}
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          disabled={pending}
          aria-label={`Remove ${name}`}
          className="shrink-0 inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-destructive transition-colors disabled:opacity-50"
        >
          <X className="size-3.5" />
        </button>
      ) : null}
    </div>
  );
}

/** Compact searchable service list shown inline when adding or
 *  changing a service. Loads the active catalog lazily — only mounts
 *  once the operator opens it. */
function InlineServicePicker({
  onPick,
  onCancel,
  pending,
  excludeId,
}: {
  onPick: (serviceId: number) => void;
  onCancel: () => void;
  pending: boolean;
  excludeId?: number;
}) {
  const { data: services, isLoading } = useServices({ activeOnly: true });
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const list = (services ?? [])
    .filter((s) => s.id !== excludeId)
    .filter(
      (s) =>
        needle === ''
        || s.name.toLowerCase().includes(needle)
        || (s.code ?? '').toLowerCase().includes(needle),
    )
    .slice(0, 50);

  return (
    <div className="rounded-md border bg-muted/30 p-2 space-y-2">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
        <Input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search services…"
          className="h-8 pl-7 text-sm"
        />
      </div>
      <div className="max-h-44 overflow-y-auto">
        {isLoading ? (
          <p className="px-2 py-3 text-xs text-muted-foreground text-center">
            Loading services…
          </p>
        ) : list.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted-foreground text-center">
            No services found.
          </p>
        ) : (
          list.map((s) => (
            <button
              key={s.id}
              type="button"
              disabled={pending}
              onClick={() => onPick(s.id)}
              className="w-full flex items-center justify-between gap-3 px-2 py-1.5 rounded text-left text-sm hover:bg-muted disabled:opacity-50"
            >
              <span className="truncate">{s.name}</span>
              <span className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground tabular-nums">
                <span className="font-mono">{s.duration_minutes}m</span>
                <span className="font-mono">{s.price_dollars}</span>
              </span>
            </button>
          ))
        )}
      </div>
      <div className="flex items-center justify-end gap-2">
        {pending ? (
          <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
        ) : null}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          disabled={pending}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

function ServiceSummary({
  appointment,
  timezone,
}: {
  appointment: Appointment;
  timezone: string;
}) {
  const editable = appointment.services_editable;
  const addService = useAddAppointmentService(appointment.id);
  const changeService = useChangeAppointmentService(appointment.id);
  const removeService = useRemoveAppointmentExtraService(appointment.id);
  const [pickerMode, setPickerMode] = useState<'add' | 'change' | null>(null);

  const pending =
    addService.isPending || changeService.isPending || removeService.isPending;
  const hasExtras = appointment.extra_services.length > 0;

  const handlePick = (serviceId: number) => {
    const mode = pickerMode;
    if (mode === 'add') {
      addService.mutate(
        { service_id: serviceId },
        {
          onSuccess: () => {
            toast.success('Service added');
            setPickerMode(null);
          },
          onError: (e) =>
            toast.error(serviceErrorMessage(e, "Couldn't add this service.")),
        },
      );
    } else if (mode === 'change') {
      changeService.mutate(
        { service_id: serviceId },
        {
          onSuccess: () => {
            toast.success('Service changed');
            setPickerMode(null);
          },
          onError: (e) =>
            toast.error(
              serviceErrorMessage(e, "Couldn't change the service."),
            ),
        },
      );
    }
  };

  const handleRemove = (extraId: number) => {
    removeService.mutate(extraId, {
      onSuccess: () => toast.success('Service removed'),
      onError: (e) =>
        toast.error(serviceErrorMessage(e, "Couldn't remove this service.")),
    });
  };

  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between mb-1">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
          {hasExtras ? 'Services' : 'Appointment'}
        </p>
        {!editable ? (
          <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
            <Lock className="size-3" />
            Locked — invoice {appointment.invoice_status}
          </span>
        ) : null}
      </div>

      <ServiceLine
        name={appointment.service.name}
        code={appointment.service.code}
        color={appointment.service.category_color}
        priceCents={appointment.quoted_price_cents}
        durationMinutes={appointment.service.duration_minutes}
        pending={pending}
        onChange={
          editable
            ? () =>
                setPickerMode((m) => (m === 'change' ? null : 'change'))
            : undefined
        }
      />

      {appointment.extra_services.map((es) => {
        // Only label the per-service provider when it's an override
        // (different from the appointment's primary provider). Same-as-
        // primary stays unlabeled to avoid noise; the operator already
        // knows the primary from the main appointment row.
        const overrideProvider =
          es.provider && es.provider.id !== appointment.provider.id
            ? es.provider
            : null;
        const providerLabel = overrideProvider
          ? `${overrideProvider.user_first_name} ${overrideProvider.user_last_name}`.trim()
            || overrideProvider.user_email
          : undefined;
        return (
          <ServiceLine
            key={es.id}
            name={es.service.name}
            code={es.service.code}
            color={es.service.category_color}
            priceCents={es.price_cents}
            durationMinutes={es.duration_minutes}
            providerLabel={providerLabel}
            pending={pending}
            onRemove={editable ? () => handleRemove(es.id) : undefined}
          />
        );
      })}

      {editable && pickerMode ? (
        <div className="mt-2">
          <InlineServicePicker
            onPick={handlePick}
            onCancel={() => setPickerMode(null)}
            pending={pending}
            excludeId={
              pickerMode === 'change' ? appointment.service.id : undefined
            }
          />
        </div>
      ) : null}

      {editable && pickerMode !== 'add' ? (
        <button
          type="button"
          onClick={() => setPickerMode('add')}
          disabled={pending}
          className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline disabled:opacity-50"
        >
          <Plus className="size-3.5" />
          Add service
        </button>
      ) : null}

      {hasExtras ? (
        <div className="mt-2.5 flex items-baseline justify-between border-t pt-2">
          <span className="text-xs text-muted-foreground">Total</span>
          <span className="font-mono text-sm font-semibold tabular-nums">
            ${(appointment.total_price_cents / 100).toFixed(2)}
          </span>
        </div>
      ) : null}

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Provider</p>
          <p className="mt-0.5 truncate">
            {appointment.provider.user_first_name} {appointment.provider.user_last_name}
          </p>
          {appointment.provider.job_title_name ? (
            <p className="text-[11px] text-muted-foreground/80 truncate">
              {appointment.provider.job_title_name}
            </p>
          ) : null}
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Time</p>
          <p className="mt-0.5 font-mono tabular-nums">{formatTimeRange(appointment, timezone)}</p>
          <p className="text-[11px] text-muted-foreground/80">
            {formatLongDate(appointment.start_time, timezone)}
          </p>
        </div>
      </div>
    </div>
  );
}

/** Preset cancellation reasons. Stored verbatim in
 *  `Appointment.cancelled_reason` and surfaced in the activity feed —
 *  operators most often cancel accidental or duplicate bookings, so
 *  those lead the list. */
const CANCELLATION_REASONS = [
  'Created by mistake',
  'Duplicate appointment',
  'Client requested',
  'Client rescheduled',
  'Provider unavailable',
  'Other',
] as const;

function StatusTransitions({
  current,
  options,
  disabled,
  onTransition,
}: {
  current: AppointmentStatus;
  options: AppointmentStatus[];
  disabled: boolean;
  onTransition: (next: AppointmentStatus, cancelledReason?: string) => void;
}) {
  // When the operator picks "Cancel", swap the transition buttons for
  // a reason picker — the cancel doesn't fire until a reason is chosen.
  const [pickingCancelReason, setPickingCancelReason] = useState(false);

  if (pickingCancelReason) {
    return (
      <div className="px-4 py-3">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">
          Why are you cancelling?
        </p>
        <div className="flex flex-col gap-1.5">
          {CANCELLATION_REASONS.map((reason) => (
            <button
              key={reason}
              type="button"
              disabled={disabled}
              onClick={() => onTransition('cancelled', reason)}
              className={cn(
                'h-9 px-3 rounded-md text-xs font-medium text-left transition-colors border',
                'border-border bg-card hover:bg-muted',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              {reason}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setPickingCancelReason(false)}
          disabled={disabled}
          className="mt-2 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          ← Back
        </button>
      </div>
    );
  }

  return (
    <div className="px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">
        Update status
      </p>
      <div className="flex flex-wrap gap-1.5">
        {options.map((next) => {
          const isDestructive = next === 'cancelled' || next === 'no_show';
          // The undo-check-in transition (checked_in → confirmed) reads
          // as a *correction*, not a forward step — render it as a quiet
          // outline button rather than a positive primary, with a "rewind"
          // icon and the verb-form label.
          const isUndo = current === 'checked_in' && next === 'confirmed';
          const isPositive =
            !isUndo &&
            (next === 'checked_in' || next === 'completed' || next === 'confirmed');
          const verbLabel =
            STATUS_TRANSITION_VERBS[`${current}->${next}`] ?? STATUS_LABELS[next];
          return (
            <button
              key={next}
              type="button"
              // Cancelling routes through the reason picker; every other
              // transition fires immediately.
              onClick={() =>
                next === 'cancelled'
                  ? setPickingCancelReason(true)
                  : onTransition(next)
              }
              disabled={disabled}
              className={cn(
                'inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-xs font-medium transition-colors border',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                isPositive
                  ? 'border-transparent bg-foreground text-background hover:bg-foreground/85'
                  : isDestructive
                    ? 'border-destructive/40 text-destructive hover:bg-destructive/5'
                    : 'border-border bg-card hover:bg-muted',
              )}
            >
              {isUndo ? (
                <Undo2 className="size-3.5" />
              ) : isPositive ? (
                <Check className="size-3.5" />
              ) : null}
              {verbLabel}
            </button>
          );
        })}
      </div>
      <p className="text-[10px] text-muted-foreground/80 mt-2">
        Currently <span className="font-medium">{STATUS_LABELS[current]}</span>. State machine
        prevents invalid transitions.
      </p>
    </div>
  );
}

/**
 * Two appointment-action buttons grouped in a single section: Take
 * Payment (opens the dedicated invoice page in a new tab) and
 * Reschedule (puts the calendar into reschedule mode — see
 * `RescheduleButton`). Take Payment is the primary visual; Reschedule
 * is a quieter outline since it's the rarer action.
 */
function ActionGroup({
  appointmentId,
  durationMinutes,
  onClose,
}: {
  appointmentId: number;
  durationMinutes: number;
  onClose: () => void;
}) {
  return (
    <div className="px-4 py-3 space-y-2">
      <InvoiceCta appointmentId={appointmentId} />
      <RescheduleButton
        appointmentId={appointmentId}
        durationMinutes={durationMinutes}
        onClose={onClose}
      />
    </div>
  );
}

/**
 * Primary CTA opening the dedicated invoice page in a new tab.
 *
 * Per ADR 0007, closing the invoice (Take Payment) is the only way to
 * mark an appointment completed. Rather than render the whole invoice
 * surface inside the popover (cards, line items, forms — too much for
 * a hover panel), we render a single contextual button that opens the
 * full invoice page with `?action=pay` so the payment form is already
 * focused when the new tab loads. One click in the popover, one click
 * in the new tab to confirm the payment.
 *
 * Label adapts to invoice state:
 *
 *   - open  → "Take payment · $XX.XX" (primary button, ?action=pay)
 *   - paid  → "View invoice"          (outline)
 *   - void  → "View invoice"          (outline)
 *
 * The popover stays minimal; everything Reopen / Void related lives
 * exclusively on the new page.
 */
function InvoiceCta({ appointmentId }: { appointmentId: number }) {
  const { data: invoice, isLoading } = useInvoiceForAppointment(appointmentId);

  if (isLoading || !invoice) {
    // Render a compact placeholder so the popover height doesn't jump
    // when the invoice query resolves.
    return <div className="h-9" aria-hidden />;
  }

  const isOpen = invoice.status === 'open';
  const label = isOpen
    ? `Take payment · ${formatMoneyCents(invoice.total_cents)}`
    : `View invoice · ${INVOICE_STATUS_LABELS[invoice.status]}`;

  return (
    <button
      type="button"
      onClick={() => openInvoiceWindow(appointmentId, isOpen ? 'pay' : undefined)}
      className={cn(
        buttonVariants({ variant: isOpen ? 'default' : 'outline', size: 'lg' }),
        'w-full justify-start',
      )}
    >
      <CreditCard className="size-4" />
      <span className="truncate">{label}</span>
      <ExternalLink className="size-3.5 ml-auto opacity-70" aria-hidden />
      <span className="sr-only">(opens in a new window)</span>
    </button>
  );
}

/**
 * Reschedule button — closes the popover and puts the calendar page
 * into "rescheduling mode" by setting `?rescheduling=<appointment_id>`
 * in the URL. The calendar page reads this param to render a banner;
 * DayView reads it to fade the source appointment block and enable
 * right-click drop targets ("reschedule here / cancel"). The duration
 * comes along in `?duration=<minutes>` so the day view can compute the
 * snapped end-time without an extra fetch.
 *
 * URL state (rather than React state) is intentional: the rescheduling
 * intent must persist when the user navigates the calendar to a
 * different day to find a slot.
 */
function RescheduleButton({
  appointmentId,
  durationMinutes,
  onClose,
}: {
  appointmentId: number;
  durationMinutes: number;
  onClose: () => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const handleClick = () => {
    const next = new URLSearchParams(searchParams.toString());
    next.set('rescheduling', String(appointmentId));
    next.set('duration', String(durationMinutes));
    router.replace(`/calendar?${next.toString()}`, { scroll: false });
    onClose();
  };

  return (
    <Button
      type="button"
      variant="outline"
      size="lg"
      className="w-full justify-start"
      onClick={handleClick}
    >
      <CalendarClock className="size-4" />
      <span className="truncate">Reschedule appointment</span>
    </Button>
  );
}

/**
 * Small inline link to the dedicated activity-log page. Opens in a new
 * tab so the calendar stays put. The full audit trail (status changes,
 * edits, payment events, reads) lives there; the popover stays focused
 * on "what's happening with this appointment right now."
 */
function LogsLinkRow({ appointmentId }: { appointmentId: number }) {
  // Opens a dedicated popup WINDOW (not a tab) so the operator can
  // park the audit trail beside the calendar without juggling tabs.
  // Mirrors the popout pattern used by the messaging inbox in
  // right-tool-rail.tsx — same window features, same UX shape.
  const openLogsWindow = () => {
    window.open(
      `/appointments/${appointmentId}/logs`,
      `appointment-logs-${appointmentId}`,
      'popup,width=900,height=720,noopener=no,noreferrer=no',
    );
  };
  return (
    <div className="px-4 py-2.5">
      <button
        type="button"
        onClick={openLogsWindow}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Activity className="size-3.5" />
        Logs
        <ExternalLink className="size-3 shrink-0" aria-hidden />
        <span className="sr-only">(opens in a new window)</span>
      </button>
    </div>
  );
}

/**
 * Forms section — always rendered for an appointment so the operator
 * never has to wonder "is the section missing or are there just no
 * forms?" Pending forms get a prominent amber row with an "Open for
 * signing" action that opens the public `/sign/[token]` URL in a new
 * tab — the same URL works whether opened on a phone (client) or an
 * iPad (front desk handing it across the counter). Completed forms
 * show a green "Signed" tag + the email-a-copy button.
 *
 * With nothing to surface we show an explicit empty state. That's
 * how a professional CRM treats a section the operator might look
 * to during checkout: it makes the absence of forms a confirmed
 * negative ("nothing required for this visit"), not an ambiguous
 * silence.
 */
function FormsSection({
  appointmentId,
  customerId,
}: {
  appointmentId: number;
  customerId: number;
}) {
  // We query by customer (not appointment) because intake forms
  // aren't tied to a specific appointment but are still relevant to
  // surface in this popover (the operator wants to see "this
  // customer has 1 unsigned intake" alongside the appointment-
  // specific consents).
  const { data: subs, isLoading } = useFormSubmissions({ customerId });

  return (
    <div className="px-4 py-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
          Forms
        </p>
        {(() => {
          if (isLoading) return null;
          const pendingCount = (subs ?? []).filter(
            (s) =>
              (s.template_form_type === 'intake'
                || s.appointment_id === appointmentId)
              && s.status === 'pending',
          ).length;
          return pendingCount > 0 ? (
            <span className="text-[11px] font-medium text-amber-600 dark:text-amber-500">
              {pendingCount} pending
            </span>
          ) : null;
        })()}
      </div>

      <FormsSectionBody
        appointmentId={appointmentId}
        subs={subs}
        isLoading={isLoading}
      />
    </div>
  );
}

function FormsSectionBody({
  appointmentId,
  subs,
  isLoading,
}: {
  appointmentId: number;
  subs: ReturnType<typeof useFormSubmissions>['data'];
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <p className="text-[11px] text-muted-foreground">Loading…</p>
    );
  }
  // Filter to forms that matter for THIS appointment context: any
  // intake (per-customer) + any consent appointment-pinned to this one.
  const relevant = (subs ?? []).filter(
    (s) =>
      s.template_form_type === 'intake' || s.appointment_id === appointmentId,
  );
  const pending = relevant.filter((s) => s.status === 'pending');
  const completed = relevant.filter((s) => s.status === 'completed');

  if (relevant.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground leading-relaxed">
        No forms required for this visit. Consent forms auto-attach
        when the service is mapped to one in Settings → Forms.
      </p>
    );
  }

  return (
    <ul className="space-y-1">
      {pending.map((sub) => (
        <li
          key={sub.id}
          className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-50/40 dark:bg-amber-950/10 px-2.5 py-1.5"
        >
          <span className="text-xs flex-1 truncate">{sub.template_name}</span>
          <a
            href={`/sign/${sub.token}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700 dark:text-amber-500 hover:underline"
          >
            Open for signing
          </a>
        </li>
      ))}
      {completed.map((sub) => (
        <li
          key={sub.id}
          className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-muted-foreground"
        >
          <span className="text-xs flex-1 truncate">{sub.template_name}</span>
          <span className="text-[11px] text-emerald-700 dark:text-emerald-500">
            Signed
          </span>
          <PopoverEmailButton submissionId={sub.id} />
        </li>
      ))}
    </ul>
  );
}

/**
 * Compact "email this signed copy to the client" button for the
 * popover's Forms section. Two-click confirm pattern same as the
 * customer profile version — click once to enter confirm state,
 * click again to fire. Backend is owner+manager gated and audit-
 * logged with recipient domain only (ADR 0012).
 */
function PopoverEmailButton({ submissionId }: { submissionId: number }) {
  const send = useEmailSubmission(submissionId);
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <span className="inline-flex items-center gap-1">
        <button
          type="button"
          onClick={() => setConfirming(false)}
          disabled={send.isPending}
          className="text-[11px] text-muted-foreground hover:text-foreground transition-colors px-1"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => {
            send.mutate(undefined, {
              onSuccess: (resp) => {
                toast.success(`Sent to ${resp.recipient}`);
                setConfirming(false);
              },
              onError: (err) => {
                if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
                  const body = err.body as { detail?: string };
                  toast.error(body.detail ?? 'Could not send.');
                } else if (err instanceof ApiError && err.status === 403) {
                  toast.error("You don't have permission to email signed forms.");
                } else {
                  toast.error('Could not send. Please try again.');
                }
                setConfirming(false);
              },
            });
          }}
          disabled={send.isPending}
          className="text-[11px] font-medium text-foreground hover:text-foreground/80 transition-colors px-1"
        >
          {send.isPending ? 'Sending…' : 'Confirm'}
        </button>
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      title="Email a signed copy to the client (only if they asked for one)"
      className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
    >
      Email
    </button>
  );
}

/**
 * Treatment record section — the provider-side EMR chart for this
 * appointment. Distinct from the patient-facing intake / consent
 * forms (those live in <FormsSection> above) — this is the clinical
 * documentation of what was actually performed.
 *
 * One record per appointment is the common case. Addenda (corrections
 * + late additions) are handled in the customer-profile EMR tab,
 * which is where the section deep-links. The popover stays focused
 * on "is there one or not, click to sign / view."
 */
function TreatmentRecordSection({
  appointmentId,
  customerId: _customerId,
}: {
  appointmentId: number;
  customerId: number;
}) {
  const { data: records, isLoading } = useAppointmentTreatmentRecords(appointmentId);
  if (isLoading) return null;

  const list = records ?? [];
  const signed = list.find((r) => r.parent_record_id === null);

  const openWindow = () => openTreatmentRecordWindow(appointmentId);

  return (
    <div className="px-4 py-3 space-y-2">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
        Treatment record
      </p>
      {signed ? (
        <button
          type="button"
          onClick={openWindow}
          className="w-full flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-50/40 dark:bg-emerald-950/10 px-2.5 py-2 hover:bg-emerald-50/60 dark:hover:bg-emerald-950/20 transition-colors text-left"
        >
          <Activity className="size-3.5 text-emerald-700 dark:text-emerald-500 shrink-0" />
          <span className="text-xs flex-1 truncate">
            {signed.template_name || 'Treatment record'}
          </span>
          <span className="text-[11px] text-emerald-700 dark:text-emerald-500 shrink-0">
            Signed
          </span>
          <ExternalLink className="size-3 text-muted-foreground/70 shrink-0" aria-hidden />
        </button>
      ) : (
        <button
          type="button"
          onClick={openWindow}
          className="w-full flex items-center gap-2 rounded-md border border-dashed border-foreground/15 bg-card hover:border-foreground/30 hover:bg-muted/40 px-2.5 py-2 transition-colors text-left"
        >
          <Activity className="size-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs flex-1 text-foreground/90">
            Sign treatment record
          </span>
          <ExternalLink className="size-3 text-muted-foreground/70 shrink-0" aria-hidden />
        </button>
      )}
    </div>
  );
}

function NotesEditor({
  appointmentId,
  initialNotes,
}: {
  appointmentId: number;
  initialNotes: string;
}) {
  const update = useUpdateAppointment(appointmentId);
  const [value, setValue] = useState(initialNotes);
  const [savedValue, setSavedValue] = useState(initialNotes);

  // Reset if the appointment behind the popover changes.
  useEffect(() => {
    setValue(initialNotes);
    setSavedValue(initialNotes);
  }, [initialNotes, appointmentId]);

  const dirty = value !== savedValue;

  const onSave = () => {
    update.mutate(
      { notes: value },
      {
        onSuccess: () => {
          setSavedValue(value);
          toast.success('Notes saved');
        },
        onError: () => toast.error('Could not save notes'),
      },
    );
  };

  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Notes</p>
        {dirty ? (
          <span className="text-[10px] text-muted-foreground italic">Unsaved</span>
        ) : null}
      </div>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={3}
        placeholder="Internal notes — visible to staff only."
        className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 placeholder:text-muted-foreground/70 resize-y"
      />
      <div className="flex justify-end gap-2 mt-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!dirty || update.isPending}
          onClick={() => setValue(savedValue)}
        >
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={!dirty || update.isPending}
          onClick={onSave}
        >
          {update.isPending ? 'Saving…' : 'Save notes'}
        </Button>
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

function Divider() {
  return <div className="border-t border-border/60" aria-hidden />;
}

function formatTimeRange(appt: Appointment, timezone: string): string {
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: timezone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  };
  const start = new Date(appt.start_time).toLocaleTimeString('en-US', opts);
  const end = new Date(appt.end_time).toLocaleTimeString('en-US', opts);
  return `${start} – ${end}`;
}

function formatLongDate(iso: string, timezone: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    timeZone: timezone,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}
