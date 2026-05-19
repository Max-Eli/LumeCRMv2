/**
 * Service detail page — tabbed shell mirroring the customer detail layout.
 *
 * Tabs: General (full editable form), Locations, Inventory, Commissions, Forms.
 * Only General is implemented today — the other four are placeholders that fill
 * in as their underlying features ship (multi-location, inventory, commissions,
 * forms). Active tab is driven by `?tab=` so deep links work.
 *
 * The hero strip (name + code chip + status + tags + price + duration) stays
 * pinned to the top of the main scroll area while tab content scrolls underneath.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import {
  Box,
  Calendar,
  CalendarClock,
  Check,
  ClipboardCheck,
  ClipboardCopy,
  DollarSign,
  FileText,
  Image as ImageIcon,
  Loader2,
  MapPin,
  Receipt,
  Settings2,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { use, useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { PageHeader } from '@/components/page-header';
import { StatusBadge } from '@/components/status-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
  type Service,
  centsFromDollars,
  dollarsFromCents,
  useDeleteServicePhoto,
  useService,
  useServiceCategories,
  useUpdateService,
  useUploadServicePhoto,
} from '@/lib/services';
import { cn } from '@/lib/utils';

import { ProtocolTab } from './_tabs/protocol-tab';

// ── Tab definitions ──────────────────────────────────────────────────────

type TabDef = { id: string; label: string; comingPhase?: string };

const TABS: readonly TabDef[] = [
  { id: 'general', label: 'General' },
  { id: 'protocol', label: 'Protocol' },
  { id: 'locations', label: 'Locations', comingPhase: 'Phase 4E · Multi-location' },
  { id: 'inventory', label: 'Inventory', comingPhase: 'Phase 4C · Inventory' },
  { id: 'commissions', label: 'Commissions', comingPhase: 'Phase 2F · Commissions' },
  { id: 'forms', label: 'Forms', comingPhase: 'Phase 1D · Forms' },
];

const TAB_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  general: Settings2,
  protocol: ClipboardCheck,
  locations: MapPin,
  inventory: Box,
  commissions: Receipt,
  forms: FileText,
};

// ── Page ─────────────────────────────────────────────────────────────────

export default function ServiceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const serviceId = Number(id);
  const { data: service, isLoading, error } = useService(serviceId);

  const searchParams = useSearchParams();
  const requestedTab = searchParams.get('tab') ?? 'general';
  const activeTab = TABS.find((t) => t.id === requestedTab) ?? TABS[0];

  if (isLoading) {
    return <div className="px-10 py-10 text-sm text-muted-foreground">Loading service…</div>;
  }
  if (error || !service) {
    return (
      <div className="px-10 py-10">
        <PageHeader title="Service not found" back={{ href: '/catalog/services', label: 'All services' }} />
        <p className="text-sm text-destructive">Failed to load this service.</p>
      </div>
    );
  }

  return (
    <div>
      {/* Back link — scrolls away */}
      <div className="max-w-7xl px-10 pt-10">
        <PageHeader
          title=""
          back={{
            href: service.category
              ? `/catalog/services?category=${service.category.id}`
              : '/catalog/services',
            label: service.category ? `Back to ${service.category.name}` : 'All services',
          }}
          className="mb-0"
        />
      </div>

      {/* Sticky band: hero + code chip + tabs */}
      <div className="sticky top-0 z-10 mt-4 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="max-w-7xl px-10 pt-2">
          <Hero service={service} />
          <CodeChip code={service.code} />
          <TabsNav active={activeTab.id} />
        </div>
      </div>

      {/* Tab content */}
      <div className="max-w-7xl px-10 mt-8 pb-10">
        {activeTab.id === 'general' ? (
          <GeneralTab service={service} />
        ) : activeTab.id === 'protocol' ? (
          <ProtocolTab serviceId={service.id} />
        ) : (
          <ComingSoonTab tab={activeTab} />
        )}
      </div>
    </div>
  );
}

// ── Hero ─────────────────────────────────────────────────────────────────

