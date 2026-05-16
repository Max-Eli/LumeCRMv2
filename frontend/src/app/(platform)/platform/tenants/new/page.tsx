/**
 * `/platform/tenants/new` — create a new customer tenant.
 *
 * Single-page form: tenant name, slug (with live "x.xn--lumcrm-5ua.com"
 * preview), owner email + name, initial status. On submit:
 *   - If owner email is a NEW user → backend provisions one with a
 *     temp password, surfaced exactly once in the success state for
 *     the operator to copy and share over a secure channel.
 *   - If owner email matches an EXISTING user → attached as a new
 *     owner membership; no temp password.
 *
 * The success state shows the temp password ONCE with a copy button;
 * leaving the page (or refreshing) wipes it. We never persist the
 * temp password in audit logs or any DB row beyond the initial
 * `set_password` hash.
 */

'use client';

import { ArrowLeft, Building2, Check, ClipboardCopy } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  type PlatformTenantStatus,
  type PlatformTenantDetailWithTempPassword,
  useCreatePlatformTenant,
} from '@/lib/platform';

interface FormState {
  name: string;
  slug: string;
  owner_email: string;
  owner_first_name: string;
  owner_last_name: string;
  status: PlatformTenantStatus;
}

const INITIAL: FormState = {
  name: '',
  slug: '',
  owner_email: '',
  owner_first_name: '',
  owner_last_name: '',
  status: 'trial',
};

export default function NewPlatformTenantPage() {
  const router = useRouter();
  const create = useCreatePlatformTenant();
  const [form, setForm] = useState<FormState>(INITIAL);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});
  const [success, setSuccess] = useState<PlatformTenantDetailWithTempPassword | null>(null);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }));
  };

  // Auto-generate the slug from the name as the operator types — only
  // until they manually edit the slug field, after which we leave
  // their explicit choice alone. (`slugTouched` ratchets one-way.)
  const [slugTouched, setSlugTouched] = useState(false);
  const handleNameChange = (value: string) => {
    update('name', value);
    if (!slugTouched) {
      const auto = value
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 63);
      setForm((f) => ({ ...f, slug: auto }));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    create.mutate(form, {
      onSuccess: (created) => {
        toast.success(`Tenant "${created.name}" created.`);
        setSuccess(created);
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 400 && err.body && typeof err.body === 'object') {
          const body = err.body as Record<string, string[] | string>;
          const fieldErrors: Partial<Record<keyof FormState, string>> = {};
          for (const [k, msgs] of Object.entries(body)) {
            const message = Array.isArray(msgs) ? msgs[0] : String(msgs);
            if (k in INITIAL) {
              fieldErrors[k as keyof FormState] = message;
            }
          }
          setErrors(fieldErrors);
          toast.error('Please fix the highlighted fields.');
        } else {
          toast.error('Could not create tenant. Please try again.');
        }
      },
    });
  };

  if (success) {
    return <CreatedSuccess tenant={success} onContinue={() => router.push(`/platform/tenants/${success.slug}`)} />;
  }

  return (
    <div className="px-10 py-10 max-w-3xl">
      <Link
        href="/platform/tenants"
        className="inline-flex items-center gap-1.5 text-xs uppercase tracking-[0.16em] text-muted-foreground hover:text-foreground transition-colors mb-6"
      >
        <ArrowLeft className="size-3.5" />
        Tenants
      </Link>

      <header className="mb-8">
        <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
          Platform Admin · New tenant
        </p>
        <h1 className="mt-2 font-serif text-3xl font-semibold tracking-tight text-foreground">
          Create a customer tenant
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Provisions a tenant, a default location, the standard job-title list,
          and an owner membership. If the owner email is new to Lumè, a
          temp password is returned once for you to share securely.
        </p>
      </header>

      <form onSubmit={handleSubmit} noValidate>
        <div className="divide-y border-t border-b">
          <Section
            title="Tenant"
            description="The customer spa. Slug becomes the production subdomain — pick carefully; changing it later breaks every bookmarked URL."
            icon={<Building2 className="size-4 text-muted-foreground" />}
          >
            <Field data-invalid={errors.name ? true : undefined}>
              <FieldLabel htmlFor="name">Spa name</FieldLabel>
              <Input
                id="name"
                value={form.name}
                onChange={(e) => handleNameChange(e.target.value)}
                placeholder="Acme Med Spa"
                required
              />
              {errors.name ? <FieldError>{errors.name}</FieldError> : null}
            </Field>

            <Field data-invalid={errors.slug ? true : undefined}>
              <FieldLabel htmlFor="slug">Subdomain slug</FieldLabel>
              <div className="flex items-center gap-2">
                <Input
                  id="slug"
                  value={form.slug}
                  onChange={(e) => {
                    setSlugTouched(true);
                    update('slug', e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''));
                  }}
                  className="font-mono w-44"
                  placeholder="acmespa"
                  required
                />
                <span className="text-sm text-muted-foreground font-mono">
                  .xn--lumcrm-5ua.com
                </span>
              </div>
              {errors.slug ? (
                <FieldError>{errors.slug}</FieldError>
              ) : (
                <p className="text-xs text-muted-foreground mt-1">
                  Lowercase letters, numbers, hyphens. Reserved slugs (admin, api, app, platform) are blocked.
                </p>
              )}
            </Field>

            <Field>
              <FieldLabel htmlFor="status">Initial status</FieldLabel>
              <select
                id="status"
                value={form.status}
                onChange={(e) => update('status', e.target.value as PlatformTenantStatus)}
                className="h-9 w-44 rounded-md border bg-background px-3 text-sm shadow-xs outline-none focus:border-ring focus:ring-3 focus:ring-ring/50"
              >
                <option value="trial">Trial</option>
                <option value="active">Active</option>
              </select>
              <p className="text-xs text-muted-foreground mt-1">
                "Trial" if you haven't billed them yet. Move to "Active" when payment lands.
              </p>
            </Field>
          </Section>

          <Section
            title="Owner"
            description="The first user added to this tenant. New email → user provisioned with a one-time temp password (returned in the success screen). Existing email → user attached as a new membership."
            icon={<span className="size-4 inline-flex items-center justify-center text-accent">@</span>}
          >
            <Field data-invalid={errors.owner_email ? true : undefined}>
              <FieldLabel htmlFor="owner_email">Owner email</FieldLabel>
              <Input
                id="owner_email"
                type="email"
                value={form.owner_email}
                onChange={(e) => update('owner_email', e.target.value)}
                placeholder="owner@acmespa.com"
                required
              />
              {errors.owner_email ? <FieldError>{errors.owner_email}</FieldError> : null}
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="owner_first_name">First name</FieldLabel>
                <Input
                  id="owner_first_name"
                  value={form.owner_first_name}
                  onChange={(e) => update('owner_first_name', e.target.value)}
                  placeholder="Sarah"
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="owner_last_name">Last name</FieldLabel>
                <Input
                  id="owner_last_name"
                  value={form.owner_last_name}
                  onChange={(e) => update('owner_last_name', e.target.value)}
                  placeholder="Chen"
                />
              </Field>
            </div>
          </Section>
        </div>

        <div className="flex items-center justify-end gap-2 pt-6">
          <Button type="button" variant="outline" onClick={() => router.push('/platform/tenants')}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create tenant'}
          </Button>
        </div>
      </form>
    </div>
  );
}

