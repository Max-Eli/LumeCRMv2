/**
 * `<MembershipPlanForm>` — shared form body for creating + editing
 * a `MembershipPlan` row. Mirrors `PackageForm` but adds the
 * billing-interval picker + member-discount field.
 */

'use client';

import {
  CreditCard,
  DollarSign,
  ListChecks,
  Plus,
  Repeat,
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
import { useServiceCategories, useServices } from '@/lib/services';
import { type BillingInterval, centsFromDollars } from '@/lib/subscriptions';
import { cn } from '@/lib/utils';

/** One inclusion line on the plan — either a single service or a
 *  whole service category. `item_type` discriminates; only the
 *  matching id is meaningful. */
export interface PlanFormItemRow {
  item_type: 'service' | 'category';
  service_id: string;
  category_id: string;
  quantity_per_cycle: string;
}

/** A fresh, empty line row — defaults to a single-service line. */
export function emptyPlanItemRow(): PlanFormItemRow {
  return {
    item_type: 'service',
    service_id: '',
    category_id: '',
    quantity_per_cycle: '1',
  };
}

export interface PlanFormValues {
  name: string;
  sku: string;
  description: string;
  price_dollars: string;
  tax_rate_percent: string;
  billing_interval: BillingInterval;
  member_discount_percent: string;
  is_active: boolean;
  items: PlanFormItemRow[];
}

export interface PlanFormErrors {
  name?: string;
  sku?: string;
  price_dollars?: string;
  tax_rate_percent?: string;
  member_discount_percent?: string;
  items?: string;
}

interface PlanFormProps {
  values: PlanFormValues;
  setValues: (next: PlanFormValues) => void;
  errors: PlanFormErrors;
  onSubmit: () => void;
  isPending: boolean;
  submitLabel: string;
  cancelHref: string;
  topSlot?: ReactNode;
  bottomSlot?: ReactNode;
}

export function MembershipPlanForm({
  values,
  setValues,
  errors,
  onSubmit,
  isPending,
  submitLabel,
  cancelHref,
  topSlot,
  bottomSlot,
}: PlanFormProps) {
  const { data: services } = useServices({ activeOnly: true });
  const { data: categories } = useServiceCategories();
  const serviceList = services ?? [];
  const categoryList = categories ?? [];

  // A category line has no single price — value it at the average
  // a-la-carte price of the active services in it (mirrors the
  // backend's `get_a_la_carte_total_cents`).
  const categoryAvgCents = (categoryId: string): number => {
    const inCat = serviceList.filter(
      (s) => s.category && String(s.category.id) === categoryId,
    );
    if (inCat.length === 0) return 0;
    return Math.round(
      inCat.reduce((a, s) => a + s.price_cents, 0) / inCat.length,
    );
  };

  const lineValueCents = (row: PlanFormItemRow): number => {
    const qty = Number(row.quantity_per_cycle) || 0;
    if (qty <= 0) return 0;
    if (row.item_type === 'category') {
      return categoryAvgCents(row.category_id) * qty;
    }
    const svc = serviceList.find((s) => String(s.id) === row.service_id);
    return svc ? svc.price_cents * qty : 0;
  };

  const priceCents = centsFromDollars(values.price_dollars || '0');
  const aLaCarteCents = values.items.reduce(
    (sum, row) => sum + lineValueCents(row),
    0,
  );
  const implicitDiscountCents = aLaCarteCents - priceCents;

  const update = (patch: Partial<PlanFormValues>) =>
    setValues({ ...values, ...patch });

  const updateItem = (index: number, patch: Partial<PlanFormItemRow>) => {
    const next = values.items.map((row, i) =>
      i === index ? { ...row, ...patch } : row,
    );
    update({ items: next });
  };

  const addItemRow = () =>
    update({ items: [...values.items, emptyPlanItemRow()] });

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
                <FieldLabel htmlFor="name">Plan name</FieldLabel>
                <Input
                  id="name"
                  autoFocus
                  placeholder="e.g. Glow Club"
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
                placeholder="Optional internal notes — what's the pitch."
                className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                value={values.description}
                onChange={(e) => update({ description: e.target.value })}
              />
            </Field>
          </Section>

          <Section
            title="Billing + pricing"
            icon={<DollarSign className="size-4" />}
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field data-invalid={errors.price_dollars ? true : undefined}>
                <FieldLabel htmlFor="price_dollars">Price per cycle</FieldLabel>
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
              <Field>
                <FieldLabel htmlFor="billing_interval">
                  Billing cycle
                </FieldLabel>
                <Select
                  value={values.billing_interval}
                  onValueChange={(v) =>
                    update({
                      billing_interval: ((v ?? 'monthly') as BillingInterval),
                    })
                  }
                >
                  <SelectTrigger id="billing_interval">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="monthly">Monthly</SelectItem>
                    <SelectItem value="annual">Annual</SelectItem>
                  </SelectContent>
                </Select>
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
            </div>

            <Field
              data-invalid={errors.member_discount_percent ? true : undefined}
            >
              <FieldLabel htmlFor="member_discount_percent">
                Member discount on a-la-carte services
                <span className="text-muted-foreground/70 font-normal ml-1">
                  (optional)
                </span>
              </FieldLabel>
              <div className="relative w-32">
                <Input
                  id="member_discount_percent"
                  type="text"
                  inputMode="decimal"
                  placeholder="0"
                  className="pr-7"
                  value={values.member_discount_percent}
                  onChange={(e) =>
                    update({ member_discount_percent: e.target.value })
                  }
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                  %
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                Stored on the plan as the member rate. v1 doesn&rsquo;t
                auto-apply this at invoice time &mdash; operator overrides
                line price manually for member discounts. Auto-apply lights
                up when payment processing is wired in Phase 2A.
              </p>
              {errors.member_discount_percent ? (
                <FieldError>{errors.member_discount_percent}</FieldError>
              ) : null}
            </Field>
          </Section>

          <Section
            title="Included credits"
            icon={<ListChecks className="size-4" />}
          >
            <p className="text-xs text-muted-foreground -mt-2 mb-3 leading-relaxed">
              How many credits the customer gets each billing cycle. v1
              is use-it-or-lose-it &mdash; unredeemed credits don&rsquo;t
              roll forward. A <strong>category</strong> credit can be
              redeemed against any service in that category, at that
              service&rsquo;s full price.
            </p>
            <div className="space-y-2">
              {values.items.length === 0 ? (
                <p className="text-sm text-muted-foreground italic">
                  No credits yet — add at least one below.
                </p>
              ) : (
                values.items.map((row, index) => (
                  <ItemRow
                    key={index}
                    row={row}
                    services={serviceList}
                    categories={categoryList}
                    lineValueCents={lineValueCents(row)}
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
                Add a credit
              </Button>
              {errors.items ? (
                <p className="text-sm text-destructive mt-2">{errors.items}</p>
              ) : null}
            </div>
          </Section>

          <Section title="Status" icon={<CreditCard className="size-4" />}>
            <CheckboxRow
              id="is_active"
              label="Active"
              description="Inactive plans stay on past subscriptions but can't be sold on new invoices."
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
            billingInterval={values.billing_interval}
            aLaCarteCents={aLaCarteCents}
            implicitDiscountCents={implicitDiscountCents}
            itemCount={values.items.length}
            hasCategoryLine={values.items.some(
              (r) => r.item_type === 'category',
            )}
            totalCredits={values.items.reduce(
              (s, r) => s + (Number(r.quantity_per_cycle) || 0),
              0,
            )}
            memberDiscountPercent={values.member_discount_percent}
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
  categories,
  lineValueCents,
  onChange,
  onRemove,
}: {
  row: PlanFormItemRow;
  services: {
    id: number;
    name: string;
    price_cents: number;
    price_dollars: string;
    category: { id: number } | null;
  }[];
  categories: { id: number; name: string; service_count: number }[];
  lineValueCents: number;
  onChange: (patch: Partial<PlanFormItemRow>) => void;
  onRemove: () => void;
}) {
  const isCategory = row.item_type === 'category';
  const hasValue =
    Number(row.quantity_per_cycle) > 0
    && (isCategory ? !!row.category_id : !!row.service_id)
    && lineValueCents > 0;

  return (
    <div className="grid grid-cols-12 gap-2 items-start">
      <div className="col-span-3">
        <Select
          value={row.item_type}
          onValueChange={(v) =>
            onChange({
              item_type: (v as 'service' | 'category') ?? 'service',
              // Clear both ids — switching kind invalidates the pick.
              service_id: '',
              category_id: '',
            })
          }
        >
          <SelectTrigger aria-label="Credit type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="service">Service</SelectItem>
            <SelectItem value="category">Category</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-5">
        {isCategory ? (
          <Select
            value={row.category_id}
            onValueChange={(v) => onChange({ category_id: v ?? '' })}
          >
            <SelectTrigger>
              <SelectValue placeholder="Pick a category…" />
            </SelectTrigger>
            <SelectContent>
              {categories.length === 0 ? (
                <div className="px-2 py-2 text-xs text-muted-foreground">
                  No categories in the catalog.
                </div>
              ) : (
                categories.map((cat) => (
                  <SelectItem key={cat.id} value={String(cat.id)}>
                    <span className="flex items-center justify-between gap-3 w-full">
                      <span className="truncate">{cat.name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {cat.service_count} service
                        {cat.service_count === 1 ? '' : 's'}
                      </span>
                    </span>
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
        ) : (
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
        )}
      </div>
      <div className="col-span-2">
        <Input
          type="number"
          min={1}
          value={row.quantity_per_cycle}
          onChange={(e) => onChange({ quantity_per_cycle: e.target.value })}
          className="text-center font-mono"
          aria-label="Credits per billing cycle"
          placeholder="1"
        />
      </div>
      <div className="col-span-1 text-xs text-muted-foreground self-center font-mono">
        {hasValue
          ? `${isCategory ? '~' : ''}$${(lineValueCents / 100).toFixed(2)}`
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
  billingInterval,
  aLaCarteCents,
  implicitDiscountCents,
  itemCount,
  hasCategoryLine,
  totalCredits,
  memberDiscountPercent,
}: {
  name: string;
  priceCents: number;
  billingInterval: BillingInterval;
  aLaCarteCents: number;
  implicitDiscountCents: number;
  itemCount: number;
  hasCategoryLine: boolean;
  totalCredits: number;
  memberDiscountPercent: string;
}) {
  const discountPct =
    aLaCarteCents > 0
      ? Math.round((implicitDiscountCents / aLaCarteCents) * 100)
      : 0;
  // Category lines have no fixed price — their value is an average,
  // so any total that includes one is an estimate.
  const approx = hasCategoryLine ? '~' : '';
  return (
    <div className="rounded-xl border bg-card p-6">
      <p className="text-xs uppercase tracking-wide text-muted-foreground mb-4">
        Live preview
      </p>
      <div className="flex items-start gap-3 mb-4">
        <div className="inline-flex size-10 items-center justify-center rounded-md bg-violet-50 text-violet-700 shrink-0">
          <CreditCard className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-serif text-lg font-semibold tracking-tight truncate">
            {name || 'New plan'}
          </h3>
          <p className="font-mono text-2xl font-medium tracking-tight mt-1">
            ${(priceCents / 100).toFixed(2)}
            <span className="text-xs text-muted-foreground font-sans ml-1">
              / {billingInterval === 'annual' ? 'year' : 'month'}
            </span>
          </p>
        </div>
      </div>
      <dl className="space-y-2 text-sm pt-4 border-t">
        <Row
          label="A la carte / cycle"
          value={`${approx}$${(aLaCarteCents / 100).toFixed(2)}`}
          mono
          muted
        />
        <Row
          label="Customer saves"
          value={
            implicitDiscountCents > 0
              ? `${approx}$${(implicitDiscountCents / 100).toFixed(2)} (${approx}${discountPct}%)`
              : implicitDiscountCents < 0
                ? `−${approx}$${Math.abs(implicitDiscountCents / 100).toFixed(2)}`
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
        <Row label="Included lines" value={String(itemCount)} />
        <Row label="Credits / cycle" value={String(totalCredits)} />
        {memberDiscountPercent && Number(memberDiscountPercent) > 0 ? (
          <Row
            label="Member rate"
            value={`${memberDiscountPercent}% off`}
            tone="positive"
          />
        ) : null}
      </dl>
      <div className="mt-4 pt-4 border-t flex items-center gap-2 text-[11px] text-muted-foreground">
        <Repeat className="size-3.5" />
        <span>
          v1: manual renewal. Operator generates next cycle&rsquo;s
          invoice each {billingInterval === 'annual' ? 'year' : 'month'}.
        </span>
      </div>
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
      <dt
        className={cn(
          'text-muted-foreground',
          muted && 'text-muted-foreground/70',
        )}
      >
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

// ── Validation ──────────────────────────────────────────────────────

export function validatePlanForm(values: PlanFormValues): PlanFormErrors {
  const errors: PlanFormErrors = {};
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
    values.member_discount_percent !== ''
    && (Number.isNaN(Number(values.member_discount_percent))
      || Number(values.member_discount_percent) < 0
      || Number(values.member_discount_percent) > 100)
  ) {
    errors.member_discount_percent = 'Discount must be 0–100.';
  }
  if (values.items.length === 0) {
    errors.items = 'A plan needs at least one credit.';
  } else {
    for (const row of values.items) {
      const missing =
        row.item_type === 'category' ? !row.category_id : !row.service_id;
      if (missing) {
        errors.items = 'Pick a service or category for every row.';
        break;
      }
      if (!row.quantity_per_cycle || Number(row.quantity_per_cycle) < 1) {
        errors.items = 'Credits/cycle must be at least 1 for every row.';
        break;
      }
    }
    if (!errors.items) {
      const seen = new Set<string>();
      for (const row of values.items) {
        const key =
          row.item_type === 'category'
            ? `c:${row.category_id}`
            : `s:${row.service_id}`;
        if (seen.has(key)) {
          errors.items =
            'Each service or category can only appear once per plan.';
          break;
        }
        seen.add(key);
      }
    }
  }
  return errors;
}

export function planFormToPayload(values: PlanFormValues) {
  return {
    name: values.name.trim(),
    sku: values.sku.trim(),
    description: values.description,
    price_cents: centsFromDollars(values.price_dollars || '0'),
    tax_rate_percent: values.tax_rate_percent || '0',
    billing_interval: values.billing_interval,
    member_discount_percent: values.member_discount_percent || '0',
    is_active: values.is_active,
    items_input: values.items.map((row, i) => ({
      ...(row.item_type === 'category'
        ? { category_id: Number(row.category_id) }
        : { service_id: Number(row.service_id) }),
      quantity_per_cycle: Number(row.quantity_per_cycle || '1'),
      sort_order: i,
    })),
  };
}