function Hero({ service }: { service: Service }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0 flex-1">
        <h1 className="font-serif text-3xl font-semibold tracking-tight">{service.name}</h1>
        <div className="flex flex-wrap items-center gap-3 mt-3 text-sm">
          <StatusBadge tone={service.is_active ? 'success' : 'neutral'}>
            {service.is_active ? 'active' : 'inactive'}
          </StatusBadge>
          {service.category ? (
            <Badge
              variant="outline"
              style={{ borderColor: `${service.category.color}66`, color: service.category.color }}
              className="font-normal"
            >
              {service.category.name}
            </Badge>
          ) : null}
          {service.service_type === 'addon' ? (
            <Badge variant="outline" className="font-normal">
              Add-on
            </Badge>
          ) : null}
          {!service.is_bookable_online ? (
            <span className="text-xs text-muted-foreground uppercase tracking-wide">
              Phone only
            </span>
          ) : null}
        </div>
      </div>
      <div className="text-right shrink-0">
        <p className="font-mono text-3xl font-medium tracking-tight">{service.price_dollars}</p>
        <p className="text-xs text-muted-foreground tabular-nums mt-1">
          {service.duration_minutes}m
          {service.buffer_minutes > 0 ? ` (+${service.buffer_minutes} buffer)` : ''}
        </p>
      </div>
    </div>
  );
}

// ── Code chip ────────────────────────────────────────────────────────────

function CodeChip({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success('Code copied');
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error('Could not copy to clipboard');
    }
  };

  return (
    <div className="mt-4 inline-flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-1.5 text-sm">
      <span className="text-muted-foreground text-xs uppercase tracking-wide">Code</span>
      <code className="font-mono font-medium tracking-wider">{code || '—'}</code>
      {code ? (
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Copy code"
          title="Copy"
        >
          {copied ? <Check className="size-3.5" /> : <ClipboardCopy className="size-3.5" />}
        </button>
      ) : null}
    </div>
  );
}

// ── Tabs nav ─────────────────────────────────────────────────────────────

