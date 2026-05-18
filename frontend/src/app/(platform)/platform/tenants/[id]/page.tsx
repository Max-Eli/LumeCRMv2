/**
 * `/platform/tenants/[slug]` — tenant detail.
 *
 * Layout:
 *   - Back link
 *   - Header strip: tenant name + status pill + subdomain link
 *     + quick-action toolbar (Visit CRM, View audit log, Suspend /
 *     Reactivate). Mobile: stacks vertically.
 *   - Quick metrics row: signup date, member count, location count
 *   - Sections (in order):
 *       * Identity (editable name + brand color + logo URL)
 *       * Members (every membership row)
 *       * Lifecycle (suspend / reactivate)
 *
 * Phase 2 will add Impersonate ("view as owner") and cost
 * breakdown — both need backend work that doesn't exist yet.
 *
 * Param convention: Next 16's dynamic segment is `[id]` here but
 * the value is the slug — Next doesn't care, the segment name is
 * just a key. Slug-based URLs read cleaner ("acmespa" beats a PK).
 */

'use client';

import {
  AlertTriangle,
  ArrowLeft,
  Building2,
  ExternalLink,
  Power,
  ScrollText,
  Users,
} from 'lucide-react';
import Link from 'next/link';
import { use, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  STATUS_LABELS,
  STATUS_TONE,
  type PlatformTenantMember,
  type PlatformTenantStatus,
  useReactivatePlatformTenant,
  useSuspendPlatformTenant,
  useUpdatePlatformTenant,
  usePlatformTenant,
} from '@/lib/platform';
import { cn } from '@/lib/utils';

const ROOT_DOMAIN =
  process.env.NEXT_PUBLIC_ROOT_DOMAIN || 'xn--lumcrm-5ua.com';

