/**
 * `/org/business` — owner-editable business profile + branding.
 *
 * Holds the truly account-level fields: identity (name + portal URL,
 * both read-only after onboarding) and branding (primary color + logo
 * URL, applied to client-facing surfaces only). Per-site fields
 * (address, hours, phone, email, timezone) live on each Location and
 * are managed at `/org/locations/[id]`.
 *
 * Why this page is shorter than the previous `/settings/business`:
 * those per-site fields moved out as part of the multi-location
 * rollout (Phase 4E). What remains is the account-level surface that
 * applies to the business as a whole.
 *
 * Saves go through `useUpdateTenantSettings()` which also invalidates
 * the auth `me` query so any cached tenant name in the sidebar /
 * dashboard refreshes immediately.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Building2, Globe, Info, Lock, Palette } from 'lucide-react';
import { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  type TenantSettings,
  useTenantSettings,
  useUpdateTenantSettings,
} from '@/lib/tenant';
import { cn } from '@/lib/utils';

const HEX_COLOR = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

const schema = z.object({
  primary_color: z
    .string()
    .regex(HEX_COLOR, 'Use a 6-digit hex like #95122C')
    .max(7),
  logo_url: z.string().url('Must be a valid URL').or(z.literal('')),
});

type FormValues = z.infer<typeof schema>;

export default function OrgBusinessPage() {
  const { data: tenant, isLoading, error } = useTenantSettings();

  if (isLoading) {
    return (
      <div className="px-10 py-10 max-w-7xl">
        <PageHeader title="Business profile" description="Loading…" />
      </div>
    );
  }
  if (error || !tenant) {
    return (
      <div className="px-10 py-10 max-w-7xl">
        <PageHeader title="Business profile" />
        <p className="text-sm text-destructive">Could not load business profile.</p>
      </div>
    );
  }
  return <BusinessForm tenant={tenant} />;
}

function BusinessForm({ tenant }: { tenant: TenantSettings }) {
  const update = useUpdateTenantSettings();

  const defaultValues: FormValues = useMemo(
    () => ({
      primary_color: tenant.primary_color,
      logo_url: tenant.logo_url,
    }),
    [tenant],
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues,
  });

  useEffect(() => {
    form.reset(defaultValues);
  }, [defaultValues, form]);

  const portalUrl = `${tenant.slug}.lumecrm.com`;

  const onSubmit = form.handleSubmit((values) => {
    update.mutate(values, {
      onSuccess: () => toast.success('Business profile saved'),
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error("You don't have permission to edit business settings.");
        } else if (
          err instanceof ApiError &&
          err.status === 400 &&
          typeof err.body === 'object' &&
          err.body
        ) {
          const body = err.body as Record<string, string[] | string>;
          const firstField = Object.keys(body)[0];
          const detail = firstField
            ? Array.isArray(body[firstField])
              ? (body[firstField] as string[])[0]
              : String(body[firstField])
            : 'Could not save changes.';
          toast.error(detail);
        } else {
          toast.error('Could not save changes. Please try again.');
        }
      },
    });
  });

  return (
    <div className="px-10 py-10 max-w-7xl">
      <PageHeader
        title="Business profile"
        description="Account-level details that apply to your whole business. Per-site settings (address, hours, contact) live with each location."
      />

      <form onSubmit={onSubmit}>
        <div className="divide-y border-t border-b">
          <Section
            title="Identity"
            description="Your business name and the URL your team uses to sign in. Both are locked after onboarding because they appear on invoices, receipts, and emails — contact support if you need to rename."
            icon={<Building2 className="size-4 text-muted-foreground" />}
          >
            <ReadOnlyField icon={<Lock className="size-3.5" />} label="Business name">
              {tenant.name}
            </ReadOnlyField>
            <ReadOnlyField icon={<Globe className="size-3.5" />} label="Portal URL">
              <span className="font-mono">{portalUrl}</span>
            </ReadOnlyField>
          </Section>

          <Section
            title="Branding"
            description="Color and logo shown on your staff's sign-in page and your public booking page. The staff CRM keeps the consistent Lumè look so workers across multiple businesses get one workspace."
            icon={<Palette className="size-4 text-muted-foreground" />}
          >
            <div className="rounded-md border border-accent/30 bg-accent/[0.04] px-3 py-2.5 flex items-start gap-2 text-xs">
              <Info className="size-3.5 shrink-0 text-accent mt-0.5" />
              <p className="text-foreground/90 leading-relaxed">
                These only appear to your{' '}
                <span className="font-medium">customers</span> (booking page) and
                your <span className="font-medium">staff at sign-in</span>.
                Inside the workspace your team uses the consistent Lumè
                interface.
              </p>
            </div>

            <Field>
              <FieldLabel htmlFor="primary_color">Primary color (hex)</FieldLabel>
              <div className="flex items-center gap-2">
                <Input
                  id="primary_color"
                  {...form.register('primary_color')}
                  className="font-mono uppercase max-w-[140px]"
                  placeholder="#95122C"
                />
                <ColorPreview hex={form.watch('primary_color')} />
              </div>
              <FieldError>{form.formState.errors.primary_color?.message}</FieldError>
            </Field>

            <Field>
              <FieldLabel htmlFor="logo_url">Logo URL</FieldLabel>
              <Input
                id="logo_url"
                type="url"
                {...form.register('logo_url')}
                placeholder="https://your-cdn.com/logo.png"
              />
              <p className="text-[11px] text-muted-foreground mt-1">
                Paste a URL to a hosted PNG or SVG. Direct upload is on the
                roadmap.
              </p>
              <FieldError>{form.formState.errors.logo_url?.message}</FieldError>
            </Field>
          </Section>
        </div>

        <div className="flex items-center justify-end gap-2 pt-4">
          <Button
            type="button"
            variant="outline"
            disabled={!form.formState.isDirty || update.isPending}
            onClick={() => form.reset(defaultValues)}
          >
            Reset
          </Button>
          <Button
            type="submit"
            disabled={!form.formState.isDirty || update.isPending}
          >
            {update.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </form>
    </div>
  );
}

// ── Layout primitives ────────────────────────────────────────────────

function Section({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6 lg:gap-12 py-6 first:pt-8 last:pb-8">
      <header>
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-serif text-base font-semibold tracking-tight">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
            {description}
          </p>
        ) : null}
      </header>
      <div className="space-y-3 max-w-2xl">{children}</div>
    </section>
  );
}

function ReadOnlyField({
  icon,
  label,
  children,
}: {
  icon?: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium flex items-center gap-1">
        {icon}
        {label}
      </p>
      <p className="text-sm mt-1">{children}</p>
    </div>
  );
}

function ColorPreview({ hex }: { hex: string }) {
  const valid = HEX_COLOR.test(hex);
  return (
    <div
      className={cn('size-8 rounded-md border shrink-0', !valid && 'bg-muted')}
      style={valid ? { backgroundColor: hex } : undefined}
      aria-hidden
      title={valid ? hex : 'Invalid hex'}
    />
  );
}
