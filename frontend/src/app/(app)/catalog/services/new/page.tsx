'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { CalendarClock, DollarSign, Sparkles } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
import {
  centsFromDollars,
  useCreateService,
  useServiceCategories,
} from '@/lib/services';

const schema = z.object({
  name: z.string().min(1, 'Name is required').max(200),
  code: z.string().max(20),
  description: z.string(),
  service_type: z.enum(['regular', 'addon']),
  category_id: z.string(),
  // Plain `z.number()` (not coerce) so zodResolver's input/output
  // types match. The `<Input type="number">`s register with
  // `valueAsNumber: true` to coerce on the RHF side.
  duration_minutes: z.number().int().min(1, 'Must be at least 1 minute'),
  buffer_minutes: z.number().int().min(0),
  price_dollars: z.string().refine((v) => v === '' || !Number.isNaN(Number(v)), 'Enter a number'),
  tax_rate_percent: z
    .string()
    .refine((v) => v === '' || !Number.isNaN(Number(v)), 'Enter a number')
    .refine((v) => v === '' || Number(v) >= 0, 'Must be 0 or higher')
    .refine((v) => v === '' || Number(v) < 100, 'Must be below 100'),
  is_bookable_online: z.boolean(),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

export default function NewServicePage() {
  const router = useRouter();
  const create = useCreateService();
  const { data: categories } = useServiceCategories();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      code: '',
      description: '',
      service_type: 'regular',
      category_id: '',
      duration_minutes: 60,
      buffer_minutes: 0,
      price_dollars: '',
      tax_rate_percent: '0',
      is_bookable_online: true,
      is_active: true,
    },
  });
  const watched = form.watch();

  const onSubmit = (values: FormValues) => {
    const payload = {
      name: values.name,
      code: values.code,
      description: values.description,
      service_type: values.service_type,
      category_id: values.category_id ? Number(values.category_id) : null,
      duration_minutes: values.duration_minutes,
      buffer_minutes: values.buffer_minutes,
      price_cents: centsFromDollars(values.price_dollars || '0'),
      tax_rate_percent: values.tax_rate_percent || '0',
      is_bookable_online: values.is_bookable_online,
      is_active: values.is_active,
    };
    create.mutate(payload, {
      onSuccess: (created) => {
        toast.success(`${created.name} added to catalog`);
        // Same stale-route bug as /catalog/categories/new: services
        // moved under /catalog/* in the Phase 1 IA reorg. Old
        // /services/<id> path 404s. Service WAS created — the
        // operator just landed on a missing page.
        router.push(`/catalog/services/${created.id}`);
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
          toast.error('Failed to create service. Please try again.');
        }
      },
    });
  };

  const previewPrice = watched.price_dollars
    ? `$${Number(watched.price_dollars || 0).toFixed(2)}`
    : '$0.00';
  const totalMinutes = (watched.duration_minutes || 0) + (watched.buffer_minutes || 0);

  return (
    <div className="px-10 py-10 max-w-5xl">
      <PageHeader
        title="New service"
        description="Add a service to your catalog. Required: name, duration, price."
        back={{ href: '/catalog/services', label: 'All services' }}
      />

      <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Form */}
          <div className="lg:col-span-2 space-y-10">
            <Section title="Basics" icon={<Sparkles className="size-4" />}>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Field
                  className="md:col-span-2"
                  data-invalid={form.formState.errors.name ? true : undefined}
                >
                  <FieldLabel htmlFor="name">Service name</FieldLabel>
                  <Input
                    id="name"
                    autoFocus
                    placeholder="e.g. Botox — 20 units"
                    {...form.register('name')}
                  />
                  {form.formState.errors.name ? (
                    <FieldError>{form.formState.errors.name.message}</FieldError>
                  ) : null}
                </Field>
                <Field data-invalid={form.formState.errors.code ? true : undefined}>
                  <FieldLabel htmlFor="code">
                    Code <span className="text-muted-foreground/70 font-normal ml-1">(SKU)</span>
                  </FieldLabel>
                  <Input
                    id="code"
                    placeholder="Auto"
                    className="font-mono"
                    {...form.register('code')}
                  />
                  {form.formState.errors.code ? (
                    <FieldError>{form.formState.errors.code.message}</FieldError>
                  ) : null}
                </Field>
              </div>
              <p className="text-xs text-muted-foreground -mt-2">
                Leave blank to auto-generate from the name (e.g. <code className="font-mono">BTX20</code>).
                Edit anytime; must be unique within your spa.
              </p>

              <Field>
                <FieldLabel htmlFor="description">
                  Description <span className="text-muted-foreground/70 font-normal ml-1">(optional)</span>
                </FieldLabel>
                <textarea
                  id="description"
                  rows={3}
                  placeholder="Shown to clients on the public booking page."
                  className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  {...form.register('description')}
                />
              </Field>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field>
                  <FieldLabel htmlFor="service_type">Type</FieldLabel>
                  <Select
                    value={watched.service_type}
                    onValueChange={(v) =>
                      form.setValue('service_type', v as 'regular' | 'addon', { shouldDirty: true })
                    }
                  >
                    <SelectTrigger id="service_type" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="regular">Regular service</SelectItem>
                      <SelectItem value="addon">Add-on</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    Add-ons attach to a regular appointment instead of booking their own slot.
                  </p>
                </Field>

                <Field>
                  <FieldLabel htmlFor="category_id">Category</FieldLabel>
                  <Select
                    value={watched.category_id}
                    onValueChange={(v) =>
                      form.setValue('category_id', v ?? '', { shouldDirty: true })
                    }
                  >
                    <SelectTrigger id="category_id" className="w-full">
                      <SelectValue placeholder="Uncategorized" />
                    </SelectTrigger>
                    <SelectContent>
                      {(categories ?? []).map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>
                          {c.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    Eligibility (which staff can perform) is configured at the category level.
                  </p>
                </Field>
              </div>
            </Section>

            <Section title="Duration" icon={<CalendarClock className="size-4" />}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field data-invalid={form.formState.errors.duration_minutes ? true : undefined}>
                  <FieldLabel htmlFor="duration_minutes">Service time (minutes)</FieldLabel>
                  <Input
                    id="duration_minutes"
                    type="number"
                    min={1}
                    {...form.register('duration_minutes', { valueAsNumber: true })}
                  />
                  {form.formState.errors.duration_minutes ? (
                    <FieldError>{form.formState.errors.duration_minutes.message}</FieldError>
                  ) : null}
                </Field>
                <Field>
                  <FieldLabel htmlFor="buffer_minutes">Buffer after (minutes)</FieldLabel>
                  <Input
                    id="buffer_minutes"
                    type="number"
                    min={0}
                    {...form.register('buffer_minutes', { valueAsNumber: true })}
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Cleanup / setup time, kept off the bookable schedule.
                  </p>
                </Field>
              </div>
            </Section>

            <Section title="Pricing" icon={<DollarSign className="size-4" />}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Field data-invalid={form.formState.errors.price_dollars ? true : undefined}>
                  <FieldLabel htmlFor="price_dollars">Price (USD)</FieldLabel>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                      $
                    </span>
                    <Input
                      id="price_dollars"
                      type="text"
                      inputMode="decimal"
                      placeholder="0.00"
                      className="pl-7"
                      {...form.register('price_dollars')}
                    />
                  </div>
                  {form.formState.errors.price_dollars ? (
                    <FieldError>{form.formState.errors.price_dollars.message}</FieldError>
                  ) : null}
                </Field>
                <Field data-invalid={form.formState.errors.tax_rate_percent ? true : undefined}>
                  <FieldLabel htmlFor="tax_rate_percent">Tax rate</FieldLabel>
                  <div className="relative">
                    <Input
                      id="tax_rate_percent"
                      type="text"
                      inputMode="decimal"
                      placeholder="0.000"
                      className="pr-7"
                      {...form.register('tax_rate_percent')}
                    />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                      %
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Applied at invoice time. Up to 3 decimal places (e.g. 8.875).
                  </p>
                  {form.formState.errors.tax_rate_percent ? (
                    <FieldError>{form.formState.errors.tax_rate_percent.message}</FieldError>
                  ) : null}
                </Field>
              </div>
            </Section>

            <Section title="Booking" icon={<CalendarClock className="size-4" />}>
              <div className="space-y-3">
                <CheckboxRow
                  id="is_bookable_online"
                  label="Bookable on the public booking page"
                  description="Uncheck for staff-only services like consultations or VIP-only treatments."
                  checked={watched.is_bookable_online}
                  onChange={(v) => form.setValue('is_bookable_online', v, { shouldDirty: true })}
                />
                <CheckboxRow
                  id="is_active"
                  label="Active"
                  description="Inactive services stay on past appointments and invoices but cannot be booked."
                  checked={watched.is_active}
                  onChange={(v) => form.setValue('is_active', v, { shouldDirty: true })}
                />
              </div>
            </Section>
          </div>

          {/* Live preview */}
          <aside className="lg:sticky lg:top-10 self-start">
            <div className="rounded-xl border bg-card p-6">
              <p className="text-xs uppercase tracking-wide text-muted-foreground mb-4">
                Live preview
              </p>
              <div className="space-y-3">
                <h3 className="font-serif text-xl font-semibold tracking-tight">
                  {watched.name || 'New service'}
                </h3>
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-mono text-2xl font-medium tracking-tight">
                    {previewPrice}
                  </span>
                  <span className="text-muted-foreground">·</span>
                  <span className="text-muted-foreground tabular-nums">{totalMinutes}m</span>
                </div>
                {watched.description ? (
                  <p className="text-sm text-muted-foreground line-clamp-3 whitespace-pre-wrap">
                    {watched.description}
                  </p>
                ) : null}
              </div>
            </div>
            <p className="text-xs text-muted-foreground mt-3 px-1">
              This preview matches how the service will appear on the calendar block and the
              public booking page.
            </p>
          </aside>
        </div>

        <div className="sticky bottom-0 -mx-10 mt-10 px-10 py-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="flex items-center justify-end gap-2 max-w-5xl mx-auto">
            <Button render={<Link href="/catalog/services" />} nativeButton={false} variant="outline">
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Saving…' : 'Save service'}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

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

function CheckboxRow({
  id,
  label,
  description,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  description?: string;
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
      <div>
        <p className="leading-relaxed">{label}</p>
        {description ? (
          <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
        ) : null}
      </div>
    </label>
  );
}
