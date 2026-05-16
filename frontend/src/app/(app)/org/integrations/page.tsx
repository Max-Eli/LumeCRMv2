/**
 * `/org/integrations` — connect external messaging channels.
 *
 * v1 surface: three cards (Facebook Page Messenger, Instagram
 * Business DMs, WhatsApp Business). Each card shows the provider's
 * status pill, a one-line description, the bullet list of what
 * connecting enables, and a Connect / Disconnect button.
 *
 * In v1 the OAuth flow itself is gated behind Meta App approval —
 * Connect button posts to /api/integrations/<provider>/connect/begin/
 * which returns 501 with `code='oauth_not_ready'`. The page surfaces
 * the backend's friendly message ("we'll email you when it goes
 * live") rather than treating it as an error.
 *
 * Disconnect is fully wired today — useful when Session 2 lands and
 * an operator needs to reconnect, but also works on rows that were
 * manually inserted (e.g. for testing).
 */

'use client';

import { CheckCircle2, Plug, XCircle } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type IntegrationProviderEntry,
  type IntegrationStatus,
  PROVIDER_GLYPH,
  STATUS_LABELS,
  STATUS_TONE,
  useConnectIntegration,
  useDisconnectIntegration,
  useIntegrations,
} from '@/lib/integrations';
import { cn } from '@/lib/utils';

export default function OrgIntegrationsPage() {
  const me = useCurrentMembership();
  const { data: providers, isLoading, error } = useIntegrations();
  const canManage = me?.role === 'owner' || me?.role === 'manager';

  return (
    <div className="px-10 py-10 max-w-7xl space-y-8">
      <PageHeader
        title="Integrations"
        description="Connect Facebook, Instagram, and WhatsApp so customer messages land in Lumè's inbox — and book appointments directly from a conversation."
      />

      <ContextNote />

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Failed to load integrations.
        </div>
      ) : isLoading ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          {(providers ?? []).map((p) => (
            <ProviderCard key={p.key} provider={p} canManage={canManage} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Provider card ─────────────────────────────────────────────────────

function ProviderCard({
  provider,
  canManage,
}: {
  provider: IntegrationProviderEntry;
  canManage: boolean;
}) {
  const connect = useConnectIntegration();
  const disconnect = useDisconnectIntegration();
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  const isConnected = provider.status === 'connected';

  const handleConnect = () => {
    connect.mutate(
      { provider: provider.key },
      {
        onSuccess: (data) => {
          // Backend returns `authorize_url` for Meta; future providers
          // may return `url`. Either triggers a full-page redirect to
          // the provider's consent screen. If neither is set the
          // backend gave us nothing actionable — show a fallback.
          const target = data.authorize_url ?? data.url;
          if (target) {
            window.location.href = target;
          } else {
            toast.message(
              "Connection started, but the backend didn't return a "
              + 'redirect URL. Check the integrations log.',
            );
          }
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 501) {
            const body = err.body as { detail?: string; code?: string } | null;
            toast.message(provider.display_name, {
              description: body?.detail ?? 'Connection flow not yet available.',
            });
          } else {
            toast.error('Could not start connection. Please try again.');
          }
        },
      },
    );
  };

  const handleDisconnect = () => {
    if (!provider.connection_id) return;
    disconnect.mutate(
      { connectionId: provider.connection_id },
      {
        onSuccess: () => {
          toast.success(`${provider.display_name} disconnected.`);
          setConfirmDisconnect(false);
        },
        onError: () => toast.error('Disconnect failed. Please try again.'),
      },
    );
  };

  return (
    <article className="rounded-lg border bg-card overflow-hidden flex flex-col">
      <header className="flex items-start gap-3 border-b px-5 py-4">
        <span
          className="inline-flex size-10 items-center justify-center rounded-md border bg-foreground/[0.04] font-serif text-lg font-medium text-foreground/80"
          aria-hidden
        >
          {PROVIDER_GLYPH[provider.key]}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-serif text-base font-semibold tracking-tight truncate">
            {provider.display_name}
          </h2>
          <StatusPill status={provider.status} className="mt-1.5" />
        </div>
      </header>

      <div className="flex-1 px-5 py-4 space-y-4">
        <p className="text-sm leading-relaxed text-foreground/80">
          {provider.short_description}
        </p>

        <ul className="space-y-1.5 text-xs text-muted-foreground">
          {provider.enables.map((line) => (
            <li key={line} className="flex items-start gap-2">
              <span aria-hidden className="mt-1.5 inline-block size-1 shrink-0 rounded-full bg-accent" />
              {line}
            </li>
          ))}
        </ul>

        {isConnected && provider.external_name ? (
          <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
            <p className="text-muted-foreground">Connected account</p>
            <p className="mt-0.5 font-medium text-foreground truncate">
              {provider.external_name}
            </p>
            {provider.last_synced_at ? (
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Last sync: {formatTimestamp(provider.last_synced_at)}
              </p>
            ) : null}
          </div>
        ) : null}

        {provider.status === 'error' && provider.last_error_message ? (
          <div className="rounded-md border border-rose-300/50 bg-rose-50 px-3 py-2 text-xs text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100">
            <p className="font-medium">Connection error</p>
            <p className="mt-0.5">{provider.last_error_message}</p>
          </div>
        ) : null}
      </div>

      <footer className="border-t px-5 py-3 flex items-center justify-between gap-2">
        {!provider.oauth_ready && !isConnected ? (
          <p className="text-[11px] text-muted-foreground italic">
            Awaiting Meta App approval
          </p>
        ) : (
          <span aria-hidden />
        )}

        {isConnected ? (
          confirmDisconnect ? (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirmDisconnect(false)}
                disabled={disconnect.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleDisconnect}
                disabled={disconnect.isPending}
                className="border-rose-300 text-rose-900 hover:bg-rose-50 dark:border-rose-900 dark:text-rose-100 dark:hover:bg-rose-950"
              >
                <XCircle className="size-3.5" />
                {disconnect.isPending ? 'Disconnecting…' : 'Confirm'}
              </Button>
            </div>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmDisconnect(true)}
              disabled={!canManage}
            >
              Disconnect
            </Button>
          )
        ) : (
          <Button
            size="sm"
            onClick={handleConnect}
            disabled={!canManage || connect.isPending}
          >
            <Plug className="size-3.5" />
            {connect.isPending ? 'Starting…' : 'Connect'}
          </Button>
        )}
      </footer>
    </article>
  );
}

function StatusPill({
  status,
  className,
}: {
  status: IntegrationStatus;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center h-5 px-2 rounded text-[10px] uppercase tracking-wide font-medium ring-1',
        STATUS_TONE[status],
        className,
      )}
    >
      {status === 'connected' ? <CheckCircle2 className="size-3 mr-1" /> : null}
      {STATUS_LABELS[status]}
    </span>
  );
}