export default function PlatformTenantDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: slug } = use(params);
  const { data: tenant, isLoading, error } = usePlatformTenant(slug);

  if (isLoading) {
    return (
      <div className="px-4 sm:px-8 lg:px-10 py-6 sm:py-10">
        <BackLink />
        <div className="mt-6 text-sm text-muted-foreground">Loading tenant…</div>
      </div>
    );
  }
  if (error || !tenant) {
    return (
      <div className="px-4 sm:px-8 lg:px-10 py-6 sm:py-10">
        <BackLink />
        <h1 className="mt-6 font-serif text-2xl sm:text-3xl font-semibold tracking-tight">
          Tenant not found
        </h1>
        <p className="mt-2 text-sm text-destructive">
          Failed to load this tenant. They may have been cancelled or the
          slug is wrong.
        </p>
      </div>
    );
  }

  const subdomain = `${tenant.slug}.${ROOT_DOMAIN}`;
  const activeMembers = tenant.members.filter((m) => m.is_active).length;

  return (
    <div className="px-4 sm:px-8 lg:px-10 py-6 sm:py-10">
      <BackLink />

      {/* ─── Tenant header strip ──────────────────────────────────── */}
      <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            Platform Admin · Tenant detail
          </p>
          <div className="mt-2 flex items-baseline flex-wrap gap-3">
            <h1 className="font-serif text-2xl sm:text-3xl font-semibold tracking-tight text-foreground">
              {tenant.name}
            </h1>
            <StatusPill status={tenant.status} />
          </div>
          <a
            href={`https://${subdomain}`}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors font-mono"
          >
            {subdomain}
            <ExternalLink className="size-3.5" />
          </a>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <a
            href={`https://${subdomain}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-9 items-center gap-1.5 px-3 rounded-md border border-border bg-card text-xs font-medium uppercase tracking-wide text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <ExternalLink className="size-3.5" />
            Visit CRM
          </a>
          <Link
            href={`/platform/logs?tenant=${encodeURIComponent(tenant.slug)}`}
            className="inline-flex h-9 items-center gap-1.5 px-3 rounded-md border border-border bg-card text-xs font-medium uppercase tracking-wide text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <ScrollText className="size-3.5" />
            View audit log
          </Link>
        </div>
      </header>

      {/* ─── Quick metrics row ────────────────────────────────────── */}
      <div className="mt-6 grid grid-cols-3 gap-3 sm:gap-4">
        <MetricTile label="Signed up" value={formatDate(tenant.created_at)} />
        <MetricTile
          label="Members"
          value={`${activeMembers}${
            activeMembers !== tenant.members.length
              ? ` / ${tenant.members.length}`
              : ''
          }`}
          hint={
            activeMembers !== tenant.members.length
              ? `${tenant.members.length - activeMembers} inactive`
              : 'all active'
          }
        />
        <MetricTile
          label="Locations"
          value={String(tenant.location_count)}
        />
      </div>

      {/* ─── Sections ─────────────────────────────────────────────── */}
      <div className="mt-8 space-y-6 lg:space-y-8">
        <IdentitySection
          slug={slug}
          tenantName={tenant.name}
          primaryColor={tenant.primary_color}
          logoUrl={tenant.logo_url}
        />
        <MembersSection members={tenant.members} />
        <LifecycleSection slug={slug} status={tenant.status} />
      </div>
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function BackLink() {
  return (
    <Link
      href="/platform/tenants"
      className="inline-flex items-center gap-1.5 text-xs uppercase tracking-[0.16em] text-muted-foreground hover:text-foreground transition-colors"
    >
      <ArrowLeft className="size-3.5" />
      All tenants
    </Link>
  );
}

function MetricTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3 sm:px-5 sm:py-4">
      <p className="text-[10px] sm:text-[11px] uppercase tracking-wide text-muted-foreground/85 font-medium">
        {label}
      </p>
      <p className="mt-1 font-serif text-lg sm:text-2xl font-semibold tracking-tight tabular-nums text-foreground truncate">
        {value}
      </p>
      {hint ? (
        <p className="mt-0.5 text-[11px] text-muted-foreground tabular-nums">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

// ── Identity ─────────────────────────────────────────────────────────

function IdentitySection({
  slug,
  tenantName,
  primaryColor,
  logoUrl,
}: {
  slug: string;
  tenantName: string;
  primaryColor: string;
  logoUrl: string;
}) {
  const update = useUpdatePlatformTenant(slug);
  const [name, setName] = useState(tenantName);
  const [color, setColor] = useState(primaryColor);
  const [logo, setLogo] = useState(logoUrl);

  const isDirty =
    name !== tenantName || color !== primaryColor || logo !== logoUrl;

  const handleSave = () => {
    update.mutate(
      { name, primary_color: color, logo_url: logo },
      {
        onSuccess: () => toast.success('Tenant updated.'),
        onError: () => toast.error('Update failed. Please try again.'),
      },
    );
  };

  return (
    <SectionCard title="Identity" icon={<Building2 className="size-4 text-muted-foreground" />}>
      <div className="grid gap-4 sm:gap-5">
        <Field>
          <FieldLabel htmlFor="name">Display name</FieldLabel>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="max-w-md"
          />
        </Field>

        <Field>
          <FieldLabel htmlFor="color">Brand primary color</FieldLabel>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="size-10 rounded-md border cursor-pointer p-1 bg-background"
              aria-label="Pick brand color"
            />
            <Input
              id="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="font-mono uppercase max-w-[140px]"
              placeholder="#95122C"
            />
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Shown on the tenant&apos;s login + booking pages only.
          </p>
        </Field>

        <Field>
          <FieldLabel htmlFor="logo_url">Logo URL</FieldLabel>
          <Input
            id="logo_url"
            value={logo}
            onChange={(e) => setLogo(e.target.value)}
            placeholder="https://…/logo.png"
            className="max-w-xl"
          />
        </Field>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 pt-4 mt-2 border-t">
        <Button
          variant="outline"
          disabled={!isDirty || update.isPending}
          onClick={() => {
            setName(tenantName);
            setColor(primaryColor);
            setLogo(logoUrl);
          }}
        >
          Discard
        </Button>
        <Button disabled={!isDirty || update.isPending} onClick={handleSave}>
          {update.isPending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </SectionCard>
  );
}

// ── Members ──────────────────────────────────────────────────────────

function MembersSection({ members }: { members: PlatformTenantMember[] }) {
  return (
    <SectionCard
      title={`Members (${members.length})`}
      icon={<Users className="size-4 text-muted-foreground" />}
    >
      {members.length === 0 ? (
        <p className="text-sm text-muted-foreground">No members yet.</p>
      ) : (
        <ul className="divide-y border rounded-md overflow-hidden">
          {members.map((m) => {
            const displayName =
              [m.user_first_name, m.user_last_name].filter(Boolean).join(' ') ||
              m.user_email;
            return (
              <li
                key={m.id}
                className={cn(
                  'flex items-center gap-3 px-4 py-3',
                  !m.is_active && 'opacity-50',
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground truncate">
                    {displayName}
                  </p>
                  <p className="text-xs text-muted-foreground truncate font-mono">
                    {m.user_email}
                  </p>
                </div>
                <span className="hidden sm:inline-block text-xs uppercase tracking-wide text-foreground/70 whitespace-nowrap">
                  {m.role_display}
                </span>
                {m.is_active ? (
                  <span className="text-[10px] uppercase tracking-wide text-emerald-300 whitespace-nowrap">
                    Active
                  </span>
                ) : (
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground whitespace-nowrap">
                    Inactive
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </SectionCard>
  );
}

// ── Lifecycle (suspend / reactivate) ─────────────────────────────────

function LifecycleSection({
  slug,
  status,
}: {
  slug: string;
  status: PlatformTenantStatus;
}) {
  const suspend = useSuspendPlatformTenant(slug);
  const reactivate = useReactivatePlatformTenant(slug);
  const [showSuspendForm, setShowSuspendForm] = useState(false);
  const [reason, setReason] = useState('');

  const handleSuspend = () => {
    if (!reason.trim()) {
      toast.error('Please enter a reason for the audit log.');
      return;
    }
    suspend.mutate(
      { reason: reason.trim() },
      {
        onSuccess: () => {
          toast.success('Tenant suspended.');
          setShowSuspendForm(false);
          setReason('');
        },
        onError: () => toast.error('Suspend failed. Please try again.'),
      },
    );
  };

  const handleReactivate = () => {
    if (
      !window.confirm(
        'Reactivate this tenant? They will regain access immediately.',
      )
    )
      return;
    reactivate.mutate(undefined, {
      onSuccess: () => toast.success('Tenant reactivated.'),
      onError: () => toast.error('Reactivate failed. Please try again.'),
    });
  };

  return (
    <SectionCard
      title="Lifecycle"
      icon={<Power className="size-4 text-muted-foreground" />}
      tone="caution"
    >
      {status === 'suspended' ? (
        <div className="space-y-4">
          <div className="flex items-start gap-2 rounded-md border border-rose-500/30 bg-rose-500/[0.06] px-4 py-3 text-sm">
            <AlertTriangle
              className="size-4 text-rose-300 mt-0.5 shrink-0"
              aria-hidden
            />
            <p className="text-foreground/85">
              This tenant is currently <strong>suspended</strong>. Members
              cannot sign in. Reactivate to restore access immediately.
            </p>
          </div>
          <Button
            variant="outline"
            disabled={reactivate.isPending}
            onClick={handleReactivate}
          >
            {reactivate.isPending ? 'Reactivating…' : 'Reactivate tenant'}
          </Button>
        </div>
      ) : status === 'cancelled' ? (
        <p className="text-sm text-muted-foreground italic">
          This tenant has been cancelled. Restoration requires a manual
          database action.
        </p>
      ) : showSuspendForm ? (
        <div className="space-y-4">
          <Field>
            <FieldLabel htmlFor="reason">Reason for suspension</FieldLabel>
            <textarea
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="flex w-full rounded-md border bg-background px-3 py-2 text-sm shadow-xs outline-none focus:border-ring focus:ring-3 focus:ring-ring/50"
              placeholder="Captured in the audit log. e.g. 'Non-payment after 60 days', 'Customer cancellation request'…"
              required
            />
            <p className="text-xs text-muted-foreground mt-1">
              Members lose access immediately on suspend. Reactivate any time
              to restore.
            </p>
          </Field>
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setShowSuspendForm(false);
                setReason('');
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSuspend}
              disabled={suspend.isPending || !reason.trim()}
            >
              {suspend.isPending ? 'Suspending…' : 'Suspend tenant'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Suspending pauses access for every member. Use for non-payment,
            ToS issues, or customer-requested holds. The reason you enter is
            captured in the platform audit log.
          </p>
          <Button variant="outline" onClick={() => setShowSuspendForm(true)}>
            Suspend tenant…
          </Button>
        </div>
      )}
    </SectionCard>
  );
}

// ── Local primitives ─────────────────────────────────────────────────

function SectionCard({
  title,
  icon,
  tone,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  tone?: 'caution';
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        'rounded-lg border bg-card overflow-hidden',
        tone === 'caution' && 'border-rose-500/20',
      )}
    >
      <header className="flex items-center gap-2 border-b px-4 sm:px-5 py-3">
        {icon}
        <h2 className="font-serif text-base font-semibold tracking-tight text-foreground">
          {title}
        </h2>
      </header>
      <div className="px-4 sm:px-5 py-4 sm:py-5 space-y-4">{children}</div>
    </section>
  );
}

function StatusPill({ status }: { status: PlatformTenantStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center h-6 px-2.5 rounded text-[11px] uppercase tracking-wide font-medium ring-1 whitespace-nowrap',
        STATUS_TONE[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