function CreatedSuccess({
  tenant,
  onContinue,
}: {
  tenant: PlatformTenantDetailWithTempPassword;
  onContinue: () => void;
}) {
  const tempPassword = tenant.owner_temp_password;
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!tempPassword) return;
    try {
      await navigator.clipboard.writeText(tempPassword);
      setCopied(true);
      toast.success('Temp password copied.');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Could not copy to clipboard.');
    }
  };

  return (
    <div className="px-10 py-10 max-w-3xl">
      <header className="mb-8">
        <p className="text-[11px] uppercase tracking-[0.16em] text-accent">
          Tenant created
        </p>
        <h1 className="mt-2 font-serif text-3xl font-semibold tracking-tight text-foreground">
          {tenant.name} is live.
        </h1>
        <p className="mt-2 text-sm text-muted-foreground font-mono">
          {tenant.slug}.xn--lumcrm-5ua.com
        </p>
      </header>

      {tempPassword ? (
        <div className="rounded-lg border border-accent/40 bg-accent/[0.05] p-6">
          <p className="text-[11px] uppercase tracking-[0.16em] text-accent font-medium">
            One-time owner password
          </p>
          <p className="mt-2 text-sm text-foreground/80">
            A new user was provisioned for{' '}
            <span className="font-mono">{tenant.members[0]?.user_email}</span>. Share
            this password with them over a secure channel — it will not be
            shown again, and we don't store it anywhere on our side.
          </p>
          <div className="mt-4 flex items-center gap-2 rounded-md border bg-background px-4 py-3">
            <code className="flex-1 font-mono text-base tracking-wider text-foreground">
              {tempPassword}
            </code>
            <Button type="button" variant="outline" onClick={handleCopy} className="gap-1.5">
              {copied ? <Check className="size-3.5" /> : <ClipboardCopy className="size-3.5" />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border bg-card px-6 py-5">
          <p className="text-sm text-foreground/80">
            Existing user{' '}
            <span className="font-mono">{tenant.members[0]?.user_email}</span> was
            attached as the owner. They can sign in at{' '}
            <span className="font-mono">{tenant.slug}.xn--lumcrm-5ua.com</span> with
            their existing password.
          </p>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 mt-8">
        <Button onClick={onContinue}>Open tenant detail</Button>
      </div>
    </div>
  );
}

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
    <section className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 lg:gap-12 py-6 first:pt-8 last:pb-8">
      <header>
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-serif text-base font-semibold tracking-tight text-foreground">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">{description}</p>
        ) : null}
      </header>
      <div className="space-y-3">{children}</div>
    </section>
  );
}