// ── Context strip ─────────────────────────────────────────────────────

function ContextNote() {
  return (
    <div className="rounded-lg border bg-muted/30 px-5 py-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground/85 font-medium">
        How this works
      </p>
      <p className="mt-2 text-sm leading-relaxed text-foreground/80">
        Once connected, customer messages from your linked Meta accounts land
        in <Link href="/messages" className="font-medium text-accent hover:underline underline-offset-2">Lumè's unified inbox</Link>.
        Reply directly from Lumè and the message is delivered back to the
        customer on the original platform. You can also book appointments
        from inside a conversation — the client record auto-links by name +
        phone where possible.
      </p>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="rounded-lg border bg-card overflow-hidden flex flex-col">
      <div className="border-b px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="size-10 rounded-md bg-muted animate-pulse" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-32 rounded bg-muted animate-pulse" />
            <div className="h-3 w-20 rounded bg-muted animate-pulse" />
          </div>
        </div>
      </div>
      <div className="flex-1 px-5 py-4 space-y-3">
        <div className="h-3 w-full rounded bg-muted animate-pulse" />
        <div className="h-3 w-2/3 rounded bg-muted animate-pulse" />
        <div className="space-y-1.5 pt-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-2.5 w-3/4 rounded bg-muted animate-pulse" />
          ))}
        </div>
      </div>
      <div className="border-t px-5 py-3 flex justify-end">
        <div className="h-8 w-20 rounded-md bg-muted animate-pulse" />
      </div>
    </div>
  );
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const now = Date.now();
  const diffSec = Math.floor((now - d.getTime()) / 1000);
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
