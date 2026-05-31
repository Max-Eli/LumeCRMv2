'use client';

/**
 * Global escalation notifier for the AI SMS inbox.
 *
 * Mounted once per authenticated app session in `(app)/layout.tsx`.
 * Polls `/api/ai-inbox/escalations/?status=open` every 30s
 * (handled by the underlying `useEscalationAlerts` query). Two
 * surfaces:
 *
 *   1. **Sonner toast** when a NEW escalation appears. Compares the
 *      latest poll's IDs against the prior set; any unseen ID fires
 *      a toast with the customer name, escalation reason, and a
 *      deep-link to the conversation in the inbox.
 *   2. **Persistent bell badge** in the fixed top-right of the
 *      viewport whenever there's ≥1 open escalation. Click opens a
 *      popover listing every open alert with quick acknowledge /
 *      resolve actions.
 *
 * Renders nothing visible when there are 0 open escalations — the
 * tenant operator's calendar stays uncluttered.
 *
 * Hidden cleanly for tenants without F_AI_INBOX (the underlying
 * useEscalationAlerts call 402's, the query reports error, we
 * render nothing). Same pattern as the AIStatusBanner in the inbox.
 */
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Loader2,
  MessageSquareWarning,
  X,
} from 'lucide-react';
import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

import {
  type EscalationAlert,
  useAcknowledgeAlert,
  useEscalationAlerts,
  useResolveAlert,
} from '@/lib/ai-inbox';
import { cn } from '@/lib/utils';

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

// Human-readable label for the escalation reason enum (matches the
// backend EscalationAlert.Reason choices). Kept here as a tight
// table so the toast + popover render identical text.
const REASON_LABELS: Record<string, string> = {
  requested_human: 'Customer asked to talk to a person',
  clinical_question: 'Clinical question — needs a provider',
  payment_dispute: 'Payment or refund issue',
  complaint: 'Complaint',
  agent_loop_limit: 'AI agent hit its tool-call limit',
  daily_cap_exceeded: "Tenant's daily AI cap was hit",
  safety_outbound_blocked: 'Outbound PHI scanner blocked a message',
  unsupported_request: 'Out-of-scope request (reschedule / cancel)',
  manual_staff: 'Staff manually escalated',
  agent_error: 'AI agent crashed',
};

function labelForReason(reason: string): string {
  return REASON_LABELS[reason] || reason.replace(/_/g, ' ');
}

function formatCustomer(alert: EscalationAlert): string {
  const name = `${alert.customer_first_name} ${alert.customer_last_name}`.trim();
  return name || alert.customer_phone || `Customer #${alert.customer_id}`;
}

export function EscalationNotifier() {
  const { data: alerts, isError } = useEscalationAlerts('open');

  // Track which IDs we've already toasted. Ref (not state) so the
  // effect re-firing doesn't reset the seen-set on every poll.
  // Seeded from the first response so we don't toast pre-existing
  // alerts when the app first loads — only NEW ones.
  const seenIds = useRef<Set<number> | null>(null);

  useEffect(() => {
    if (!alerts) return;

    // First poll: seed the seen set, don't toast.
    if (seenIds.current === null) {
      seenIds.current = new Set(alerts.map((a) => a.id));
      return;
    }

    // Subsequent polls: find IDs that weren't there before.
    const previouslySeen = seenIds.current;
    const newOnes = alerts.filter((a) => !previouslySeen.has(a.id));
    for (const alert of newOnes) {
      toast.warning(`AI escalation: ${formatCustomer(alert)}`, {
        description: labelForReason(alert.reason),
        duration: 12_000, // long enough to act on but auto-dismisses
        action: {
          label: 'Open',
          onClick: () => {
            window.location.href = `/inbox?customer=${alert.customer_id}`;
          },
        },
      });
    }

    // Update the seen set to the current list (dropping resolved ones
    // is fine — if they re-open, we re-toast).
    seenIds.current = new Set(alerts.map((a) => a.id));
  }, [alerts]);

  // 402 (PlanFeatureRequired) or any other error → hide entirely. We
  // don't want a broken badge sitting in the corner for tenants
  // without F_AI_INBOX.
  if (isError) return null;
  if (!alerts || alerts.length === 0) return null;

  return (
    <Popover>
      <PopoverTrigger
        aria-label={`${alerts.length} AI escalation${alerts.length === 1 ? '' : 's'} need attention`}
        className={cn(
          'fixed top-4 right-4 z-50',
          'flex items-center gap-2 rounded-full',
          'bg-rose-600 text-white shadow-lg shadow-rose-900/20',
          'px-3.5 py-2 text-sm font-medium',
          'hover:bg-rose-700 transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300 focus-visible:ring-offset-2',
        )}
      >
        <Bell className="size-4 shrink-0" aria-hidden />
        <span>{alerts.length}</span>
        <span className="sr-only">AI escalation needs attention</span>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-[380px] p-0 max-h-[480px] overflow-y-auto"
      >
        <header className="px-4 py-3 border-b sticky top-0 bg-card z-10">
          <div className="flex items-center gap-2">
            <MessageSquareWarning className="size-4 text-rose-600" aria-hidden />
            <h3 className="text-sm font-semibold">AI escalations</h3>
            <span className="ml-auto text-xs text-muted-foreground">
              {alerts.length} open
            </span>
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            The AI agent stopped these threads — a teammate needs to handle them.
          </p>
        </header>
        <ul className="divide-y">
          {alerts.map((alert) => (
            <EscalationRow key={alert.id} alert={alert} />
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function EscalationRow({ alert }: { alert: EscalationAlert }) {
  const acknowledge = useAcknowledgeAlert();
  const resolve = useResolveAlert();
  const customer = formatCustomer(alert);
  const reason = labelForReason(alert.reason);
  const detail = alert.reason_detail?.trim();
  const isAcknowledged = alert.acknowledged_at !== null;

  const openInbox = () => {
    window.location.href = `/inbox?customer=${alert.customer_id}`;
  };

  return (
    <li className="px-4 py-3">
      <div className="flex items-start gap-2">
        <AlertTriangle
          className="size-3.5 mt-0.5 shrink-0 text-rose-600"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-tight">{customer}</p>
          <p className="text-xs text-muted-foreground mt-0.5">{reason}</p>
          {detail ? (
            <p className="text-[11px] text-muted-foreground/80 mt-1 line-clamp-2">
              {detail}
            </p>
          ) : null}
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={openInbox}
              className="text-[11px] font-medium text-rose-700 hover:text-rose-800 underline-offset-2 hover:underline"
            >
              Open conversation
            </button>
            {!isAcknowledged ? (
              <button
                type="button"
                onClick={() => acknowledge.mutate(alert.id)}
                disabled={acknowledge.isPending}
                className="text-[11px] text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
              >
                {acknowledge.isPending ? (
                  <Loader2 className="size-3 animate-spin inline" />
                ) : (
                  'Acknowledge'
                )}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => resolve.mutate(alert.id)}
              disabled={resolve.isPending}
              className="ml-auto inline-flex items-center gap-1 text-[11px] text-emerald-700 hover:text-emerald-800 disabled:opacity-50"
            >
              {resolve.isPending ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <CheckCircle2 className="size-3" />
              )}
              Resolve
            </button>
          </div>
        </div>
        <X className="size-3 text-transparent" aria-hidden />
        {/* placeholder for future per-row dismiss if needed; keeps row height consistent */}
      </div>
    </li>
  );
}
