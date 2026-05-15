/**
 * Calendar right-rail Social DM panel.
 *
 * Once Meta App Review approves our `pages_messaging`,
 * `instagram_business_*`, and `whatsapp_business_*` scopes, this
 * panel will become a real unified inbox for IG / Facebook / WhatsApp
 * DMs (same Message model + thread UX as the SMS inbox). Until then,
 * the `connect/begin/` endpoint returns 501 `oauth_not_ready` and
 * staff can't actually pair their Meta accounts.
 *
 * This panel surfaces that state honestly — shows the providers, the
 * current status pill, what connecting will unlock, and routes the
 * connect action to `/org/integrations` where the full settings UI
 * already lives. No staff workflow inside the calendar depends on
 * social being live yet; this is an awareness surface + a path
 * forward when Meta approval lands.
 */

'use client';

import {
  ArrowUpRight,
  AtSign,
  CheckCircle2,
  Loader2,
} from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import {
  PROVIDER_GLYPH,
  STATUS_LABELS,
  STATUS_TONE,
  useIntegrations,
  type IntegrationProviderEntry,
} from '@/lib/integrations';
import { cn } from '@/lib/utils';

export function SocialPanel() {
  const { data: providers, isLoading } = useIntegrations();
  const connectedCount = (providers ?? []).filter((p) => p.status === 'connected').length;
  const totalCount = providers?.length ?? 0;

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-3 pb-2 border-b">
        <p className="text-xs text-muted-foreground">
          {isLoading ? (
            'Loading…'
          ) : connectedCount > 0 ? (
            <>
              <span className="font-medium text-foreground">{connectedCount}</span>
              {' of '}
              {totalCount} channels connected
            </>
          ) : (
            <>
              Connect your spa&apos;s social accounts so DMs land in the inbox alongside SMS.
            </>
          )}
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : (providers?.length ?? 0) === 0 ? (
          <div className="px-4 py-8 text-center">
            <AtSign className="size-6 mx-auto mb-2 text-muted-foreground" />
            <p className="text-xs text-muted-foreground">
              No social channels configured yet.
            </p>
          </div>
        ) : (
          <ul className="divide-y">
            {providers!.map((p) => (
              <ProviderRow key={p.key} provider={p} />
            ))}
          </ul>
        )}
      </div>

      <div className="border-t px-3 py-2.5">
        <Button
          render={<Link href="/org/integrations" target="_blank" />}
          nativeButton={false}
          variant="outline"
          size="sm"
          className="w-full"
        >
          Manage integrations
          <ArrowUpRight className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

function ProviderRow({ provider }: { provider: IntegrationProviderEntry }) {
  const isConnected = provider.status === 'connected';
  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-3">
        <span
          className="size-8 rounded-md inline-flex items-center justify-center bg-muted text-foreground/80 font-semibold text-sm shrink-0"
          aria-hidden
        >
          {PROVIDER_GLYPH[provider.key]}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{provider.display_name}</p>
          <p className="text-[11px] text-muted-foreground truncate">
            {isConnected && provider.external_name
              ? provider.external_name
              : provider.short_description}
          </p>
        </div>
        <span
          className={cn(
            'shrink-0 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded-full ring-1 ring-inset',
            STATUS_TONE[provider.status],
          )}
        >
          {isConnected ? <CheckCircle2 className="size-2.5" /> : null}
          {STATUS_LABELS[provider.status]}
        </span>
      </div>
      {!provider.oauth_ready ? (
        <p className="text-[11px] text-muted-foreground/80 mt-1.5 pl-11">
          Awaiting Meta App approval — the spa-owner can register interest from settings.
        </p>
      ) : null}
    </li>
  );
}
