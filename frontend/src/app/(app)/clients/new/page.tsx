'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Heart, MapPin, Megaphone, Shield, User } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { InitialsAvatar } from '@/components/initials-avatar';
import { PageHeader } from '@/components/page-header';
import { StatusBadge } from '@/components/status-badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ApiError } from '@/lib/api';
import { useCreateCustomer } from '@/lib/customers';

const schema = z.object({
  first_name: z.string().min(1, 'First name is required').max(100),
  last_name: z.string().min(1, 'Last name is required').max(100),
  preferred_name: z.string().max(100).optional(),
  email: z.string().email('Enter a valid email').or(z.literal('')).optional(),
  phone: z.string().max(20).optional(),
  date_of_birth: z.string().optional(),
  sex: z.enum(['', 'female', 'male', 'other', 'prefer_not_to_say']).optional(),
  address_line1: z.string().max(200).optional(),
  address_line2: z.string().max(200).optional(),
  city: z.string().max(100).optional(),
  state: z.string().max(2).optional(),
  zip_code: z.string().max(10).optional(),
  emergency_name: z.string().max(200).optional(),
  emergency_phone: z.string().max(20).optional(),
  emergency_relationship: z.string().max(50).optional(),
  email_opt_in: z.boolean(),
  sms_opt_in: z.boolean(),
  // Promotional marketing consent — separate from transactional
  // confirmations above (ADR 0016). Pre-checked so the operator's
  // common-path doesn't require an extra click, but visible on
  // screen so leaving the checkbox checked counts as an explicit
  // operator-affirmed consent action. Same pattern Mindbody and
  // Boulevard use for front-desk-added clients. Consent source
  // stamps as 'manual' on the backend so the audit trail is
  // defensible under TCPA / CAN-SPAM.
  email_marketing_opt_in: z.boolean(),
  sms_marketing_opt_in: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

export default function NewClientPage() {
  const router = useRouter();
  const create = useCreateCustomer();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      first_name: '',
      last_name: '',
      preferred_name: '',
      email: '',
      phone: '',
      date_of_birth: '',
      sex: '',
      address_line1: '',
      address_line2: '',
      city: '',
      state: '',
      zip_code: '',
      emergency_name: '',
      emergency_phone: '',
      emergency_relationship: '',
      email_opt_in: true,
      sms_opt_in: true,
      email_marketing_opt_in: true,
      sms_marketing_opt_in: true,
    },
  });

  // Watch form values to power the live preview pane.
  const watched = form.watch();
  const previewName =
    watched.preferred_name?.trim()
      ? `${watched.preferred_name} ${watched.last_name}`.trim()
      : `${watched.first_name} ${watched.last_name}`.trim();
  const hasIdentity = Boolean(watched.first_name || watched.last_name);

  const submit = (values: FormValues, andAddAnother: boolean) => {
    const payload = {
      ...values,
      date_of_birth: values.date_of_birth || null,
      sex: values.sex || undefined,
      state: values.state ? values.state.toUpperCase() : '',
    };

    create.mutate(payload, {
      onSuccess: (created) => {
        toast.success(`${created.full_name || 'Client'} created`);
        if (andAddAnother) {
          form.reset();
        } else {
          router.push(`/clients/${created.id}`);
        }
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
          const fieldErrors = err.body as Record<string, string[] | string>;
          for (const [field, msgs] of Object.entries(fieldErrors)) {
            const message = Array.isArray(msgs) ? msgs[0] : String(msgs);
            form.setError(field as keyof FormValues, { message });
          }
          toast.error('Please fix the highlighted fields.');
        } else {
          toast.error('Failed to create client. Please try again.');
        }
      },
    });
  };

  return (
    <div className="px-10 py-10 max-w-6xl">
      <PageHeader
        title="New client"
        description="Capture the essentials. You can add medical history, photos, and other details from the client's chart later."
        back={{ href: '/clients', label: 'Back to clients' }}
      />

      <form onSubmit={form.handleSubmit((v) => submit(v, false))} noValidate>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* ── Form column ────────────────────────────────────────────────── */}
          <div className="lg:col-span-2 space-y-10">
            <Section title="Identity" icon={<User className="size-4" />}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field data-invalid={form.formState.errors.first_name ? true : undefined}>
                  <FieldLabel htmlFor="first_name">
                    First name <Required />
                  </FieldLabel>
                  <Input id="first_name" autoFocus {...form.register('first_name')} />
                  {form.formState.errors.first_name ? (
                    <FieldError>{form.formState.errors.first_name.message}</FieldError>
                  ) : null}
                </Field>
                <Field data-invalid={form.formState.errors.last_name ? true : undefined}>
                  <FieldLabel htmlFor="last_name">
                    Last name <Required />
                  </FieldLabel>
                  <Input id="last_name" {...form.register('last_name')} />
                  {form.formState.errors.last_name ? (
                    <FieldError>{form.formState.errors.last_name.message}</FieldError>
                  ) : null}
                </Field>
              </div>

              <Field>
                <FieldLabel htmlFor="preferred_name">
                  Preferred name <Optional />
                </FieldLabel>
                <Input
                  id="preferred_name"
                  placeholder="What they like to be called"
                  {...form.register('preferred_name')}
                />
              </Field>
            </Section>

            <Section title="Contact" icon={<User className="size-4" />}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field data-invalid={form.formState.errors.email ? true : undefined}>
                  <FieldLabel htmlFor="email">Email</FieldLabel>
                  <Input
                    id="email"
                    type="email"
                    placeholder="client@example.com"
                    {...form.register('email')}
                  />
                  {form.formState.errors.email ? (
                    <FieldError>{form.formState.errors.email.message}</FieldError>
                  ) : null}
                </Field>
                <Field>
                  <FieldLabel htmlFor="phone">Phone</FieldLabel>
                  <Input id="phone" type="tel" placeholder="(555) 555-5555" {...form.register('phone')} />
                </Field>
              </div>
            </Section>

            <Section title="Personal" icon={<Heart className="size-4" />}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field>
                  <FieldLabel htmlFor="date_of_birth">Date of birth</FieldLabel>
                  <Input id="date_of_birth" type="date" {...form.register('date_of_birth')} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="sex">Sex</FieldLabel>
                  <Select
                    value={watched.sex ?? ''}
                    onValueChange={(value) =>
                      form.setValue('sex', (value || '') as FormValues['sex'])
                    }
                  >
                    <SelectTrigger id="sex" className="w-full">
                      <SelectValue placeholder="Select sex" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="female">Female</SelectItem>
                      <SelectItem value="male">Male</SelectItem>
                      <SelectItem value="other">Other</SelectItem>
                      <SelectItem value="prefer_not_to_say">Prefer not to say</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              </div>
            </Section>

            <Section title="Address" icon={<MapPin className="size-4" />}>
              <Field>
                <FieldLabel htmlFor="address_line1">Street</FieldLabel>
                <Input id="address_line1" {...form.register('address_line1')} />
              </Field>
              <Field>
                <FieldLabel htmlFor="address_line2">Apt / Suite / Unit</FieldLabel>
                <Input id="address_line2" {...form.register('address_line2')} />
              </Field>
              <div className="grid grid-cols-1 md:grid-cols-6 gap-4">
                <Field className="md:col-span-3">
                  <FieldLabel htmlFor="city">City</FieldLabel>
                  <Input id="city" {...form.register('city')} />
                </Field>
                <Field className="md:col-span-1">
                  <FieldLabel htmlFor="state">State</FieldLabel>
                  <Input id="state" placeholder="NY" maxLength={2} {...form.register('state')} />
                </Field>
                <Field className="md:col-span-2">
                  <FieldLabel htmlFor="zip_code">ZIP</FieldLabel>
                  <Input id="zip_code" {...form.register('zip_code')} />
                </Field>
              </div>
            </Section>

            <Section title="Emergency contact" icon={<Shield className="size-4" />}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field>
                  <FieldLabel htmlFor="emergency_name">Name</FieldLabel>
                  <Input id="emergency_name" {...form.register('emergency_name')} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="emergency_phone">Phone</FieldLabel>
                  <Input
                    id="emergency_phone"
                    type="tel"
                    {...form.register('emergency_phone')}
                  />
                </Field>
              </div>
              <Field>
                <FieldLabel htmlFor="emergency_relationship">Relationship</FieldLabel>
                <Input
                  id="emergency_relationship"
                  placeholder="Spouse, parent, friend…"
                  {...form.register('emergency_relationship')}
                />
              </Field>
            </Section>

            <Section title="Communication preferences" icon={<Megaphone className="size-4" />}>
              <div className="space-y-1">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
                  Transactional (booking confirmations, reminders)
                </p>
                <div className="space-y-3 mt-2">
                  <CheckboxRow
                    id="email_opt_in"
                    label="Send appointment confirmations and reminders by email"
                    checked={watched.email_opt_in}
                    onChange={(v) => form.setValue('email_opt_in', v)}
                  />
                  <CheckboxRow
                    id="sms_opt_in"
                    label="Send appointment confirmations and reminders by text message"
                    checked={watched.sms_opt_in}
                    onChange={(v) => form.setValue('sms_opt_in', v)}
                  />
                </div>
              </div>

              <div className="space-y-1 pt-2 border-t">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mt-3">
                  Promotional marketing (campaigns)
                </p>
                <div className="space-y-3 mt-2">
                  <CheckboxRow
                    id="email_marketing_opt_in"
                    label="Include in promotional email campaigns"
                    checked={watched.email_marketing_opt_in}
                    onChange={(v) => form.setValue('email_marketing_opt_in', v)}
                  />
                  <CheckboxRow
                    id="sms_marketing_opt_in"
                    label="Include in promotional SMS campaigns"
                    checked={watched.sms_marketing_opt_in}
                    onChange={(v) => form.setValue('sms_marketing_opt_in', v)}
                  />
                </div>
              </div>

              <p className="text-xs text-muted-foreground">
                Promotional channels are separate from transactional confirmations.
                Leaving these checked records the client&apos;s consent at the time you
                added them (front-desk consent pattern). Clients can unsubscribe at
                any time from the footer of any campaign email or SMS.
              </p>
            </Section>
          </div>

          {/* ── Live preview column ───────────────────────────────────────── */}
          <aside className="lg:sticky lg:top-10 self-start">
            <div className="rounded-xl border bg-card p-6">
              <p className="text-xs uppercase tracking-wide text-muted-foreground mb-4">
                Live preview
              </p>
              <div className="flex flex-col items-center text-center">
                <InitialsAvatar name={previewName || '—'} size="xl" />
                <h3 className="font-serif text-xl font-semibold tracking-tight mt-3">
                  {hasIdentity ? previewName || '—' : 'New client'}
                </h3>
                {watched.preferred_name?.trim() && hasIdentity ? (
                  <p className="text-xs text-muted-foreground mt-1">
                    Legal: {watched.first_name} {watched.last_name}
                  </p>
                ) : null}
                <div className="mt-3">
                  <StatusBadge tone="success">active</StatusBadge>
                </div>
              </div>

              <div className="mt-6 pt-6 border-t space-y-2 text-sm">
                <PreviewRow label="Email" value={watched.email} muted="No email yet" />
                <PreviewRow label="Phone" value={watched.phone} muted="No phone yet" />
                <PreviewRow
                  label="Date of birth"
                  value={watched.date_of_birth}
                  muted="Not provided"
                />
              </div>

              <div className="mt-6 pt-6 border-t text-xs text-muted-foreground space-y-1.5">
                <ChecklistRow done={hasIdentity} label="Name" />
                <ChecklistRow done={Boolean(watched.email || watched.phone)} label="Contact info" />
                <ChecklistRow
                  done={Boolean(
                    watched.address_line1 || watched.city || watched.state || watched.zip_code,
                  )}
                  label="Address"
                />
                <ChecklistRow done={Boolean(watched.emergency_name)} label="Emergency contact" />
              </div>
            </div>

            <p className="text-xs text-muted-foreground mt-3 px-1">
              Medical history, allergies, photos, and consent forms are captured from the client's
              chart after the first appointment is booked.
            </p>
          </aside>
        </div>

        {/* ── Sticky save bar ────────────────────────────────────────────── */}
        <div className="sticky bottom-0 -mx-10 mt-10 px-10 py-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="flex items-center justify-end gap-2 max-w-6xl mx-auto">
            <Button render={<Link href="/clients" />} nativeButton={false} variant="outline">
              Cancel
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={create.isPending}
              onClick={form.handleSubmit((v) => submit(v, true))}
            >
              Save and add another
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Saving…' : 'Save and view'}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

