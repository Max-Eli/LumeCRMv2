/**
 * `<PackageForm>` — shared form body for creating + editing a
 * catalog `Package` row. Holds:
 *
 *   - Basics: name, sku, description, validity, active
 *   - Pricing: price + tax rate
 *   - Items editor: variable-length list of `{service, quantity}`
 *     rows with add/remove
 *   - Live preview side card showing a-la-carte total + implicit
 *     discount as the operator edits
 *
 * Rendered by both `/catalog/packages/new` and
 * `/catalog/packages/[id]`. Submit handlers are passed in so the
 * caller can wire to `useCreatePackage` / `useUpdatePackage`.
 */

'use client';

import {
  DollarSign,
  Layers,
  ListChecks,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

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
import { centsFromDollars } from '@/lib/packages';
import { useServices } from '@/lib/services';
import { cn } from '@/lib/utils';

// ── Types ───────────────────────────────────────────────────────────

export interface PackageFormItemRow {
  service_id: string;
  quantity: string;
}

export interface PackageFormValues {
  name: string;
  sku: string;
  description: string;
  price_dollars: string;
  tax_rate_percent: string;
  validity_days: string;
  is_active: boolean;
  items: PackageFormItemRow[];
}

export interface PackageFormErrors {
  name?: string;
  sku?: string;
  price_dollars?: string;
  tax_rate_percent?: string;
  validity_days?: string;
  items?: string;
}

interface PackageFormProps {
  values: PackageFormValues;
  setValues: (next: PackageFormValues) => void;
  errors: PackageFormErrors;
  onSubmit: () => void;
  isPending: boolean;
  submitLabel: string;
  cancelHref: string;
  /** Optional surface above the items editor (e.g. metadata, audit). */
  topSlot?: ReactNode;
  /** Optional surface below the form, before the sticky action bar. */
  bottomSlot?: ReactNode;
}

// ── Component ───────────────────────────────────────────────────────

export function PackageForm({
  values,
  setValues,
  errors,
  onSubmit,
  isPending,
  submitLabel,
  cancelHref,
  topSlot,
  bottomSlot,
}: PackageFormProps) {
  const { data: services } = useServices({ activeOnly: true });
  const serviceList = services ?? [];

  // Derived values for the live preview card.
  const priceCents = centsFromDollars(values.price_dollars || '0');
  const aLaCarteCents = values.items.reduce((sum, row) => {
    const svc = serviceList.find((s) => String(s.id) === row.service_id);
    if (!svc) return sum;
    const qty = Number(row.quantity) || 0;
    return sum + svc.price_cents * qty;
  }, 0);
  const implicitDiscountCents = aLaCarteCents - priceCents;

  const update = (patch: Partial<PackageFormValues>) =>
    setValues({ ...values, ...patch });

  const updateItem = (index: number, patch: Partial<PackageFormItemRow>) => {
    const next = values.items.map((row, i) =>
      i === index ? { ...row, ...patch } : row,
    );
    update({ items: next });
  };

  const addItemRow = () =>
    update({
      items: [...values.items, { service_id: '', quantity: '1' }],
    });

  const removeItemRow = (index: number) =>
    update({ items: values.items.filter((_, i) => i !== index) });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <form onSubmit={handleSubmit} noValidate>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-10">
          {topSlot}

          <Section title="Basics" icon={<Sparkles className="size-4" />}>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field
                className="md:col-span-2"
                data-invalid={errors.name ? true : undefined}
              >
                <FieldLabel htmlFor="name">Package name</FieldLabel>
                <Input
                  id="name"
                  autoFocus
                  placeholder="e.g. 5 Facial Pack"
                  value={values.name}
                  onChange={(e) => update({ name: e.target.value })}
                />
                {errors.name ? <FieldError>{errors.name}</FieldError> : null}
              </Field>
              <Field data-invalid={errors.sku ? true : undefined}>
                <FieldLabel htmlFor="sku">
                  SKU
                  <span className="text-muted-foreground/70 font-normal ml-1">
                    (auto if blank)
                  </span>
                </FieldLabel>
                <Input
                  id="sku"
                  placeholder="Auto"
                  className="font-mono"
                  value={values.sku}
                  onChange={(e) => update({ sku: e.target.value })}
                />
                {errors.sku ? <FieldError>{errors.sku}</FieldError> : null}
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor="description">Description</FieldLabel>
              <textarea
                id="description"
                rows={3}
                placeholder="Optional internal notes — what's included, how to pitch it."
                className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                value={values.description}
                onChange={(e) => update({ description: e.target.value })}
              />
            </Field>
          </Section>

          <Section title="Pricing" icon={<DollarSign className="size-4" />}>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field
                data-invalid={errors.price_dollars ? true : undefined}
              >
                <FieldLabel htmlFor="price_dollars">Package price</FieldLabel>
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
                    value={values.price_dollars}
                    onChange={(e) => update({ price_dollars: e.target.value })}
                  />
                </div>
                {errors.price_dollars ? (
                  <FieldError>{errors.price_dollars}</FieldError>
                ) : null}
              </Field>
              <Field
                data-invalid={errors.tax_rate_percent ? true : undefined}
              >
                <FieldLabel htmlFor="tax_rate_percent">Tax rate</FieldLabel>
                <div className="relative">
                  <Input
                    id="tax_rate_percent"
                    type="text"
                    inputMode="decimal"
                    placeholder="0.000"
                    className="pr-7"
                    value={values.tax_rate_percent}
                    onChange={(e) =>
                      update({ tax_rate_percent: e.target.value })
                    }
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                    %
                  </span>
                </div>
              </Field>
              <Field data-invalid={errors.validity_days ? true : undefined}>
                <FieldLabel htmlFor="validity_days">
                  Validity
                  <span className="text-muted-foreground/70 font-normal ml-1">
                    (days)
                  </span>
                </FieldLabel>
                <Input
                  id="validity_days"
                  type="text"
                  inputMode="numeric"
                  placeholder="365 or blank"
                  value={values.validity_days}
                  onChange={(e) => update({ validity_days: e.target.value })}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Blank = never expires.
                </p>
              </Field>
            </div>
          </Section>

          <Section title="Included services" icon={<ListChecks className="size-4" />}>
            <div className="space-y-2">
              {values.items.length === 0 ? (
                <p className="text-sm text-muted-foreground italic">
                  No services yet — add at least one below.
                </p>
              ) : (
                values.items.map((row, index) => (
                  <ItemRow
                    key={index}
                    row={row}
                    services={serviceList}
                    onChange={(patch) => updateItem(index, patch)}
                    onRemove={() => removeItemRow(index)}
                  />
                ))
              )}
              <Button
                type="button"
                variant="outline"
                onClick={addItemRow}
                className="mt-2"
              >
                <Plus className="size-4" />
                Add a service
              </Button>
              {errors.items ? (
                <p className="text-sm text-destructive mt-2">{errors.items}</p>
              ) : null}
            </div>
          </Section>

          <Section title="Status" icon={<Layers className="size-4" />}>
            <CheckboxRow
              id="is_active"
              label="Active"
              description="Inactive packages stay on past invoices but can't be sold on new ones."
              checked={values.is_active}
              onChange={(v) => update({ is_active: v })}
            />
          </Section>

          {bottomSlot}
        </div>

        <aside className="lg:sticky lg:top-10 self-start">
          <PreviewCard
            name={values.name}
            priceCents={priceCents}
            aLaCarteCents={aLaCarteCents}
            implicitDiscountCents={implicitDiscountCents}
            itemCount={values.items.length}
            totalCredits={values.items.reduce(
              (s, r) => s + (Number(r.quantity) || 0),
              0,
            )}
            validityDays={values.validity_days}
          />
        </aside>
      </div>

      <div className="sticky bottom-0 -mx-8 mt-10 px-8 py-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="flex items-center justify-end gap-2">
          <Button render={<Link href={cancelHref} />} nativeButton={false} variant="outline">
            Cancel
          </Button>
          <Button type="submit" disabled={isPending}>
            {isPending ? 'Saving…' : submitLabel}
          </Button>
        </div>
      </div>
    </form>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function ItemRow({
  row,
  services,
  onChange,
  onRemove,
}: {
  row: PackageFormItemRow;
  services: { id: number; name: string; price_cents: number; price_dollars: string }[];
  onChange: (patch: Partial<PackageFormItemRow>) => void;
  onRemove: () => void;
}) {
  const selectedService = services.find(
    (s) => String(s.id) === row.service_id,
  );
  return (
    <div className="grid grid-cols-12 gap-2 items-start">
      <div className="col-span-7">
        <Select
          value={row.service_id}
          onValueChange={(v) => onChange({ service_id: v ?? '' })}
        >
          <SelectTrigger>
            <SelectValue placeholder="Pick a service…" />
          </SelectTrigger>
          <SelectContent>
            {services.length === 0 ? (
              <div className="px-2 py-2 text-xs text-muted-foreground">
                No active services in the catalog.
              </div>
            ) : (
              services.map((svc) => (
                <SelectItem key={svc.id} value={String(svc.id)}>
                  <span className="flex items-center justify-between gap-3 w-full">
                    <span className="truncate">{svc.name}</span>
                    <span className="text-xs text-muted-foreground font-mono shrink-0">
                      {svc.price_dollars}
                    </span>
                  </span>
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-3">
        <div className="relative">
          <Input
            type="number"
            min={1}
            value={row.quantity}
            onChange={(e) => onChange({ quantity: e.target.value })}
            className="text-center font-mono"
            aria-label="Credits granted for this service"
            placeholder="1"
          />
        </div>
      </div>
      <div className="col-span-1 text-xs text-muted-foreground self-center font-mono">
        {selectedService && Number(row.quantity) > 0
          ? `$${(
              (selectedService.price_cents * Number(row.quantity)) /
              100
            ).toFixed(2)}`
          : '—'}
      </div>
      <div className="col-span-1">
        <button
          type="button"
          onClick={onRemove}
          className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive transition-colors"
          aria-label="Remove this item"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

function PreviewCard({
  name,
  priceCents,
  aLaCarteCents,
  implicitDiscountCents,
  itemCount,
  totalCredits,
  validityDays,
}: {
  name: string;
  priceCents: number;
  aLaCarteCents: number;
  implicitDiscountCents: number;
  itemCount: number;
  totalCredits: number;
  validityDays: string;
}) {
  const discountPct =
    aLaCarteCents > 0
      ? Math.round((implicitDiscountCents / aLaCarteCents) * 100)
      : 0;
  return (
    <div className="rounded-xl border bg-card p-6">
      <p className="text-xs uppercase tracking-wide text-muted-foreground mb-4">
        Live preview
      </p>
      <div className="flex items-start gap-3 mb-4">
        <div className="inline-flex size-10 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 shrink-0">
          <Layers className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-serif text-lg font-semibold tracking-tight truncate">
            {name || 'New package'}
          </h3>
          <p className="font-mono text-2xl font-medium tracking-tight mt-1">
            ${(priceCents / 100).toFixed(2)}
          </p>
        </div>
      </div>
      <dl className="space-y-2 text-sm pt-4 border-t">
        <Row
          label="A la carte total"
          value={`$${(aLaCarteCents / 100).toFixed(2)}`}
          mono
          muted
        />
        <Row
          label="Customer saves"
          value={
            implicitDiscountCents > 0
              ? `$${(implicitDiscountCents / 100).toFixed(2)} (${discountPct}%)`
              : implicitDiscountCents < 0
                ? `−$${Math.abs(implicitDiscountCents / 100).toFixed(2)}`
                : '—'
          }
          mono
          tone={
            implicitDiscountCents > 0
              ? 'positive'
              : implicitDiscountCents < 0
                ? 'negative'
                : 'neutral'
          }
        />
        <Row label="Services included" value={String(itemCount)} />
        <Row label="Total credits" value={String(totalCredits)} />
        <Row
          label="Expires"
          value={
            validityDays && Number(validityDays) > 0
              ? `${validityDays} days after purchase`
              : 'Never'
          }
          muted
        />
      </dl>
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
        <h2 className="text-sm font-medium uppercase tracking-wide text-foreground">
          {title}
        </h2>
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

function Row({
  label,
  value,
  mono,
  muted,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  muted?: boolean;
  tone?: 'positive' | 'negative' | 'neutral';
}) {
  return (
    <div className="flex items-baseline justify-between">
      <dt className={cn('text-muted-foreground', muted && 'text-muted-foreground/70')}>
        {label}
      </dt>
      <dd
        className={cn(
          'font-medium tabular-nums',
          mono && 'font-mono',
          tone === 'positive' && 'text-emerald-700',
          tone === 'negative' && 'text-red-700',
        )}
      >
        {value}
      </dd>
    </div>
  );
}

// ── Validation helper ───────────────────────────────────────────────

export function validatePackageForm(values: PackageFormValues): PackageFormErrors {
  const errors: PackageFormErrors = {};
  if (!values.name.trim()) errors.name = 'Name is required.';
  if (values.name.length > 200) errors.name = 'Max 200 characters.';
  if (values.sku.length > 30) errors.sku = 'Max 30 characters.';
  if (
    values.price_dollars !== ''
    && Number.isNaN(Number(values.price_dollars))
  ) {
    errors.price_dollars = 'Enter a number.';
  }
  if (
    values.tax_rate_percent !== ''
    && (Number.isNaN(Number(values.tax_rate_percent))
      || Number(values.tax_rate_percent) < 0
      || Number(values.tax_rate_percent) >= 100)
  ) {
    errors.tax_rate_percent = 'Tax rate must be 0–100.';
  }
  if (
    values.validity_days !== ''
    && (!/^\d+$/.test(values.validity_days)
      || Number(values.validity_days) < 0)
  ) {
    errors.validity_days = 'Enter a whole number of days, or leave blank.';
  }
  if (values.items.length === 0) {
    errors.items = 'A package needs at least one service.';
  } else {
    for (const row of values.items) {
      if (!row.service_id) {
        errors.items = 'Pick a service for every row.';
        break;
      }
      if (!row.quantity || Number(row.quantity) < 1) {
        errors.items = 'Quantity must be at least 1 for every row.';
        break;
      }
    }
    if (!errors.items) {
      const seen = new Set<string>();
      for (const row of values.items) {
        if (seen.has(row.service_id)) {
          errors.items = 'Each service can only appear once per package.';
          break;
        }
        seen.add(row.service_id);
      }
    }
  }
  return errors;
}

// ── Payload helper ──────────────────────────────────────────────────

export function packageFormToPayload(values: PackageFormValues) {
  return {
    name: values.name.trim(),
    sku: values.sku.trim(),
    description: values.description,
    price_cents: centsFromDollars(values.price_dollars || '0'),
    tax_rate_percent: values.tax_rate_percent || '0',
    validity_days:
      values.validity_days && Number(values.validity_days) > 0
        ? Number(values.validity_days)
        : null,
    is_active: values.is_active,
    items_input: values.items.map((row, i) => ({
      service_id: Number(row.service_id),
      quantity: Number(row.quantity || '1'),
      sort_order: i,
    })),
  };
}