function TabsNav({ active }: { active: string }) {
  const pathname = usePathname();
  return (
    <div className="mt-5 -mx-2 overflow-x-auto">
      <nav className="flex min-w-max border-b" role="tablist">
        {TABS.map((tab) => {
          const Icon = TAB_ICONS[tab.id] ?? Settings2;
          const isActive = active === tab.id;
          return (
            <Link
              key={tab.id}
              href={`${pathname}?tab=${tab.id}`}
              scroll={false}
              role="tab"
              aria-selected={isActive}
              className={cn(
                'inline-flex items-center gap-2 px-3 py-2.5 text-sm whitespace-nowrap border-b-2 -mb-px transition-colors',
                isActive
                  ? 'border-accent text-foreground font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30',
              )}
            >
              <Icon className="size-3.5" />
              {tab.label}
              {tab.comingPhase ? (
                <span className="size-1.5 rounded-full bg-muted-foreground/30" aria-label="coming soon" />
              ) : null}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

// ── General tab (editable form) ──────────────────────────────────────────

const generalSchema = z.object({
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

type GeneralFormValues = z.infer<typeof generalSchema>;

function serviceToGeneralValues(s: Service): GeneralFormValues {
  return {
    name: s.name,
    code: s.code,
    description: s.description,
    service_type: s.service_type,
    category_id: s.category ? String(s.category.id) : '',
    duration_minutes: s.duration_minutes,
    buffer_minutes: s.buffer_minutes,
    price_dollars: dollarsFromCents(s.price_cents),
    tax_rate_percent: s.tax_rate_percent ?? '0',
    is_bookable_online: s.is_bookable_online,
    is_active: s.is_active,
  };
}

function GeneralTab({ service }: { service: Service }) {
  const update = useUpdateService(service.id);
  const { data: categories } = useServiceCategories();

  const form = useForm<GeneralFormValues>({
    resolver: zodResolver(generalSchema),
    defaultValues: serviceToGeneralValues(service),
  });
  const watched = form.watch();

  useEffect(() => {
    form.reset(serviceToGeneralValues(service));
  }, [service, form]);

  const onSubmit = (values: GeneralFormValues) => {
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
    update.mutate(payload, {
      onSuccess: (updated) => {
        toast.success('Service saved');
        form.reset(serviceToGeneralValues(updated));
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
          const fieldErrors = err.body as Record<string, string[] | string>;
          for (const [field, msgs] of Object.entries(fieldErrors)) {
            const message = Array.isArray(msgs) ? msgs[0] : String(msgs);
            if (field in form.getValues()) {
              form.setError(field as keyof GeneralFormValues, { message });
            }
          }
          toast.error('Please fix the highlighted fields.');
        } else {
          toast.error('Save failed. Please try again.');
        }
      },
    });
  };

  const isDirty = form.formState.isDirty;

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-10">
          <Section
            title="Basics"
            description="The core identity of this service — what shows up on invoices, the calendar, and the booking page."
            icon={<Sparkles className="size-4" />}
          >
            <Field data-invalid={form.formState.errors.name ? true : undefined}>
              <FieldLabel htmlFor="name">Service name</FieldLabel>
              <Input id="name" {...form.register('name')} />
              {form.formState.errors.name ? (
                <FieldError>{form.formState.errors.name.message}</FieldError>
              ) : null}
            </Field>

            <Field data-invalid={form.formState.errors.code ? true : undefined}>
              <FieldLabel htmlFor="code">Code (SKU)</FieldLabel>
              <Input id="code" className="font-mono w-40" {...form.register('code')} />
              <p className="text-xs text-muted-foreground mt-1">
                Short identifier shown on invoices, reports, and inventory. Auto-generated from
                the name; edit to use your own SKU. Unique within your spa.
              </p>
              {form.formState.errors.code ? (
                <FieldError>{form.formState.errors.code.message}</FieldError>
              ) : null}
            </Field>

            <Field>
              <FieldLabel htmlFor="description">Description</FieldLabel>
              <textarea
                id="description"
                rows={3}
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
                    form.setValue('service_type', v as GeneralFormValues['service_type'], {
                      shouldDirty: true,
                    })
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
              </Field>
            </div>
          </Section>

          <HeroPhotoSection service={service} />

          <Section
            title="Duration"
            description="How long this service blocks the calendar, plus optional cleanup / setup time held off the bookable schedule."
            icon={<CalendarClock className="size-4" />}
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field data-invalid={form.formState.errors.duration_minutes ? true : undefined}>
                <FieldLabel htmlFor="duration_minutes">Service time (minutes)</FieldLabel>
                <Input
                  id="duration_minutes"
                  type="number"
                  min={1}
                  {...form.register('duration_minutes', { valueAsNumber: true })}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  How long this service blocks the calendar when booked.
                </p>
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

          <Section
            title="Pricing"
            description="Default price and tax rate. Both can be overridden per-line on an invoice for one-off discounts or comp visits."
            icon={<DollarSign className="size-4" />}
          >
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
                  Applied at invoice time. Examples: 8.875 (NYC), 0 (most medical services in
                  many states). Up to 3 decimal places.
                </p>
                {form.formState.errors.tax_rate_percent ? (
                  <FieldError>{form.formState.errors.tax_rate_percent.message}</FieldError>
                ) : null}
              </Field>
            </div>
          </Section>

          <Section
            title="Booking"
            description="Where this service is bookable from and whether it's currently available."
            icon={<Calendar className="size-4" />}
          >
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

        <aside className="lg:sticky lg:top-72 self-start">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium uppercase tracking-wide">
                Live preview
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <h3 className="font-serif text-xl font-semibold tracking-tight">
                {watched.name || 'Untitled service'}
              </h3>
              {watched.code ? (
                <p className="font-mono text-xs text-muted-foreground tracking-wider">
                  {watched.code}
                </p>
              ) : null}
              <div className="flex items-center gap-2 text-sm">
                <span className="font-mono text-2xl font-medium tracking-tight">
                  ${Number(watched.price_dollars || 0).toFixed(2)}
                </span>
                <span className="text-muted-foreground">·</span>
                <span className="text-muted-foreground tabular-nums">
                  {(Number(watched.duration_minutes) || 0) + (Number(watched.buffer_minutes) || 0)}m
                </span>
              </div>
              {Number(watched.tax_rate_percent || 0) > 0 ? (
                <p className="text-xs text-muted-foreground">
                  + {Number(watched.tax_rate_percent).toFixed(3)}% tax
                </p>
              ) : null}
              {watched.description ? (
                <p className="text-sm text-muted-foreground line-clamp-3 whitespace-pre-wrap">
                  {watched.description}
                </p>
              ) : null}
            </CardContent>
          </Card>
        </aside>
      </div>

      {/* Sticky save bar */}
      <div className="sticky bottom-0 -mx-10 mt-10 px-10 py-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="flex items-center justify-between gap-2 max-w-7xl mx-auto">
          <p className="text-xs text-muted-foreground">
            {isDirty ? 'Unsaved changes' : 'No changes'}
          </p>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!isDirty || update.isPending}
              onClick={() => form.reset(serviceToGeneralValues(service))}
            >
              Discard
            </Button>
            <Button type="submit" disabled={!isDirty || update.isPending}>
              {update.isPending ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}

// ── ComingSoon tab ───────────────────────────────────────────────────────

function ComingSoonTab({ tab }: { tab: TabDef }) {
  const Icon = TAB_ICONS[tab.id] ?? Settings2;
  const summary = TAB_SUMMARIES[tab.id] ?? '';
  return (
    <Card className="border-dashed">
      <CardContent className="py-16 text-center">
        <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground mb-4">
          <Icon className="size-5" />
        </div>
        <h3 className="font-serif text-xl font-semibold tracking-tight">{tab.label}</h3>
        <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto">{summary}</p>
        <p className="text-xs text-muted-foreground mt-4 uppercase tracking-wide">
          Coming with {tab.comingPhase}
        </p>
      </CardContent>
    </Card>
  );
}

const TAB_SUMMARIES: Record<string, string> = {
  locations:
    'Pick which locations offer this service. Once multi-location lands, providers, calendars, and ' +
    'inventory get scoped per-location.',
  inventory:
    'Track which products this service consumes — Botox vials, filler syringes, retail items — so ' +
    'inventory drops automatically each time the service is performed.',
  commissions:
    'Configure commission percentages per role or per individual staff. Used by the commission tracker ' +
    'and payroll exports to compute earned amounts when this service is paid for.',
  forms:
    'Attach one or more consent forms, intake forms, or treatment notes that are auto-assigned to the ' +
    "client when this service is booked. Custom forms are built on the tenant's form templates.",
};

// ── Local helpers ────────────────────────────────────────────────────────

function Section({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-5 pb-3 border-b">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">{icon}</span>
          <h2 className="font-serif text-base font-semibold tracking-tight text-foreground">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
            {description}
          </p>
        ) : null}
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

// ── Hero photo section ───────────────────────────────────────────────────
//
// Self-contained: owns its own file input + mutations. Lives outside
// the React Hook Form because uploads are multipart and happen
// immediately on file selection — no Save button required.

const HERO_PHOTO_MAX_BYTES = 5 * 1024 * 1024;

function HeroPhotoSection({ service }: { service: Service }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useUploadServicePhoto(service.id);
  const remove = useDeleteServicePhoto(service.id);
  const busy = upload.isPending || remove.isPending;
  const photoUrl = service.hero_photo_url;

  const onPick = () => inputRef.current?.click();

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // allow re-selecting the same file later
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      toast.error('Please choose an image file (JPG, PNG, WebP).');
      return;
    }
    if (file.size > HERO_PHOTO_MAX_BYTES) {
      toast.error('Photo must be 5 MB or smaller.');
      return;
    }
    upload.mutate(file, {
      onSuccess: () => toast.success('Photo updated'),
      onError: (err) => {
        if (err instanceof ApiError && err.body && typeof err.body === 'object') {
          const body = err.body as Record<string, unknown>;
          const detail = body.photo ?? body.detail;
          toast.error(typeof detail === 'string' ? detail : 'Upload failed. Please try again.');
        } else {
          toast.error('Upload failed. Please try again.');
        }
      },
    });
  };

  const onRemove = () => {
    if (!photoUrl) return;
    remove.mutate(undefined, {
      onSuccess: () => toast.success('Photo removed'),
      onError: () => toast.error('Could not remove the photo. Please try again.'),
    });
  };

  return (
    <Section
      title="Hero photo"
      description="Optional image shown at the top of this service's card on your public booking page. Use a clean, high-quality photo (1200×750 or similar). Up to 5 MB."
      icon={<ImageIcon className="size-4" />}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={onFile}
      />
      {photoUrl ? (
        <div className="space-y-3">
          <div className="relative aspect-[16/10] w-full max-w-md overflow-hidden rounded-lg border bg-muted/30">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={photoUrl}
              alt=""
              className={cn(
                'absolute inset-0 size-full object-cover transition-opacity',
                busy && 'opacity-40',
              )}
            />
            {busy ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <Loader2 className="size-5 animate-spin text-foreground/70" />
              </div>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onPick} disabled={busy}>
              <Upload className="size-3.5" />
              Replace
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onRemove}
              disabled={busy}
              className="text-destructive hover:text-destructive"
            >
              <Trash2 className="size-3.5" />
              Remove
            </Button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={onPick}
          disabled={busy}
          className={cn(
            'group flex aspect-[16/10] w-full max-w-md flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed bg-muted/20 text-muted-foreground transition-colors',
            'hover:border-foreground/30 hover:bg-muted/40 hover:text-foreground',
            'disabled:opacity-60 disabled:cursor-not-allowed',
          )}
        >
          {busy ? (
            <Loader2 className="size-6 animate-spin" />
          ) : (
            <Upload className="size-6" />
          )}
          <span className="text-sm font-medium">
            {busy ? 'Uploading…' : 'Upload a photo'}
          </span>
          <span className="text-xs">JPG, PNG, or WebP · up to 5 MB</span>
        </button>
      )}
    </Section>
  );
}