// ── Local helpers ────────────────────────────────────────────────────────

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="flex items-center gap-2 mb-4 pb-2 border-b">
        <span className="text-muted-foreground">{icon}</span>
        <h2 className="text-sm font-medium uppercase tracking-wide text-foreground">{title}</h2>
      </header>
      <FieldGroup>{children}</FieldGroup>
    </section>
  );
}

function Required() {
  return <span className="text-accent text-xs ml-0.5" aria-label="required">•</span>;
}

function Optional() {
  return <span className="text-muted-foreground/70 text-xs font-normal ml-1">(optional)</span>;
}

function CheckboxRow({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label htmlFor={id} className="flex items-start gap-3 text-sm cursor-pointer">
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(v) => onChange(Boolean(v))}
        className="mt-0.5"
      />
      <span className="leading-relaxed">{label}</span>
    </label>
  );
}

function PreviewRow({
  label,
  value,
  muted,
}: {
  label: string;
  value: string | undefined;
  muted: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={
          value?.trim()
            ? 'text-sm font-medium truncate text-foreground'
            : 'text-sm text-muted-foreground/60 italic'
        }
      >
        {value?.trim() || muted}
      </span>
    </div>
  );
}

function ChecklistRow({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={
          done
            ? 'inline-flex size-1.5 shrink-0 rounded-full bg-emerald-500'
            : 'inline-flex size-1.5 shrink-0 rounded-full bg-muted-foreground/30'
        }
        aria-hidden
      />
      <span className={done ? 'text-foreground/80' : ''}>{label}</span>
    </div>
  );
}
