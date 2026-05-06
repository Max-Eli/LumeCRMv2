/**
 * `/platform/tenants/[slug]` — tenant detail.
 *
 * Three sections:
 *   - Identity      — name, slug, status pill, signup date, branding edit
 *   - Members       — every membership row (active + inactive) with role
 *   - Lifecycle     — suspend / reactivate actions
 *
 * Suspending requires a written reason that lands in the audit log.
 * The reactivation is a single-button confirm (no required reason).
 *
 * Param convention: Next 16's dynamic segment is `[id]` here, but we
 * use the slug as the value — Next doesn't care, the segment name is
 * just a key. Slug-based URLs read cleaner ("acmespa" beats a PK).
 */

'use client';

import { AlertTriangle, ArrowLeft, Building2, Power, Users } from 'lucide-react';
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

export default function PlatformTenantDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: slug } = use(params);
  const { data: tenant, isLoading, error } = usePlatformTenant(slug);

  if (isLoading) {
    return (
      <div className="px-10 py-10 text-sm text-muted-foreground">Loading tenant…</div>
    );
  }
  if (error || !tenant) {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <Link
          href="/platform/tenants"
          className="inline-flex items-center gap-1.5 text-xs uppercase tracking-[0.16em] text-muted-foreground hover:text-foreground transition-colors mb-6"
        >
          <ArrowLeft className="size-3.5" />
          Tenants
        </Link>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">Tenant not found</h1>
        <p className="text-sm text-destructive mt-2">
          Failed to load this tenant.
        </p>
      </div>
    );
  }

  return (
    <div className="px-10 py-10 max-w-7xl">
      <Link
        href="/platform/tenants"
        className="inline-flex items-center gap-1.5 text-xs uppercase tracking-[0.16em] text-muted-foreground hover:text-foreground transition-colors mb-6"
      >
        <ArrowLeft className="size-3.5" />
        Tenants
      </Link>

      <header className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            Platform Admin · Tenant detail
          </p>
          <div className="flex items-baseline gap-3 mt-2">
            <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
              {tenant.name}
            </h1>
            <StatusPill status={tenant.status} />
          </div>
          <p className="mt-2 text-sm text-muted-foreground font-mono">
            {tenant.slug}.lumecrm.com
          </p>
        </div>
      </header>

      <div className="space-y-8">
        <IdentitySection slug={slug} tenantName={tenant.name} primaryColor={tenant.primary_color} logoUrl={tenant.logo_url} />
        <MembersSection members={tenant.members} />
        <LifecycleSection slug={slug} status={tenant.status} />
      </div>
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

  const isDirty = name !== tenantName || color !== primaryColor || logo !== logoUrl;

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
      <Field>
        <FieldLabel htmlFor="name">Display name</FieldLabel>
        <Input id="name" value={name} onChange={(e) => setName(e.target.value)} className="max-w-md" />
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
          Shown on the tenant's login + booking pages only.
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

      <div className="flex items-center justify-end gap-2 pt-3 border-t">
        <Button variant="outline" disabled={!isDirty || update.isPending} onClick={() => { setName(tenantName); setColor(primaryColor); setLogo(logoUrl); }}>
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
          {members.map((m) => (
            <li
              key={m.id}
              className={cn(
                'grid grid-cols-[1fr_auto_auto] items-center gap-4 px-4 py-3',
                !m.is_active && 'opacity-50',
              )}
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground truncate">
                  {m.user_first_name} {m.user_last_name}
                  {(!m.user_first_name && !m.user_last_name) ? m.user_email : null}
                </p>
                <p className="text-xs text-muted-foreground truncate font-mono">{m.user_email}</p>
              </div>
              <span className="text-xs uppercase tracking-wide text-foreground/70">
                {m.role_display}
              </span>
              {m.is_active ? (
                <span className="text-[10px] uppercase tracking-wide text-emerald-300">Active</span>
              ) : (
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Inactive</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

// ── Lifecycle (suspend / reactivate) ─────────────────────────────────

function LifecycleSection({ slug, status }: { slug: string; status: PlatformTenantStatus }) {
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
    if (!window.confirm('Reactivate this tenant? They will regain access immediately.')) return;
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
            <AlertTriangle className="size-4 text-rose-300 mt-0.5 shrink-0" aria-hidden />
            <p className="text-foreground/85">
              This tenant is currently <strong>suspended</strong>. Members
              cannot sign in. Reactivate to restore access immediately.
            </p>
          </div>
          <Button variant="outline" disabled={reactivate.isPending} onClick={handleReactivate}>
            {reactivate.isPending ? 'Reactivating…' : 'Reactivate tenant'}
          </Button>
        </div>
      ) : status === 'cancelled' ? (
        <p className="text-sm text-muted-foreground italic">
          This tenant has been cancelled. Restoration requires a manual database action.
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
              Members lose access immediately on suspend. Reactivate any time to restore.
            </p>
          </Field>
          <div className="flex items-center justify-end gap-2">
            <Button variant="outline" onClick={() => { setShowSuspendForm(false); setReason(''); }}>
              Cancel
            </Button>
            <Button onClick={handleSuspend} disabled={suspend.isPending || !reason.trim()}>
              {suspend.isPending ? 'Suspending…' : 'Suspend tenant'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Suspending pauses access for every member. Use for non-payment, ToS issues, or customer-requested holds. The reason you enter is captured in the platform audit log.
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
      <header className="flex items-center gap-2 border-b px-5 py-3">
        {icon}
        <h2 className="font-serif text-base font-semibold tracking-tight text-foreground">
          {title}
        </h2>
      </header>
      <div className="px-5 py-5 space-y-4">{children}</div>
    </section>
  );
}

function StatusPill({ status }: { status: PlatformTenantStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center h-6 px-2.5 rounded text-[11px] uppercase tracking-wide font-medium ring-1',
        STATUS_TONE[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}
