/**
 * Invoice page for a single appointment.
 *
 * Reachable from the calendar's appointment popover via the "Take
 * payment" CTA, which opens this page in a new tab with `?action=pay`
 * so the payment form is already focused when the page loads. The
 * popover stays minimal; the full invoice surface — line items, tax
 * breakdown, payment metadata, Reopen / Void actions — lives here.
 *
 * Per ADR 0007: closing the invoice (Take Payment) is the only path
 * to marking the linked appointment `completed`. The Reopen action is
 * gated to owner/manager (`REOPEN_INVOICE` permission, locked against
 * per-user override) and to the 60-day window from the first close.
 */

'use client';

import {
  Ban,
  CheckCircle2,
  CreditCard,
  Layers,
  Loader2,
  Package as PackageIcon,
  Plus,
  Repeat,
  RotateCcw,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { use, useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { StatusBadge } from '@/components/status-badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ApiError } from '@/lib/api';
import { useAppointment } from '@/lib/appointments';
import { useCurrentMembership } from '@/lib/auth';
import {
  INVOICE_STATUS_LABELS,
  INVOICE_STATUS_TONE,
  PAYMENT_METHOD_LABELS,
  formatMoneyCents,
  invoiceErrorMessage,
  useAddInvoiceLine,
  useCloseInvoice,
  useInvoiceForAppointment,
  useRedeemFromMembership,
  useRedeemFromPackage,
  useRemoveInvoiceLine,
  useReopenInvoice,
  useVoidInvoice,
  type Invoice,
  type InvoiceLineItem,
  type PaymentMethod,
} from '@/lib/invoices';
import {
  useCustomerPurchasedPackages,
  usePackages,
} from '@/lib/packages';
import { useProducts } from '@/lib/products';
import { useServices } from '@/lib/services';
import {
  useCustomerSubscriptions,
  useMembershipPlans,
} from '@/lib/subscriptions';

import { CustomPackageBuilder } from './_components/custom-package-builder';
import { cn } from '@/lib/utils';

type Mode = 'view' | 'pay' | 'reopen' | 'void';

const REOPEN_ROLES = new Set(['owner', 'manager']);
const VOID_ROLES = new Set(['owner', 'manager']);

const DEFAULT_TIMEZONE = 'America/New_York';

interface InvoicePageProps {
  params: Promise<{ id: string }>;
}

export default function AppointmentInvoicePage({ params }: InvoicePageProps) {
  const { id: idStr } = use(params);
  const id = Number(idStr);

  const { data: appointment, isLoading: loadingAppt } = useAppointment(id);
  const { data: invoice, isLoading: loadingInvoice, error } = useInvoiceForAppointment(id);

  if (loadingAppt || loadingInvoice) {
    return <Loading />;
  }
  if (error || !appointment) {
    return <Error />;
  }
  if (!invoice) {
    return <Missing />;
  }

  return <InvoiceBody appointment={appointment} invoice={invoice} />;
}

// ── Body ─────────────────────────────────────────────────────────────────

function InvoiceBody({
  appointment,
  invoice,
}: {
  appointment: NonNullable<ReturnType<typeof useAppointment>['data']>;
  invoice: Invoice;
}) {
  const searchParams = useSearchParams();
  const initialAction = searchParams.get('action');
  // Lazy initializer — picks the right mode on first render based on
  // ?action= + the loaded invoice status. Avoids a setState-in-effect
  // cascade and the eslint-disable workaround that came with it.
  const [mode, setMode] = useState<Mode>(() => {
    if (initialAction === 'pay' && invoice.status === 'open') return 'pay';
    if (initialAction === 'reopen' && invoice.status === 'paid') return 'reopen';
    if (initialAction === 'void' && invoice.status === 'open') return 'void';
    return 'view';
  });

  const membership = useCurrentMembership();
  const role = membership?.role ?? '';
  const canReopen = REOPEN_ROLES.has(role);
  const canVoid = VOID_ROLES.has(role);
  // Adding/removing lines requires PROCESS_PAYMENT (owner / manager /
  // front_desk by default). Backend permission is the source of truth;
  // this is just a UI gate to hide the affordance when it'd 403.
  const canEditLines =
    role === 'owner' || role === 'manager' || role === 'front_desk';

  const tz = DEFAULT_TIMEZONE;

  return (
    <div className="px-10 py-10 max-w-3xl">
      <PageHeader
        title={invoice.invoice_number || `Invoice #${invoice.id}`}
        description={`${appointment.customer.full_name} · ${appointment.service.name} · ${formatLongDateTime(appointment.start_time, tz)}`}
        back={{ href: '/calendar', label: 'Back to calendar' }}
        actions={
          <StatusBadge tone={INVOICE_STATUS_TONE[invoice.status]}>
            {INVOICE_STATUS_LABELS[invoice.status]}
          </StatusBadge>
        }
      />

      <Card>
        <CardContent className="p-0">
          <ContextSection appointment={appointment} timezone={tz} />
          <Divider />
          <LineItemsTable invoice={invoice} canEdit={canEditLines} />
          {canEditLines && invoice.status === 'open' ? (
            <AddLinePanel invoice={invoice} />
          ) : null}
          {canEditLines && invoice.status === 'open' && invoice.customer ? (
            <CustomPackageBuilder invoice={invoice} />
          ) : null}
          {canEditLines && invoice.status === 'open' && invoice.customer ? (
            <RedeemFromPackagePanel
              invoice={invoice}
              customerId={invoice.customer.id}
            />
          ) : null}
          {canEditLines && invoice.status === 'open' && invoice.customer ? (
            <RedeemFromMembershipPanel
              invoice={invoice}
              customerId={invoice.customer.id}
            />
          ) : null}
          <Divider />
          <TotalsBlock invoice={invoice} />
          {invoice.status === 'paid' || invoice.status === 'void' ? (
            <>
              <Divider />
              <LifecycleSummary invoice={invoice} />
            </>
          ) : null}
        </CardContent>
      </Card>

      <div className="mt-6 space-y-4">
        {mode === 'view' ? (
          <ActionRow
            invoice={invoice}
            canReopen={canReopen}
            canVoid={canVoid}
            onPay={() => setMode('pay')}
            onReopen={() => setMode('reopen')}
            onVoid={() => setMode('void')}
          />
        ) : null}

        {mode === 'pay' ? (
          <PayForm
            invoice={invoice}
            onDone={() => setMode('view')}
            onCancel={() => setMode('view')}
          />
        ) : null}

        {mode === 'reopen' ? (
          <ReopenForm
            invoice={invoice}
            onDone={() => setMode('view')}
            onCancel={() => setMode('view')}
          />
        ) : null}

        {mode === 'void' ? (
          <VoidForm
            invoice={invoice}
            onDone={() => setMode('view')}
            onCancel={() => setMode('view')}
          />
        ) : null}
      </div>
    </div>
  );
}

// ── Sections ─────────────────────────────────────────────────────────────

function ContextSection({
  appointment,
  timezone,
}: {
  appointment: NonNullable<ReturnType<typeof useAppointment>['data']>;
  timezone: string;
}) {
  const provider = appointment.provider;
  const providerName =
    `${provider.user_first_name ?? ''} ${provider.user_last_name ?? ''}`.trim() ||
    provider.user_email;
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 px-6 py-5 text-sm">
      <dt className="text-muted-foreground">Customer</dt>
      <dd className="font-medium">{appointment.customer.full_name}</dd>

      <dt className="text-muted-foreground">Service</dt>
      <dd>
        {appointment.service.name}{' '}
        <span className="text-muted-foreground">· {appointment.duration_minutes}m</span>
      </dd>

      <dt className="text-muted-foreground">Provider</dt>
      <dd>{providerName}</dd>

      <dt className="text-muted-foreground">Time</dt>
      <dd className="font-mono tabular-nums">
        {formatLongDateTime(appointment.start_time, timezone)}
      </dd>
    </dl>
  );
}

function LineItemsTable({
  invoice,
  canEdit,
}: {
  invoice: Invoice;
  canEdit: boolean;
}) {
  const remove = useRemoveInvoiceLine(invoice.id);
  const editable = canEdit && invoice.status === 'open';

  const onRemove = (lineId: number) => {
    if (!editable) return;
    remove.mutate(lineId, {
      onSuccess: () => toast.success('Line removed'),
      onError: (err) =>
        toast.error(invoiceErrorMessage(err, "Couldn't remove the line.")),
    });
  };

  return (
    <div className="px-6 py-5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-3">
        Line items
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wide text-muted-foreground">
            <th className="text-left font-normal pb-2">Description</th>
            <th className="text-right font-normal pb-2 w-12">Qty</th>
            <th className="text-right font-normal pb-2 w-24">Price</th>
            <th className="text-right font-normal pb-2 w-24">Tax</th>
            <th className="text-right font-normal pb-2 w-28">Subtotal</th>
            {editable ? <th className="w-8" /> : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {invoice.line_items.map((line) => (
            <LineRow
              key={line.id}
              line={line}
              editable={editable}
              onRemove={onRemove}
              isRemoving={remove.isPending && remove.variables === line.id}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LineRow({
  line,
  editable,
  onRemove,
  isRemoving,
}: {
  line: InvoiceLineItem;
  editable: boolean;
  onRemove: (id: number) => void;
  isRemoving: boolean;
}) {
  const Icon = line.product
    ? PackageIcon
    : line.service
      ? Sparkles
      : null;
  return (
    <tr className="group">
      <td className="py-2.5">
        <div className="flex items-center gap-2">
          {Icon ? (
            <Icon className="size-3.5 text-muted-foreground shrink-0" />
          ) : null}
          <span>{line.description}</span>
        </div>
      </td>
      <td className="py-2.5 text-right font-mono tabular-nums">
        {line.quantity}
      </td>
      <td className="py-2.5 text-right font-mono tabular-nums">
        {formatMoneyCents(line.unit_price_cents)}
      </td>
      <td className="py-2.5 text-right font-mono tabular-nums text-muted-foreground">
        {formatMoneyCents(line.line_tax_cents)}
      </td>
      <td className="py-2.5 text-right font-mono tabular-nums">
        {formatMoneyCents(line.line_subtotal_cents + line.line_tax_cents)}
      </td>
      {editable ? (
        <td className="py-2.5 text-right">
          <button
            type="button"
            onClick={() => onRemove(line.id)}
            disabled={isRemoving}
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground/60 opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-destructive transition-all disabled:opacity-50"
            aria-label="Remove line"
            title="Remove line"
          >
            {isRemoving ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Trash2 className="size-3.5" />
            )}
          </button>
        </td>
      ) : null}
    </tr>
  );
}

type AddLineKind = 'product' | 'service' | 'package' | 'membership';

function AddLinePanel({ invoice }: { invoice: Invoice }) {
  const [kind, setKind] = useState<AddLineKind>('product');
  const [selectedId, setSelectedId] = useState<string>('');
  const [quantity, setQuantity] = useState('1');
  const products = useProducts({ activeOnly: true });
  const services = useServices({ activeOnly: true });
  const packages = usePackages({ activeOnly: true });
  const memberships = useMembershipPlans({ activeOnly: true });
  const add = useAddInvoiceLine(invoice.id);

  // Single handler for the kind toggle so the selectedId reset
  // happens in the event-handler path, not as an effect — which
  // would cascade an extra render and trip react-hooks/set-state-in-effect.
  const switchKind = (next: AddLineKind) => {
    if (next === kind) return;
    setKind(next);
    setSelectedId('');
    // Packages and memberships always go on as qty=1.
    setQuantity(next === 'package' || next === 'membership' ? '1' : quantity);
  };

  const onAdd = () => {
    const id = Number(selectedId);
    const qty = Math.max(1, Number(quantity) || 1);
    if (!id) {
      toast.error('Pick a catalog item first.');
      return;
    }
    const payload =
      kind === 'product'
        ? { product_id: id, quantity: qty }
        : kind === 'service'
          ? { service_id: id, quantity: qty }
          : kind === 'package'
            ? { package_id: id }
            : { membership_plan_id: id };
    add.mutate(payload, {
      onSuccess: () => {
        const label =
          kind === 'product' ? 'Product'
          : kind === 'service' ? 'Service'
          : kind === 'package' ? 'Package'
          : 'Membership';
        toast.success(`${label} added`);
        setSelectedId('');
        setQuantity('1');
      },
      onError: (err) => {
        if (err instanceof ApiError && err.body && typeof err.body === 'object') {
          const body = err.body as Record<string, unknown>;
          const firstField = Object.values(body).find(
            (v) => typeof v === 'string',
          );
          toast.error(
            (typeof body.detail === 'string' ? body.detail : null)
              ?? (typeof firstField === 'string' ? firstField : null)
              ?? 'Could not add this line.',
          );
        } else {
          toast.error('Could not add this line.');
        }
      },
    });
  };

  const productOptions = products.data ?? [];
  const serviceOptions = services.data ?? [];
  const packageOptions = packages.data ?? [];
  const membershipOptions = memberships.data ?? [];
  const list =
    kind === 'product'
      ? productOptions
      : kind === 'service'
        ? serviceOptions
        : kind === 'package'
          ? packageOptions
          : membershipOptions;

  return (
    <div className="px-6 py-5 border-t bg-muted/20">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-3">
        Add to this invoice
      </p>
      <div className="flex items-end gap-2 flex-wrap">
        <div className="inline-flex items-center gap-0.5 rounded-md border bg-card p-0.5 flex-wrap">
          {(['product', 'service', 'package', 'membership'] as const).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => switchKind(k)}
              className={cn(
                'inline-flex items-center gap-1.5 px-3 h-8 rounded text-sm capitalize transition-colors',
                kind === k
                  ? 'bg-foreground text-background font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {k === 'product' ? (
                <PackageIcon className="size-3.5" />
              ) : k === 'service' ? (
                <Sparkles className="size-3.5" />
              ) : k === 'package' ? (
                <Layers className="size-3.5" />
              ) : (
                <CreditCard className="size-3.5" />
              )}
              {k}
            </button>
          ))}
        </div>

        <div className="flex-1 min-w-[200px]">
          <Select
            value={selectedId}
            onValueChange={(v) => setSelectedId(v ?? '')}
          >
            <SelectTrigger className="w-full">
              <SelectValue
                placeholder={
                  kind === 'product' ? 'Pick a product…' : 'Pick a service…'
                }
              />
            </SelectTrigger>
            <SelectContent>
              {list.length === 0 ? (
                <div className="px-2 py-2 text-xs text-muted-foreground">
                  No active {kind}s in the catalog.
                </div>
              ) : (
                list.map((row) => (
                  <SelectItem key={row.id} value={String(row.id)}>
                    <span className="flex items-center justify-between gap-3 w-full">
                      <span className="truncate">{row.name}</span>
                      <span className="text-xs text-muted-foreground font-mono shrink-0">
                        {row.price_dollars}
                      </span>
                    </span>
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
        </div>

        {kind === 'package' || kind === 'membership' ? null : (
          <div>
            <Input
              type="number"
              min={1}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="w-20 text-center font-mono"
              aria-label="Quantity"
            />
          </div>
        )}

        <Button
          type="button"
          onClick={onAdd}
          disabled={!selectedId || add.isPending}
        >
          {add.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Plus className="size-4" />
          )}
          Add
        </Button>
      </div>
    </div>
  );
}

function RedeemFromPackagePanel({
  invoice,
  customerId,
}: {
  invoice: Invoice;
  customerId: number;
}) {
  const { data, isLoading } = useCustomerPurchasedPackages(customerId, {
    status: 'active',
  });
  const redeem = useRedeemFromPackage(invoice.id);

  // Only redeemable packages (active + not expired + has remaining
  // credits on at least one service).
  const redeemable = (data ?? []).filter((p) => p.is_redeemable);

  const [selectedPackageId, setSelectedPackageId] = useState<string>('');
  const [selectedServiceId, setSelectedServiceId] = useState<string>('');

  // Reset the service picker whenever the package changes.
  const onPackageChange = (next: string) => {
    if (next === selectedPackageId) return;
    setSelectedPackageId(next);
    setSelectedServiceId('');
  };

  const selectedPackage = redeemable.find(
    (p) => String(p.id) === selectedPackageId,
  );
  const availableServices = (selectedPackage?.items ?? []).filter(
    (it) => it.quantity_remaining > 0,
  );

  if (!isLoading && redeemable.length === 0) {
    // No active packages → don't show the panel at all. Keeps the
    // POS surface clean for customers who haven't bought packages.
    return null;
  }

  const onRedeem = () => {
    if (!selectedPackageId || !selectedServiceId) return;
    redeem.mutate(
      {
        purchased_package_id: Number(selectedPackageId),
        service_id: Number(selectedServiceId),
      },
      {
        onSuccess: () => {
          toast.success('Package credit redeemed');
          setSelectedServiceId('');
        },
        onError: (err) => {
          toast.error(
            invoiceErrorMessage(err, "Couldn't redeem this credit."),
          );
        },
      },
    );
  };

  return (
    <div className="px-6 py-5 border-t bg-emerald-50/40">
      <div className="flex items-start gap-2 mb-3">
        <Layers className="size-3.5 text-emerald-700 mt-0.5 shrink-0" />
        <p className="text-[11px] uppercase tracking-wide text-emerald-900 font-medium">
          Redeem from package
        </p>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">
          Loading package balances…
        </p>
      ) : (
        <div className="flex items-end gap-2 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <Select
              value={selectedPackageId}
              onValueChange={(v) => onPackageChange(v ?? '')}
            >
              <SelectTrigger>
                <SelectValue placeholder="Pick a package…" />
              </SelectTrigger>
              <SelectContent>
                {redeemable.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    <span className="flex items-center justify-between gap-3 w-full">
                      <span className="truncate">{p.name}</span>
                      <span className="text-xs text-emerald-700 shrink-0">
                        {p.total_credits_remaining} credits
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex-1 min-w-[200px]">
            <Select
              value={selectedServiceId}
              onValueChange={(v) => setSelectedServiceId(v ?? '')}
              disabled={!selectedPackage}
            >
              <SelectTrigger>
                <SelectValue placeholder="Pick a service…" />
              </SelectTrigger>
              <SelectContent>
                {availableServices.map((it) => (
                  <SelectItem key={it.id} value={String(it.service)}>
                    <span className="flex items-center justify-between gap-3 w-full">
                      <span className="truncate">{it.service_name}</span>
                      <span className="text-xs text-emerald-700 shrink-0">
                        {it.quantity_remaining} left
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Button
            type="button"
            variant="outline"
            onClick={onRedeem}
            disabled={
              !selectedPackageId || !selectedServiceId || redeem.isPending
            }
          >
            {redeem.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <CheckCircle2 className="size-4" />
            )}
            Redeem
          </Button>
        </div>
      )}
    </div>
  );
}

function TotalsBlock({ invoice }: { invoice: Invoice }) {
  return (
    <div className="px-6 py-5 flex justify-end">
      <dl className="text-sm space-y-1.5 min-w-[200px]">
        <SummaryRow label="Subtotal" value={formatMoneyCents(invoice.subtotal_cents)} />
        <SummaryRow label="Tax" value={formatMoneyCents(invoice.tax_cents)} />
        <div className="border-t border-border/60 pt-1.5 mt-1.5">
          <SummaryRow
            label="Total"
            value={formatMoneyCents(invoice.total_cents)}
            emphasis
          />
        </div>
      </dl>
    </div>
  );
}

function SummaryRow({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-8">
      <dt
        className={cn(
          'text-muted-foreground',
          emphasis && 'text-foreground font-medium',
        )}
      >
        {label}
      </dt>
      <dd
        className={cn(
          'font-mono tabular-nums',
          emphasis && 'font-semibold text-base',
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function LifecycleSummary({ invoice }: { invoice: Invoice }) {
  if (invoice.status === 'paid') {
    return (
      <div className="px-6 py-5 text-xs space-y-1 text-muted-foreground">
        <p>
          <span className="text-foreground font-medium">Paid</span>{' '}
          {invoice.closed_at ? `on ${formatLongDateTime(invoice.closed_at, DEFAULT_TIMEZONE)}` : ''}
          {invoice.closed_by_email ? ` by ${invoice.closed_by_email}` : ''}
        </p>
        {invoice.payment_method ? (
          <p>
            Method:{' '}
            {PAYMENT_METHOD_LABELS[invoice.payment_method as PaymentMethod] ??
              invoice.payment_method}
            {invoice.payment_reference ? ` · ${invoice.payment_reference}` : ''}
          </p>
        ) : null}
        {invoice.reopen_count > 0 ? (
          <p>Reopened {invoice.reopen_count} time{invoice.reopen_count === 1 ? '' : 's'}.</p>
        ) : null}
      </div>
    );
  }
  if (invoice.status === 'void') {
    return (
      <div className="px-6 py-5 text-xs space-y-1 text-muted-foreground">
        <p>
          <span className="text-destructive font-medium">Voided</span>{' '}
          {invoice.voided_at ? `on ${formatLongDateTime(invoice.voided_at, DEFAULT_TIMEZONE)}` : ''}
          {invoice.voided_by_email ? ` by ${invoice.voided_by_email}` : ''}
        </p>
        {invoice.void_reason ? <p>Reason: {invoice.void_reason}</p> : null}
      </div>
    );
  }
  return null;
}

function RedeemFromMembershipPanel({
  invoice,
  customerId,
}: {
  invoice: Invoice;
  customerId: number;
}) {
  const { data, isLoading } = useCustomerSubscriptions(customerId, {
    status: 'active',
  });
  const redeem = useRedeemFromMembership(invoice.id);

  // Only redeemable subscriptions: ACTIVE + in-period + remaining
  // credits on at least one service.
  const redeemable = (data ?? []).filter((s) => s.is_redeemable);

  const [selectedSubId, setSelectedSubId] = useState<string>('');
  const [selectedServiceId, setSelectedServiceId] = useState<string>('');

  const onSubChange = (next: string) => {
    if (next === selectedSubId) return;
    setSelectedSubId(next);
    setSelectedServiceId('');
  };

  const selectedSub = redeemable.find((s) => String(s.id) === selectedSubId);
  const availableServices = (selectedSub?.items ?? []).filter(
    (it) => it.quantity_remaining > 0,
  );

  if (!isLoading && redeemable.length === 0) {
    // No active in-period memberships → don't show the panel.
    return null;
  }

  const onRedeem = () => {
    if (!selectedSubId || !selectedServiceId) return;
    redeem.mutate(
      {
        subscription_id: Number(selectedSubId),
        service_id: Number(selectedServiceId),
      },
      {
        onSuccess: () => {
          toast.success('Membership credit redeemed');
          setSelectedServiceId('');
        },
        onError: (err) => {
          toast.error(
            invoiceErrorMessage(err, "Couldn't redeem this credit."),
          );
        },
      },
    );
  };

  return (
    <div className="px-6 py-5 border-t bg-violet-50/40">
      <div className="flex items-start gap-2 mb-3">
        <Repeat className="size-3.5 text-violet-700 mt-0.5 shrink-0" />
        <p className="text-[11px] uppercase tracking-wide text-violet-900 font-medium">
          Redeem from membership
        </p>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">
          Loading membership balances…
        </p>
      ) : (
        <div className="flex items-end gap-2 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <Select
              value={selectedSubId}
              onValueChange={(v) => onSubChange(v ?? '')}
            >
              <SelectTrigger>
                <SelectValue placeholder="Pick a membership…" />
              </SelectTrigger>
              <SelectContent>
                {redeemable.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    <span className="flex items-center justify-between gap-3 w-full">
                      <span className="truncate">{s.name}</span>
                      <span className="text-xs text-violet-700 shrink-0">
                        {s.total_credits_remaining} this cycle
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex-1 min-w-[200px]">
            <Select
              value={selectedServiceId}
              onValueChange={(v) => setSelectedServiceId(v ?? '')}
              disabled={!selectedSub}
            >
              <SelectTrigger>
                <SelectValue placeholder="Pick a service…" />
              </SelectTrigger>
              <SelectContent>
                {availableServices.map((it) => (
                  <SelectItem key={it.id} value={String(it.service)}>
                    <span className="flex items-center justify-between gap-3 w-full">
                      <span className="truncate">{it.service_name}</span>
                      <span className="text-xs text-violet-700 shrink-0">
                        {it.quantity_remaining} left
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Button
            type="button"
            variant="outline"
            onClick={onRedeem}
            disabled={
              !selectedSubId || !selectedServiceId || redeem.isPending
            }
          >
            {redeem.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <CheckCircle2 className="size-4" />
            )}
            Redeem
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Action row ───────────────────────────────────────────────────────────

function ActionRow({
  invoice,
  canReopen,
  canVoid,
  onPay,
  onReopen,
  onVoid,
}: {
  invoice: Invoice;
  canReopen: boolean;
  canVoid: boolean;
  onPay: () => void;
  onReopen: () => void;
  onVoid: () => void;
}) {
  if (invoice.status === 'open') {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" onClick={onPay}>
          <CreditCard className="size-4" />
          Take payment · {formatMoneyCents(invoice.total_cents)}
        </Button>
        {canVoid ? (
          <Button
            type="button"
            variant="outline"
            onClick={onVoid}
            className="text-destructive hover:text-destructive"
          >
            <Ban className="size-4" />
            Void invoice
          </Button>
        ) : null}
      </div>
    );
  }

  if (invoice.status === 'paid') {
    if (!canReopen) {
      return (
        <p className="text-sm text-muted-foreground">
          This invoice is closed. Only owners and managers can reopen it.
        </p>
      );
    }
    if (!invoice.is_reopen_window_open) {
      return (
        <p className="text-sm text-muted-foreground">
          The 60-day reopen window expired
          {invoice.reopen_deadline
            ? ` on ${formatLongDateTime(invoice.reopen_deadline, DEFAULT_TIMEZONE)}`
            : ''}
          . The invoice is sealed.
        </p>
      );
    }
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" onClick={onReopen}>
          <RotateCcw className="size-4" />
          Reopen invoice
        </Button>
        {invoice.reopen_deadline ? (
          <span className="text-xs text-muted-foreground">
            Window closes {formatLongDateTime(invoice.reopen_deadline, DEFAULT_TIMEZONE)}
          </span>
        ) : null}
      </div>
    );
  }

  // status === 'void' — terminal, nothing actionable.
  return null;
}

// ── Forms ────────────────────────────────────────────────────────────────

function PayForm({
  invoice,
  onDone,
  onCancel,
}: {
  invoice: Invoice;
  onDone: () => void;
  onCancel: () => void;
}) {
  const close = useCloseInvoice(invoice.id);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('cash');
  const [reference, setReference] = useState('');

  const submit = () => {
    close.mutate(
      {
        payment_method: paymentMethod,
        payment_reference: reference.trim() || undefined,
      },
      {
        onSuccess: () => {
          toast.success('Payment recorded · appointment marked completed', {
            icon: <CheckCircle2 className="size-4" />,
          });
          onDone();
        },
        onError: (err) => {
          toast.error(invoiceErrorMessage(err, 'Could not take payment.'));
        },
      },
    );
  };

  return (
    <Card>
      <CardContent className="p-6 space-y-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Take payment
          </p>
          <p className="font-serif text-2xl font-semibold tracking-tight mt-1">
            {formatMoneyCents(invoice.total_cents)}
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-muted-foreground">Payment method</span>
            <Select
              value={paymentMethod}
              onValueChange={(v) => setPaymentMethod(v as PaymentMethod)}
            >
              <SelectTrigger className="w-full mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.entries(PAYMENT_METHOD_LABELS) as [PaymentMethod, string][]).map(
                  ([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ),
                )}
              </SelectContent>
            </Select>
          </label>
          <label className="block text-sm">
            <span className="text-muted-foreground">Reference (optional)</span>
            <input
              type="text"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Last 4, check #, drawer #…"
              maxLength={100}
              className="w-full mt-1.5 h-9 rounded-md border bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            />
          </label>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button type="button" variant="outline" disabled={close.isPending} onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" disabled={close.isPending} onClick={submit}>
            {close.isPending ? 'Recording…' : 'Confirm payment'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ReopenForm({
  invoice,
  onDone,
  onCancel,
}: {
  invoice: Invoice;
  onDone: () => void;
  onCancel: () => void;
}) {
  const reopen = useReopenInvoice(invoice.id);
  const [reason, setReason] = useState('');
  const trimmed = reason.trim();

  const submit = () => {
    reopen.mutate(
      { reason: trimmed },
      {
        onSuccess: () => {
          toast.success('Invoice reopened · appointment back to checked-in');
          onDone();
        },
        onError: (err) => {
          toast.error(invoiceErrorMessage(err, 'Could not reopen invoice.'));
        },
      },
    );
  };

  return (
    <Card>
      <CardContent className="p-6 space-y-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Reopen invoice
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            Reverts the appointment to checked-in so payment can be re-collected
            or amended. The reason is recorded in the audit log.
          </p>
        </div>
        <label className="block text-sm">
          <span className="text-muted-foreground">Reason (required)</span>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. customer disputes amount"
            maxLength={200}
            className="w-full mt-1.5 h-9 rounded-md border bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </label>
        <div className="flex items-center justify-end gap-2 pt-2">
          <Button type="button" variant="outline" disabled={reopen.isPending} onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" disabled={reopen.isPending || !trimmed} onClick={submit}>
            {reopen.isPending ? 'Reopening…' : 'Reopen'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function VoidForm({
  invoice,
  onDone,
  onCancel,
}: {
  invoice: Invoice;
  onDone: () => void;
  onCancel: () => void;
}) {
  const voidInv = useVoidInvoice(invoice.id);
  const [reason, setReason] = useState('');
  const trimmed = reason.trim();

  const submit = () => {
    voidInv.mutate(
      { reason: trimmed },
      {
        onSuccess: () => {
          toast.success('Invoice voided');
          onDone();
        },
        onError: (err) => {
          toast.error(invoiceErrorMessage(err, 'Could not void invoice.'));
        },
      },
    );
  };

  return (
    <Card>
      <CardContent className="p-6 space-y-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-destructive">
            Void invoice
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            Voiding is terminal. Use for booking errors or comp&apos;d visits.
          </p>
        </div>
        <label className="block text-sm">
          <span className="text-muted-foreground">Reason (required)</span>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. duplicate booking"
            maxLength={200}
            className="w-full mt-1.5 h-9 rounded-md border bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </label>
        <div className="flex items-center justify-end gap-2 pt-2">
          <Button type="button" variant="outline" disabled={voidInv.isPending} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={voidInv.isPending || !trimmed}
            onClick={submit}
          >
            {voidInv.isPending ? 'Voiding…' : 'Void invoice'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Loading / error / missing states ─────────────────────────────────────

function Loading() {
  return (
    <div className="px-10 py-10 max-w-3xl">
      <PageHeader
        title="Invoice"
        description="Loading…"
        back={{ href: '/calendar', label: 'Back to calendar' }}
      />
    </div>
  );
}

function Error() {
  return (
    <div className="px-10 py-10 max-w-3xl">
      <PageHeader
        title="Invoice"
        back={{ href: '/calendar', label: 'Back to calendar' }}
      />
      <p className="text-sm text-destructive">Could not load invoice.</p>
    </div>
  );
}

function Missing() {
  return (
    <div className="px-10 py-10 max-w-3xl">
      <PageHeader
        title="Invoice"
        back={{ href: '/calendar', label: 'Back to calendar' }}
      />
      <Card>
        <CardContent className="px-6 py-12 text-center">
          <p className="text-sm font-medium">No invoice on file for this appointment.</p>
          <p className="text-xs text-muted-foreground mt-2">
            Invoices are created automatically at booking time. If you&apos;re seeing this
            on a recently booked appointment, refresh in a moment.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

function Divider() {
  return <div className="border-t border-border/60" aria-hidden />;
}

function formatLongDateTime(iso: string, timezone: string): string {
  return new Date(iso).toLocaleString('en-US', {
    timeZone: timezone,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

