/**
 * `<CustomPackageBuilder>` — inline expandable panel on the invoice
 * page for building a one-off package per customer (not from the
 * catalog).
 *
 * Collapsed: a single "Build a custom package" button. Expanded: a
 * compact form with name, price, validity, and a variable-length
 * list of `{service, quantity}` rows. Submitting POSTs to the
 * `add-custom-package` invoice action.
 *
 * Permission gating happens upstream — this panel is only rendered
 * by the invoice page when `canEditLines` is true and the invoice
 * is OPEN.
 */

'use client';

import {
  ChevronDown,
  Layers,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
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
  type Invoice,
  invoiceErrorMessage,
  useAddCustomPackage,
} from '@/lib/invoices';
import { centsFromDollars } from '@/lib/packages';
import { useServices } from '@/lib/services';
import { cn } from '@/lib/utils';

interface ItemRow {
  service_id: string;
  quantity: string;
}

interface FormErrors {
  name?: string;
  price?: string;
  items?: string;
}

const INITIAL_ROW: ItemRow = { service_id: '', quantity: '1' };

export function CustomPackageBuilder({ invoice }: { invoice: Invoice }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [priceDollars, setPriceDollars] = useState('');
  const [validityDays, setValidityDays] = useState('365');
  const [items, setItems] = useState<ItemRow[]>([INITIAL_ROW]);
  const [errors, setErrors] = useState<FormErrors>({});

  const services = useServices({ activeOnly: true });
  const serviceList = services.data ?? [];
  const add = useAddCustomPackage(invoice.id);

  const aLaCarteCents = items.reduce((sum, row) => {
    const svc = serviceList.find((s) => String(s.id) === row.service_id);
    if (!svc) return sum;
    return sum + svc.price_cents * (Number(row.quantity) || 0);
  }, 0);
  const priceCents = centsFromDollars(priceDollars || '0');
  const savingsCents = aLaCarteCents - priceCents;

  const reset = () => {
    setName('');
    setDescription('');
    setPriceDollars('');
    setValidityDays('365');
    setItems([INITIAL_ROW]);
    setErrors({});
  };

  const validate = (): FormErrors => {
    const next: FormErrors = {};
    if (!name.trim()) next.name = 'Name is required.';
    if (priceDollars === '' || Number.isNaN(Number(priceDollars)))
      next.price = 'Enter a price.';
    if (items.length === 0) {
      next.items = 'Add at least one service.';
    } else {
      const seen = new Set<string>();
      for (const r of items) {
        if (!r.service_id) {
          next.items = 'Pick a service for every row.';
          break;
        }
        if (!r.quantity || Number(r.quantity) < 1) {
          next.items = 'Quantity must be at least 1 for every row.';
          break;
        }
        if (seen.has(r.service_id)) {
          next.items = 'Each service may only appear once.';
          break;
        }
        seen.add(r.service_id);
      }
    }
    return next;
  };

  const onSubmit = () => {
    const next = validate();
    setErrors(next);
    if (Object.keys(next).length > 0) {
      toast.error('Please fix the highlighted fields.');
      return;
    }
    add.mutate(
      {
        name: name.trim(),
        description,
        price_cents: priceCents,
        validity_days:
          validityDays && Number(validityDays) > 0
            ? Number(validityDays)
            : null,
        items: items.map((r) => ({
          service_id: Number(r.service_id),
          quantity: Number(r.quantity),
        })),
      },
      {
        onSuccess: () => {
          toast.success('Custom package added');
          reset();
          setOpen(false);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as Record<string, unknown>;
            const merged: FormErrors = {};
            if (typeof body.name === 'string') merged.name = body.name;
            else if (Array.isArray(body.name) && typeof body.name[0] === 'string')
              merged.name = body.name[0];
            if (typeof body.price_cents === 'string')
              merged.price = body.price_cents;
            if (typeof body.items === 'string') merged.items = body.items;
            else if (Array.isArray(body.items) && typeof body.items[0] === 'string')
              merged.items = body.items[0];
            if (Object.keys(merged).length > 0) {
              setErrors(merged);
              toast.error('Please fix the highlighted fields.');
              return;
            }
          }
          toast.error(
            invoiceErrorMessage(err, "Couldn't build that custom package."),
          );
        },
      },
    );
  };

  if (!open) {
    return (
      <div className="px-6 py-4 border-t bg-emerald-50/30">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-2 text-sm text-emerald-900 hover:text-emerald-950 transition-colors"
        >
          <Layers className="size-4" />
          Build a custom package for this customer
          <ChevronDown className="size-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="px-6 py-5 border-t bg-emerald-50/30 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-emerald-900 font-medium flex items-center gap-1.5">
            <Layers className="size-3.5" />
            Custom package
          </p>
          <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
            One-off bundle just for this customer. Won&rsquo;t be saved to
            the catalog.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Field className="md:col-span-2" data-invalid={errors.name ? true : undefined}>
          <FieldLabel htmlFor="cp-name">Package name</FieldLabel>
          <Input
            id="cp-name"
            placeholder="e.g. Jane's Wedding Bundle"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          {errors.name ? <FieldError>{errors.name}</FieldError> : null}
        </Field>
        <Field data-invalid={errors.price ? true : undefined}>
          <FieldLabel htmlFor="cp-price">Total price</FieldLabel>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
              $
            </span>
            <Input
              id="cp-price"
              type="text"
              inputMode="decimal"
              placeholder="0.00"
              className="pl-7"
              value={priceDollars}
              onChange={(e) => setPriceDollars(e.target.value)}
            />
          </div>
          {errors.price ? <FieldError>{errors.price}</FieldError> : null}
        </Field>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field>
          <FieldLabel htmlFor="cp-desc">
            Notes
            <span className="text-muted-foreground/70 font-normal ml-1">
              (optional)
            </span>
          </FieldLabel>
          <Input
            id="cp-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="cp-validity">
            Expires after
            <span className="text-muted-foreground/70 font-normal ml-1">
              (days)
            </span>
          </FieldLabel>
          <Input
            id="cp-validity"
            type="text"
            inputMode="numeric"
            placeholder="365 or blank"
            value={validityDays}
            onChange={(e) => setValidityDays(e.target.value)}
          />
        </Field>
      </div>

      <div className="space-y-2">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          Included services
        </p>
        {items.map((row, index) => (
          <ItemRowEditor
            key={index}
            row={row}
            services={serviceList}
            onChange={(patch) =>
              setItems((arr) =>
                arr.map((r, i) => (i === index ? { ...r, ...patch } : r)),
              )
            }
            onRemove={() =>
              setItems((arr) => arr.filter((_, i) => i !== index))
            }
          />
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setItems((arr) => [...arr, { ...INITIAL_ROW }])}
        >
          <Plus className="size-3.5" />
          Add a service
        </Button>
        {errors.items ? (
          <p className="text-xs text-destructive mt-1">{errors.items}</p>
        ) : null}
      </div>

      <div className="flex items-center justify-between gap-3 pt-3 border-t border-emerald-200/50">
        <p className="text-xs text-muted-foreground">
          A la carte total ${(aLaCarteCents / 100).toFixed(2)} ·{' '}
          <span
            className={cn(
              'font-medium',
              savingsCents > 0
                ? 'text-emerald-700'
                : savingsCents < 0
                  ? 'text-red-700'
                  : 'text-muted-foreground',
            )}
          >
            {savingsCents > 0
              ? `$${(savingsCents / 100).toFixed(2)} savings`
              : savingsCents < 0
                ? `$${(Math.abs(savingsCents) / 100).toFixed(2)} over`
                : 'no discount'}
          </span>
        </p>
        <Button
          type="button"
          onClick={onSubmit}
          disabled={add.isPending}
        >
          {add.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Plus className="size-4" />
          )}
          Add to invoice
        </Button>
      </div>
    </div>
  );
}

function ItemRowEditor({
  row,
  services,
  onChange,
  onRemove,
}: {
  row: ItemRow;
  services: { id: number; name: string; price_cents: number; price_dollars: string }[];
  onChange: (patch: Partial<ItemRow>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid grid-cols-12 gap-2 items-center">
      <div className="col-span-8">
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
                No active services.
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
        <Input
          type="number"
          min={1}
          value={row.quantity}
          onChange={(e) => onChange({ quantity: e.target.value })}
          className="text-center font-mono"
          placeholder="1"
          aria-label="Quantity"
        />
      </div>
      <div className="col-span-1 flex justify-end">
        <button
          type="button"
          onClick={onRemove}
          className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive transition-colors"
          aria-label="Remove this item"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
