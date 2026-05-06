/**
 * `/catalog/products/new` — create a new retail product.
 *
 * Two-pane layout: form on the left, live preview card on the
 * right. Keeps the form discoverable (each section labeled) without
 * burying pricing or stock fields behind tabs. Submit → POST
 * /api/products/ → on success, redirect to the detail page.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import {
  Boxes,
  DollarSign,
  Package as PackageIcon,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
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
import {
  centsFromDollars,
  useCreateProduct,
  useProductCategories,
} from '@/lib/products';

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
  stock_quantity: z
    .string()
    .refine(
      (v) => v === '' || /^-?\d+$/.test(v),
      'Enter a whole number',
    ),
  low_stock_threshold: z
    .string()
    .refine(
      (v) => v === '' || /^\d+$/.test(v),
      'Enter zero or a positive whole number',
    ),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

export default function NewProductPage() {
  const router = useRouter();
  const create = useCreateProduct();
  const { data: categories } = useProductCategories();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      sku: '',
      description: '',
      category_id: '',
      price_dollars: '',
      cost_dollars: '',
      tax_rate_percent: '0',
      track_inventory: true,
      stock_quantity: '0',
      low_stock_threshold: '0',
      is_active: true,
    },
  });
  const watched = form.watch();

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
      stock_quantity: Number(values.stock_quantity || '0'),
      low_stock_threshold: Number(values.low_stock_threshold || '0'),
      is_active: values.is_active,
    };
    create.mutate(payload, {
      onSuccess: (created) => {
        toast.success(`${created.name} added to catalog`);
        router.push(`/catalog/products/${created.id}`);
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
          toast.error('Failed to create product. Please try again.');
        }
      },
    });
  };

  const previewPrice = watched.price_dollars
    ? `$${Number(watched.price_dollars || 0).toFixed(2)}`
    : '$0.00';
  const marginCents =
    centsFromDollars(watched.price_dollars || '0')
    - centsFromDollars(watched.cost_dollars || '0');
  const marginDollars = (marginCents / 100).toFixed(2);

  return (
    <div className="px-8 py-8">
      <PageHeader
        title="New product"
        description="Add a retail item to your catalog. Required: name, price."
        back={{ href: '/catalog/products', label: 'All products' }}
      />

      <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="mt-2">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 space-y-10">
            <Section title="Basics" icon={<Sparkles className="size-4" />}>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Field
                  className="md:col-span-2"
                  data-invalid={form.formState.errors.name ? true : undefined}
                >
                  <FieldLabel htmlFor="name">Product name</FieldLabel>
                  <Input
                    id="name"
                    autoFocus
                    placeholder="e.g. Vitamin C Serum 30ml"
                    {...form.register('name')}
                  />
                  {form.formState.errors.name ? (
                    <FieldError>{form.formState.errors.name.message}</FieldError>
                  ) : null}
                </Field>
                <Field
                  data-invalid={form.formState.errors.sku ? true : undefined}
                >
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
                    {...form.register('sku')}
                  />
                  {form.formState.errors.sku ? (
                    <FieldError>{form.formState.errors.sku.message}</FieldError>
                  ) : null}
                </Field>
              </div>

              <Field>
                <FieldLabel htmlFor="description">
                  Description
                  <span className="text-muted-foreground/70 font-normal ml-1">
                    (optional)
                  </span>
                </FieldLabel>
                <textarea
                  id="description"
                  rows={3}
                  placeholder="Internal notes — what's in it, who it's for, retail talking points."
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
                      placeholder="0.00"
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
                <Field
                  data-invalid={
                    form.formState.errors.cost_dollars ? true : undefined
                  }
                >
                  <FieldLabel htmlFor="cost_dollars">
                    Wholesale cost
                    <span className="text-muted-foreground/70 font-normal ml-1">
                      (margin reports)
                    </span>
                  </FieldLabel>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                      $
                    </span>
                    <Input
                      id="cost_dollars"
                      type="text"
                      inputMode="decimal"
                      placeholder="0.00"
                      className="pl-7"
                      {...form.register('cost_dollars')}
                    />
                  </div>
                  {form.formState.errors.cost_dollars ? (
                    <FieldError>
                      {form.formState.errors.cost_dollars.message}
                    </FieldError>
                  ) : null}
                </Field>
                <Field
                  data-invalid={
                    form.formState.errors.tax_rate_percent ? true : undefined
                  }
                >
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
                  {form.formState.errors.tax_rate_percent ? (
                    <FieldError>
                      {form.formState.errors.tax_rate_percent.message}
                    </FieldError>
                  ) : null}
                </Field>
              </div>
              <p className="text-xs text-muted-foreground -mt-2">
                Wholesale cost is internal only &mdash; never displayed to
                customers. Used for margin reporting.
              </p>
            </Section>

            <Section title="Inventory" icon={<Boxes className="size-4" />}>
              <CheckboxRow
                id="track_inventory"
                label="Track inventory for this product"
                description="Uncheck for items where stock count is meaningless (gift cards, digital fees, consultation rates)."
                checked={watched.track_inventory}
                onChange={(v) =>
                  form.setValue('track_inventory', v, { shouldDirty: true })
                }
              />
              {watched.track_inventory ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Field>
                    <FieldLabel htmlFor="stock_quantity">
                      Current stock on hand
                    </FieldLabel>
                    <Input
                      id="stock_quantity"
                      type="number"
                      {...form.register('stock_quantity')}
                    />
                    <p className="text-xs text-muted-foreground mt-1">
                      Will decrement automatically when sold on an invoice.
                    </p>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="low_stock_threshold">
                      Low-stock warning at
                    </FieldLabel>
                    <Input
                      id="low_stock_threshold"
                      type="number"
                      min={0}
                      {...form.register('low_stock_threshold')}
                    />
                    <p className="text-xs text-muted-foreground mt-1">
                      0 disables the warning.
                    </p>
                  </Field>
                </div>
              ) : null}
            </Section>

            <Section title="Status" icon={<PackageIcon className="size-4" />}>
              <CheckboxRow
                id="is_active"
                label="Active"
                description="Inactive products stay in past invoice history but cannot be sold on new invoices."
                checked={watched.is_active}
                onChange={(v) =>
                  form.setValue('is_active', v, { shouldDirty: true })
                }
              />
            </Section>
          </div>

          <aside className="lg:sticky lg:top-10 self-start">
            <div className="rounded-xl border bg-card p-6">
              <p className="text-xs uppercase tracking-wide text-muted-foreground mb-4">
                Live preview
              </p>
              <div className="flex items-start gap-3 mb-4">
                <div className="inline-flex size-10 items-center justify-center rounded-md bg-amber-50 text-amber-700 shrink-0">
                  <PackageIcon className="size-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-serif text-lg font-semibold tracking-tight truncate">
                    {watched.name || 'New product'}
                  </h3>
                  <p className="font-mono text-2xl font-medium tracking-tight mt-1">
                    {previewPrice}
                  </p>
                </div>
              </div>
              {watched.description ? (
                <p className="text-sm text-muted-foreground line-clamp-3 whitespace-pre-wrap">
                  {watched.description}
                </p>
              ) : null}
              <dl className="mt-5 pt-4 border-t space-y-2 text-xs">
                {watched.cost_dollars ? (
                  <Row
                    label="Margin per unit"
                    value={`$${marginDollars}`}
                    tone={marginCents > 0 ? 'positive' : 'neutral'}
                  />
                ) : null}
                {watched.track_inventory ? (
                  <>
                    <Row
                      label="Initial stock"
                      value={Number(watched.stock_quantity || '0').toLocaleString()}
                    />
                    {Number(watched.low_stock_threshold) > 0 ? (
                      <Row
                        label="Low-stock at"
                        value={`${watched.low_stock_threshold}`}
                      />
                    ) : null}
                  </>
                ) : (
                  <Row label="Inventory" value="Not tracked" />
                )}
              </dl>
            </div>
          </aside>
        </div>

        <div className="sticky bottom-0 -mx-8 mt-10 px-8 py-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="flex items-center justify-end gap-2">
            <Button
              render={<Link href="/catalog/products" />}
              nativeButton={false}
              variant="outline"
            >
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Saving…' : 'Save product'}
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
  tone,
}: {
  label: string;
  value: string;
  tone?: 'positive' | 'neutral';
}) {
  return (
    <div className="flex items-baseline justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={
          tone === 'positive'
            ? 'font-mono font-medium text-emerald-700 tabular-nums'
            : 'font-mono font-medium tabular-nums'
        }
      >
        {value}
      </dd>
    </div>
  );
}
