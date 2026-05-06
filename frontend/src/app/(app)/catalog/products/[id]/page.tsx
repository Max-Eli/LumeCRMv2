/**
 * `/catalog/products/[id]` — edit a retail product + adjust stock.
 *
 * Two-pane layout: edit form on the left (same shape as the new
 * page); a stock-adjustment + summary card on the right. The stock
 * card requires an operator note for every delta — that requirement
 * lives in the API serializer too, so a missing-note POST is a 400.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import {
  AlertCircle,
  Boxes,
  DollarSign,
  Loader2,
  Minus,
  Package as PackageIcon,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { use, useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { PageHeader } from '@/components/page-header';
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
import { useCurrentMembership } from '@/lib/auth';
import {
  type Product,
  centsFromDollars,
  dollarsFromCents,
  useAdjustProductStock,
  useDeleteProduct,
  useProduct,
  useProductCategories,
  useUpdateProduct,
} from '@/lib/products';
import { cn } from '@/lib/utils';

const schema = z.object({
  name: z.string().min(1, 'Name is required').max(200),
  sku: z.string().max(30),
  description: z.string(),
  category_id: z.string(),
  price_dollars: z
    .string()
    .refine((v) => v === '' || !Number.isNaN(Number(v)), 'Enter a number'),
  cost_dollars: z
    .string()
    .refine((v) => v === '' || !Number.isNaN(Number(v)), 'Enter a number'),
  tax_rate_percent: z
    .string()
    .refine((v) => v === '' || !Number.isNaN(Number(v)), 'Enter a number')
    .refine((v) => v === '' || Number(v) >= 0, 'Must be 0 or higher')
    .refine((v) => v === '' || Number(v) < 100, 'Must be below 100'),
  track_inventory: z.boolean(),
  low_stock_threshold: z
    .string()
    .refine(
      (v) => v === '' || /^\d+$/.test(v),
      'Enter zero or a positive whole number',
    ),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

function productToFormValues(p: Product): FormValues {
  return {
    name: p.name,
    sku: p.sku,
    description: p.description,
    category_id: p.category ? String(p.category.id) : '',
    price_dollars: dollarsFromCents(p.price_cents),
    cost_dollars: dollarsFromCents(p.cost_cents),
    tax_rate_percent: p.tax_rate_percent,
    track_inventory: p.track_inventory,
    low_stock_threshold: String(p.low_stock_threshold),
    is_active: p.is_active,
  };
}

export default function ProductDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const productId = Number(id);
  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner' || me?.role === 'manager';
  const router = useRouter();

  const { data: product, isLoading, error } = useProduct(productId);
  const { data: categories } = useProductCategories();
  const update = useUpdateProduct(productId);
  const remove = useDeleteProduct();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: product ? productToFormValues(product) : undefined,
  });
  const watched = form.watch();

  useEffect(() => {
    if (product) form.reset(productToFormValues(product));
  }, [product, form]);

  if (isLoading) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title=""
          back={{ href: '/catalog/products', label: 'All products' }}
        />
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading product…
        </div>
      </div>
    );
  }
  if (error || !product) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title="Product not found"
          back={{ href: '/catalog/products', label: 'All products' }}
        />
        <p className="text-sm text-destructive">Failed to load this product.</p>
      </div>
    );
  }

  const onSubmit = (values: FormValues) => {
    const payload = {
      name: values.name,
      sku: values.sku,
      description: values.description,
      category_id: values.category_id ? Number(values.category_id) : null,
      price_cents: centsFromDollars(values.price_dollars || '0'),
      cost_cents: centsFromDollars(values.cost_dollars || '0'),
      tax_rate_percent: values.tax_rate_percent || '0',
      track_inventory: values.track_inventory,
      low_stock_threshold: Number(values.low_stock_threshold || '0'),
      is_active: values.is_active,
    };
    update.mutate(payload, {
      onSuccess: (updated) => {
        toast.success('Product saved');
        form.reset(productToFormValues(updated));
      },
      onError: (err) => {
        if (
          err instanceof ApiError &&
          err.status === 400 &&
          typeof err.body === 'object' &&
          err.body
        ) {
          const fieldErrors = err.body as Record<string, string[] | string>;
          for (const [field, msgs] of Object.entries(fieldErrors)) {
            const message = Array.isArray(msgs) ? msgs[0] : String(msgs);
            form.setError(field as keyof FormValues, { message });
          }
          toast.error('Please fix the highlighted fields.');
        } else {
          toast.error('Save failed. Please try again.');
        }
      },
    });
  };

  const onDelete = () => {
    if (!confirm(`Delete "${product.name}"? This cannot be undone.`)) return;
    remove.mutate(productId, {
      onSuccess: () => {
        toast.success('Product deleted');
        router.push('/catalog/products');
      },
      onError: () => toast.error('Could not delete this product.'),
    });
  };

  const isDirty = form.formState.isDirty;

  return (
    <div className="px-8 py-8">
      <PageHeader
        title={product.name}
        description={`SKU ${product.sku || '—'}`}
        back={{ href: '/catalog/products', label: 'All products' }}
        actions={
          canEdit ? (
            <Button
              type="button"
              variant="outline"
              onClick={onDelete}
              disabled={remove.isPending}
            >
              <Trash2 className="size-4" />
              Delete
            </Button>
          ) : null
        }
      />

      <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="mt-2">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 space-y-10">
            <fieldset disabled={!canEdit} className="space-y-10 disabled:opacity-70">
              <Section title="Basics" icon={<Sparkles className="size-4" />}>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <Field
                    className="md:col-span-2"
                    data-invalid={form.formState.errors.name ? true : undefined}
                  >
                    <FieldLabel htmlFor="name">Product name</FieldLabel>
                    <Input id="name" {...form.register('name')} />
                    {form.formState.errors.name ? (
                      <FieldError>{form.formState.errors.name.message}</FieldError>
                    ) : null}
                  </Field>
                  <Field
                    data-invalid={form.formState.errors.sku ? true : undefined}
                  >
                    <FieldLabel htmlFor="sku">SKU</FieldLabel>
                    <Input
                      id="sku"
                      className="font-mono"
                      {...form.register('sku')}
                    />
                    {form.formState.errors.sku ? (
                      <FieldError>{form.formState.errors.sku.message}</FieldError>
                    ) : null}
                  </Field>
                </div>

                <Field>
                  <FieldLabel htmlFor="description">Description</FieldLabel>
                  <textarea
                    id="description"
                    rows={3}
                    className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    {...form.register('description')}
                  />
                </Field>

                <Field>
                  <FieldLabel htmlFor="category_id">Category</FieldLabel>
                  <Select
                    value={watched.category_id}
                    onValueChange={(v) =>
                      form.setValue('category_id', v ?? '', { shouldDirty: true })
                    }
                  >
                    <SelectTrigger id="category_id" className="w-full md:w-1/2">
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
              </Section>

              <Section title="Pricing" icon={<DollarSign className="size-4" />}>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <Field
                    data-invalid={
                      form.formState.errors.price_dollars ? true : undefined
                    }
                  >
                    <FieldLabel htmlFor="price_dollars">Sale price</FieldLabel>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                        $
                      </span>
                      <Input
                        id="price_dollars"
                        type="text"
                        inputMode="decimal"
                        className="pl-7"
                        {...form.register('price_dollars')}
                      />
                    </div>
                    {form.formState.errors.price_dollars ? (
                      <FieldError>
                        {form.formState.errors.price_dollars.message}
                      </FieldError>
                    ) : null}
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="cost_dollars">Wholesale cost</FieldLabel>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                        $
                      </span>
                      <Input
                        id="cost_dollars"
                        type="text"
                        inputMode="decimal"
                        className="pl-7"
                        {...form.register('cost_dollars')}
                      />
                    </div>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="tax_rate_percent">Tax rate</FieldLabel>
                    <div className="relative">
                      <Input
                        id="tax_rate_percent"
                        type="text"
                        inputMode="decimal"
                        className="pr-7"
                        {...form.register('tax_rate_percent')}
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                        %
                      </span>
                    </div>
                  </Field>
                </div>
              </Section>

              <Section title="Inventory" icon={<Boxes className="size-4" />}>
                <CheckboxRow
                  id="track_inventory"
                  label="Track inventory for this product"
                  description="Uncheck for items where stock count is meaningless."
                  checked={watched.track_inventory}
                  onChange={(v) =>
                    form.setValue('track_inventory', v, { shouldDirty: true })
                  }
                />
                {watched.track_inventory ? (
                  <Field>
                    <FieldLabel htmlFor="low_stock_threshold">
                      Low-stock warning at
                    </FieldLabel>
                    <Input
                      id="low_stock_threshold"
                      type="number"
                      min={0}
                      className="w-32"
                      {...form.register('low_stock_threshold')}
                    />
                    <p className="text-xs text-muted-foreground mt-1">
                      0 disables the warning. Adjust on-hand stock from the
                      panel on the right.
                    </p>
                  </Field>
                ) : null}
              </Section>

              <Section title="Status" icon={<PackageIcon className="size-4" />}>
                <CheckboxRow
                  id="is_active"
                  label="Active"
                  description="Inactive products stay in past invoices but cannot be added to new ones."
                  checked={watched.is_active}
                  onChange={(v) =>
                    form.setValue('is_active', v, { shouldDirty: true })
                  }
                />
              </Section>
            </fieldset>
          </div>

          <aside className="space-y-6">
            <SummaryCard product={product} />
            {canEdit && product.track_inventory ? (
              <StockAdjustCard productId={productId} current={product.stock_quantity} />
            ) : null}
          </aside>
        </div>

        {canEdit ? (
          <div className="sticky bottom-0 -mx-8 mt-10 px-8 py-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                {isDirty ? 'Unsaved changes' : 'No changes'}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={!isDirty || update.isPending}
                  onClick={() => form.reset(productToFormValues(product))}
                >
                  Discard
                </Button>
                <Button type="submit" disabled={!isDirty || update.isPending}>
                  {update.isPending ? 'Saving…' : 'Save changes'}
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </form>
    </div>
  );
}

// ── Side cards ──────────────────────────────────────────────────────

function SummaryCard({ product }: { product: Product }) {
  const marginCents = product.price_cents - product.cost_cents;
  const marginPct =
    product.price_cents > 0
      ? Math.round((marginCents / product.price_cents) * 100)
      : null;
  return (
    <div className="rounded-xl border bg-card p-6">
      <p className="text-xs uppercase tracking-wide text-muted-foreground mb-4">
        At a glance
      </p>
      <div className="flex items-start gap-3 mb-4">
        <div className="inline-flex size-10 items-center justify-center rounded-md bg-amber-50 text-amber-700 shrink-0">
          <PackageIcon className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-serif text-lg font-semibold tracking-tight truncate">
            {product.name}
          </h3>
          <p className="text-xs text-muted-foreground font-mono">{product.sku}</p>
        </div>
      </div>
      <dl className="space-y-2 text-sm">
        <Row label="Sale price" value={product.price_dollars} mono />
        {product.cost_cents > 0 ? (
          <>
            <Row
              label="Cost"
              value={`$${(product.cost_cents / 100).toFixed(2)}`}
              mono
              muted
            />
            <Row
              label="Margin"
              value={`$${(marginCents / 100).toFixed(2)}${
                marginPct !== null ? ` (${marginPct}%)` : ''
              }`}
              mono
              tone={marginCents > 0 ? 'positive' : 'neutral'}
            />
          </>
        ) : null}
        <Row
          label="Tax"
          value={
            Number(product.tax_rate_percent) > 0
              ? `${product.tax_rate_percent}%`
              : '—'
          }
          muted
        />
        {product.track_inventory ? (
          <Row
            label="On hand"
            value={product.stock_quantity.toLocaleString()}
            tone={
              product.stock_quantity < 0
                ? 'negative'
                : product.is_low_stock
                  ? 'warn'
                  : 'neutral'
            }
            mono
          />
        ) : (
          <Row label="Inventory" value="Not tracked" muted />
        )}
      </dl>
      {product.is_low_stock ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 flex items-start gap-2">
          <AlertCircle className="size-4 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-900 leading-relaxed">
            Stock at or below threshold ({product.low_stock_threshold}). Time
            to reorder.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function StockAdjustCard({
  productId,
  current,
}: {
  productId: number;
  current: number;
}) {
  const adjust = useAdjustProductStock(productId);
  const [delta, setDelta] = useState<string>('');
  const [note, setNote] = useState('');

  const deltaNum = Number(delta);
  const isValid = !Number.isNaN(deltaNum) && deltaNum !== 0 && note.trim().length > 0;
  const projected = !Number.isNaN(deltaNum) ? current + deltaNum : current;

  const onApply = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid) return;
    adjust.mutate(
      { delta: deltaNum, note: note.trim() },
      {
        onSuccess: () => {
          toast.success('Stock adjusted');
          setDelta('');
          setNote('');
        },
        onError: (err) => {
          const detail =
            err instanceof ApiError &&
            err.body &&
            typeof err.body === 'object'
              ? (err.body as { detail?: unknown }).detail
              : null;
          toast.error(
            typeof detail === 'string' ? detail : 'Could not adjust stock.',
          );
        },
      },
    );
  };

  return (
    <form onSubmit={onApply} className="rounded-xl border bg-card p-6 space-y-4">
      <div>
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          Adjust stock
        </p>
        <p className="text-xs text-muted-foreground/80 mt-1 leading-relaxed">
          Manual delta &mdash; receiving inventory, damage write-offs, count
          corrections. Note is required and lands in the audit log alongside
          before/after totals.
        </p>
      </div>

      <div className="flex items-center justify-center gap-2 py-2">
        <button
          type="button"
          onClick={() => {
            const n = deltaNum;
            const next = Number.isNaN(n) ? -1 : n - 1;
            setDelta(String(next));
          }}
          className="inline-flex size-8 items-center justify-center rounded-md border bg-card hover:bg-muted transition-colors"
          aria-label="Decrease delta by 1"
        >
          <Minus className="size-3.5" />
        </button>
        <Input
          value={delta}
          onChange={(e) => setDelta(e.target.value)}
          placeholder="±0"
          className="text-center font-mono w-24"
          inputMode="numeric"
        />
        <button
          type="button"
          onClick={() => {
            const n = deltaNum;
            const next = Number.isNaN(n) ? 1 : n + 1;
            setDelta(String(next));
          }}
          className="inline-flex size-8 items-center justify-center rounded-md border bg-card hover:bg-muted transition-colors"
          aria-label="Increase delta by 1"
        >
          <Plus className="size-3.5" />
        </button>
      </div>

      <div className="rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground space-y-1">
        <Row label="Current" value={current.toLocaleString()} mono />
        <Row
          label="After"
          value={projected.toLocaleString()}
          mono
          tone={projected < 0 ? 'negative' : 'neutral'}
        />
      </div>

      <Field>
        <FieldLabel htmlFor="note">Reason</FieldLabel>
        <Input
          id="note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. Received shipment / damaged box / recount"
          maxLength={200}
        />
      </Field>

      <Button type="submit" disabled={!isValid || adjust.isPending} className="w-full">
        {adjust.isPending ? (
          <>
            <Loader2 className="size-4 animate-spin" />
            Applying…
          </>
        ) : (
          'Apply adjustment'
        )}
      </Button>
    </form>
  );
}

// ── Shared ──────────────────────────────────────────────────────────

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
  tone?: 'positive' | 'negative' | 'warn' | 'neutral';
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
          tone === 'warn' && 'text-amber-700',
        )}
      >
        {value}
      </dd>
    </div>
  );
}
