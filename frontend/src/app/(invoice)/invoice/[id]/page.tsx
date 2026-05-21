/**
 * Invoice / take-payment page.
 *
 * Two modes, by URL:
 *   - `/invoice/<appointmentId>` — `[id]` is an appointment id; loads
 *     that appointment + its 1:1 invoice. The common case.
 *   - `/invoice/<invoiceId>?by=invoice` — `[id]` is an invoice id;
 *     loads a standalone invoice that has no appointment (e.g. a
 *     custom package). Same checkout surface, appointment-less.
 *
 * Lives in the `(invoice)` route group — its own window, no CRM
 * sidebar, no top bar. Operators open it from the calendar
 * appointment popover ("Take payment") or the customer wallet tab,
 * always in a new tab. The standalone surface keeps the checkout
 * context focused and reads cleanly on mobile (operators frequently
 * take payment at the front desk on a tablet or phone).
 *
 * `?action=pay` (or `reopen` / `void`) auto-focuses the matching
 * mode on first render so the popover's CTA lands the operator in
 * the right place.
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
  ChevronDown,
  ChevronLeft,
  CreditCard,
  Download,
  Gift,
  Layers,
  Loader2,
  Mail,
  Package as PackageIcon,
  Plus,
  Repeat,
  RotateCcw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { use, useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { StatusBadge } from '@/components/status-badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ACTIVE_TENANT_COOKIE, ApiError } from '@/lib/api';
import { useAppointment } from '@/lib/appointments';
import { useCurrentMembership } from '@/lib/auth';
import {
  INVOICE_STATUS_LABELS,
  INVOICE_STATUS_TONE,
  PAYMENT_METHOD_LABELS,
  formatMoneyCents,
  invoiceErrorMessage,
  useAddGiftCardSale,
  useAddInvoiceLine,
  useApplyGiftCard,
  useCloseInvoice,
  useEmailInvoice,
  useInvoice,
  useInvoiceForAppointment,
  useRedeemFromMembership,
  useRedeemFromPackage,
  useRemoveInvoiceLine,
  useReopenInvoice,
  useReverseGiftCardRedemption,
  useVoidInvoice,
  type Invoice,
  type InvoiceLineItem,
  type PaymentMethod,
} from '@/lib/invoices';
import { centsFromDollars, useGiftCardLookup } from '@/lib/giftcards';
import {
  useCustomerPurchasedPackages,
  usePackages,
} from '@/lib/packages';
import { useProducts } from '@/lib/products';
import { type Service, useServices } from '@/lib/services';
import {
  type Subscription,
  useCustomerSubscriptions,
  useMembershipPlans,
} from '@/lib/subscriptions';

import { CustomPackageBuilder } from './_components/custom-package-builder';
import { cn } from '@/lib/utils';

type Mode = 'view' | 'pay' | 'reopen' | 'void';

const REOPEN_ROLES = new Set(['owner', 'manager']);
const VOID_ROLES = new Set(['owner', 'manager']);

const DEFAULT_TIMEZONE = 'America/New_York';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/** Download the invoice PDF via a fetch + Blob + anchor click. Mirrors
 *  the CSV-export pattern in `/reports`: a plain `<a href>` would skip
 *  the X-Tenant-Slug header the dev backend needs to resolve the
 *  tenant. Session auth + tenant cookie are forwarded via
 *  `credentials: 'include'`. */
function DownloadPdfButton({ invoice }: { invoice: Invoice }) {
  const [downloading, setDownloading] = useState(false);

  const handleClick = async () => {
    setDownloading(true);
    try {
      const tenantSlug = readCookie(ACTIVE_TENANT_COOKIE);
      const headers: Record<string, string> = { Accept: 'application/pdf' };
      if (tenantSlug) headers['X-Tenant-Slug'] = tenantSlug;

      const res = await fetch(`${API_URL}/api/invoices/${invoice.id}/pdf/`, {
        credentials: 'include',
        headers,
      });
      if (!res.ok) {
        toast.error(`Could not download PDF (HTTP ${res.status}).`);
        return;
      }

      const blob = await res.blob();
      const fallbackName = `${invoice.invoice_number || `invoice-${invoice.id}`}.pdf`;
      const filename = parsePdfFilename(res.headers.get('Content-Disposition')) ?? fallbackName;

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      console.error('PDF download failed', err);
      toast.error('Could not download PDF. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={handleClick}
      disabled={downloading}
      className="gap-1.5"
    >
      <Download className="size-3.5" aria-hidden />
      {downloading ? 'Downloading…' : 'Download PDF'}
    </Button>
  );
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function parsePdfFilename(header: string | null): string | null {
  if (!header) return null;
  const m = /filename\*?=(?:UTF-8''|")?([^";]+)"?/i.exec(header);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Email-this-invoice-to-the-client button.
 *
 *  - Disabled (with tooltip) when the customer has no email on file.
 *    The backend would 400 anyway; disabling the button surfaces the
 *    boundary before the click and points the operator at the fix
 *    (update the customer profile).
 *  - Click → confirmation dialog showing the recipient. No silent
 *    sends to PHI-bearing addresses. */
function EmailInvoiceButton({ invoice }: { invoice: Invoice }) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const email = invoice.customer.email?.trim() ?? '';
  const canSend = email.length > 0;
  const sendEmail = useEmailInvoice(invoice.id);

  const handleConfirm = () => {
    sendEmail.mutate(undefined, {
      onSuccess: (data) => {
        toast.success(`Invoice sent to ${data.recipient}`);
        setConfirmOpen(false);
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 400) {
          const detail =
            typeof err.body === 'object' && err.body && 'detail' in err.body
              ? String((err.body as { detail: unknown }).detail)
              : 'Could not send invoice.';
          toast.error(detail);
        } else {
          toast.error('Could not send invoice. Please try again.');
        }
      },
    });
  };

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setConfirmOpen(true)}
        disabled={!canSend}
        className="gap-1.5"
        title={canSend ? '' : 'Add an email to the customer profile to send invoices.'}
      >
        <Mail className="size-3.5" aria-hidden />
        Email to client
      </Button>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-serif">Send invoice to client</DialogTitle>
            <DialogDescription>
              We&rsquo;ll email{' '}
              <strong>
                {invoice.invoice_number || `invoice #${invoice.id}`}
              </strong>{' '}
              to <strong>{email}</strong> with the PDF attached.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            The send is logged in the audit trail with your name and a
            timestamp. Each click sends a fresh copy — no deduplication.
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={sendEmail.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleConfirm}
              disabled={sendEmail.isPending}
              className="gap-1.5"
            >
              <Mail className="size-3.5" aria-hidden />
              {sendEmail.isPending ? 'Sending…' : 'Send invoice'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface InvoicePageProps {
  params: Promise<{ id: string }>;
}

export default function AppointmentInvoicePage({ params }: InvoicePageProps) {
  const { id: idStr } = use(params);
  const id = Number(idStr);
  const searchParams = useSearchParams();
  // `?by=invoice` → `[id]` is an invoice id (a standalone invoice with
  // no appointment — e.g. a custom package). Default → `[id]` is an
  // appointment id, and we load that appointment plus its 1:1 invoice.
  const byInvoice = searchParams.get('by') === 'invoice';

  const { data: appointment, isLoading: loadingAppt } = useAppointment(
    byInvoice ? undefined : id,
  );
  const apptInvoice = useInvoiceForAppointment(byInvoice ? undefined : id);
  const standaloneInvoice = useInvoice(byInvoice ? id : undefined);

  const invoice = byInvoice ? standaloneInvoice.data : apptInvoice.data;
  const loadingInvoice = byInvoice
    ? standaloneInvoice.isLoading
    : apptInvoice.isLoading;
  const error = byInvoice ? standaloneInvoice.error : apptInvoice.error;

  if (loadingInvoice || (!byInvoice && loadingAppt)) {
    return <Loading />;
  }
  if (error || (!byInvoice && !appointment)) {
    return <Error />;
  }
  if (!invoice) {
    return <Missing />;
  }

  return <InvoiceBody appointment={appointment ?? null} invoice={invoice} />;
}

// ── Body ─────────────────────────────────────────────────────────────────

function InvoiceBody({
  appointment,
  invoice,
}: {
  /** Null for standalone invoices (custom packages) — no appointment. */
  appointment: NonNullable<ReturnType<typeof useAppointment>['data']> | null;
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
    <div className="px-3 sm:px-8 py-4 sm:py-10 max-w-3xl mx-auto">
      <InvoiceHeader appointment={appointment} invoice={invoice} timezone={tz} />

      <Card>
        <CardContent className="p-0">
          <ContextSection
            appointment={appointment}
            invoice={invoice}
            timezone={tz}
          />
          <Divider />
          <LineItemsTable invoice={invoice} canEdit={canEditLines} />
          {canEditLines && invoice.status === 'open' ? (
            <AddLinePanel invoice={invoice} />
          ) : null}
          {canEditLines && invoice.status === 'open' && invoice.customer ? (
            <CustomPackageBuilder invoice={invoice} />
          ) : null}
          {canEditLines && invoice.status === 'open' && invoice.customer ? (
            <SellGiftCardPanel invoice={invoice} />
          ) : null}
          {canEditLines && invoice.status === 'open' && invoice.customer ? (
            <ApplyGiftCardPanel invoice={invoice} />
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

// ── Header ───────────────────────────────────────────────────────────────
//
// Mobile-tuned standalone header. The generic `<PageHeader>` puts the
// title + actions on one row which crowds badly when the actions slot
// holds 3 controls (Email, PDF, status badge) and the title is a long
// invoice number. This header stacks:
//   row 1: Back link
//   row 2: Title + status badge
//   row 3: Subtitle (customer · service · time)
//   row 4: Action row (Email · PDF) — right-aligned on desktop, full-
//          width pill row on mobile

function InvoiceHeader({
  appointment,
  invoice,
  timezone,
}: {
  appointment: NonNullable<ReturnType<typeof useAppointment>['data']> | null;
  invoice: Invoice;
  timezone: string;
}) {
  return (
    <div className="mb-5 sm:mb-8">
      <Link
        href="/calendar"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-3"
      >
        <ChevronLeft className="size-3.5" />
        Back to calendar
      </Link>
      <div className="flex items-start gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="font-serif text-xl sm:text-3xl font-semibold tracking-tight text-foreground break-all">
              {invoice.invoice_number || `Invoice #${invoice.id}`}
            </h1>
            <StatusBadge tone={INVOICE_STATUS_TONE[invoice.status]}>
              {INVOICE_STATUS_LABELS[invoice.status]}
            </StatusBadge>
          </div>
          <p className="text-xs sm:text-sm text-muted-foreground mt-2 leading-relaxed">
            <span className="font-medium text-foreground/90">
              {appointment
                ? appointment.customer.full_name
                : invoice.customer.full_name}
            </span>
            <span className="mx-1.5 text-muted-foreground/50">·</span>
            {appointment ? (
              <>
                {appointment.service.name}
                <span className="mx-1.5 text-muted-foreground/50">·</span>
                <span className="tabular-nums">
                  {formatLongDateTime(appointment.start_time, timezone)}
                </span>
              </>
            ) : (
              <span className="tabular-nums">
                Created {formatLongDateTime(invoice.created_at, timezone)}
              </span>
            )}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 mt-4">
        <EmailInvoiceButton invoice={invoice} />
        <DownloadPdfButton invoice={invoice} />
      </div>
    </div>
  );
}

// ── Sections ─────────────────────────────────────────────────────────────

function ContextSection({
  appointment,
  invoice,
  timezone,
}: {
  appointment: NonNullable<ReturnType<typeof useAppointment>['data']> | null;
  invoice: Invoice;
  timezone: string;
}) {
  // Standalone invoice (custom package) — no appointment, so show the
  // customer + creation date. The line-items table below carries the
  // "what was sold" detail.
  if (!appointment) {
    return (
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 sm:gap-x-6 gap-y-2 px-4 sm:px-6 py-5 text-sm">
        <dt className="text-muted-foreground">Customer</dt>
        <dd className="font-medium">{invoice.customer.full_name}</dd>

        <dt className="text-muted-foreground">Type</dt>
        <dd>Custom invoice</dd>

        <dt className="text-muted-foreground">Created</dt>
        <dd className="font-mono tabular-nums">
          {formatLongDateTime(invoice.created_at, timezone)}
        </dd>
      </dl>
    );
  }

  const provider = appointment.provider;
  const providerName =
    `${provider.user_first_name ?? ''} ${provider.user_last_name ?? ''}`.trim() ||
    provider.user_email;
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 sm:gap-x-6 gap-y-2 px-4 sm:px-6 py-5 text-sm">
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
    <div className="px-4 sm:px-6 py-5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-3">
        Line items
      </p>
      {/* overflow-x-auto fallback for very narrow screens; the Tax
          column hides below sm so the typical phone layout fits without
          horizontal scrolling. */}
      <div className="-mx-4 sm:mx-0 overflow-x-auto">
        <table className="w-full text-sm min-w-[360px]">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="text-left font-normal pb-2 pl-4 sm:pl-0">Description</th>
              <th className="text-right font-normal pb-2 w-10">Qty</th>
              <th className="text-right font-normal pb-2 w-20 sm:w-24">Price</th>
              <th className="text-right font-normal pb-2 w-24 hidden sm:table-cell">Tax</th>
              <th className="text-right font-normal pb-2 w-24 sm:w-28 pr-4 sm:pr-0">Subtotal</th>
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
      <td className="py-2.5 pl-4 sm:pl-0">
        <div className="flex items-center gap-2 min-w-0">
          {Icon ? (
            <Icon className="size-3.5 text-muted-foreground shrink-0" />
          ) : null}
          <span className="truncate">{line.description}</span>
        </div>
      </td>
      <td className="py-2.5 text-right font-mono tabular-nums">
        {line.quantity}
      </td>
      <td className="py-2.5 text-right font-mono tabular-nums">
        {formatMoneyCents(line.unit_price_cents)}
      </td>
      <td className="py-2.5 text-right font-mono tabular-nums text-muted-foreground hidden sm:table-cell">
        {formatMoneyCents(line.line_tax_cents)}
      </td>
      <td className="py-2.5 text-right font-mono tabular-nums pr-4 sm:pr-0">
        {formatMoneyCents(line.line_subtotal_cents + line.line_tax_cents)}
      </td>
      {editable ? (
        <td className="py-2.5 text-right">
          {/* opacity-0 hover-reveal becomes always-on at touch widths
              where there's no hover state to depend on. */}
          <button
            type="button"
            onClick={() => onRemove(line.id)}
            disabled={isRemoving}
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground/60 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 hover:bg-muted hover:text-destructive transition-all disabled:opacity-50"
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
    <div className="px-4 sm:px-6 py-5 border-t bg-muted/20">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-3">
        Add to this invoice
      </p>
      <div className="flex flex-col sm:flex-row sm:items-end sm:flex-wrap gap-2">
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

        <div className="w-full sm:flex-1 sm:min-w-[200px]">
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
          className="w-full sm:w-auto"
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
    <div className="px-4 sm:px-6 py-5 border-t bg-emerald-50/40">
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
        <div className="flex flex-col sm:flex-row sm:items-end sm:flex-wrap gap-2">
          <div className="w-full sm:flex-1 sm:min-w-[200px]">
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

          <div className="w-full sm:flex-1 sm:min-w-[200px]">
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
            className="w-full sm:w-auto"
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
  const hasGiftCardCredits = invoice.gift_card_credits_cents > 0;
  return (
    <div className="px-4 sm:px-6 py-5 flex justify-stretch sm:justify-end">
      <dl className="text-sm space-y-1.5 w-full sm:w-auto sm:min-w-[260px]">
        <SummaryRow label="Subtotal" value={formatMoneyCents(invoice.subtotal_cents)} />
        <SummaryRow label="Tax" value={formatMoneyCents(invoice.tax_cents)} />
        <div className="border-t border-border/60 pt-1.5 mt-1.5">
          <SummaryRow
            label="Total"
            value={formatMoneyCents(invoice.total_cents)}
            emphasis={!hasGiftCardCredits}
          />
        </div>
        {hasGiftCardCredits ? (
          <>
            <SummaryRow
              label="Gift cards applied"
              value={`-${formatMoneyCents(invoice.gift_card_credits_cents)}`}
              tone="positive"
            />
            <div className="border-t border-border/60 pt-1.5 mt-1.5">
              <SummaryRow
                label="Amount due"
                value={formatMoneyCents(invoice.amount_due_cents)}
                emphasis
              />
            </div>
          </>
        ) : null}
      </dl>
    </div>
  );
}

function SummaryRow({
  label,
  value,
  emphasis,
  tone,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
  tone?: 'positive';
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
          tone === 'positive' && 'text-emerald-700',
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
      <div className="px-4 sm:px-6 py-5 text-xs space-y-1 text-muted-foreground">
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
      <div className="px-4 sm:px-6 py-5 text-xs space-y-1 text-muted-foreground">
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

interface RedeemServiceOption {
  serviceId: number;
  name: string;
  /** Category name when this option came from a category credit. */
  note: string;
  remaining: number;
}

/** Flatten a subscription's credits into concrete redeemable services.
 *  A service credit yields one option; a category credit expands to
 *  every active service in that category. Direct service credits win
 *  over category-derived entries for the same service (mirrors the
 *  backend's redemption preference order). */
function buildRedeemServiceOptions(
  sub: Subscription | undefined,
  services: Service[],
): RedeemServiceOption[] {
  if (!sub) return [];
  const byServiceId = new Map<number, RedeemServiceOption>();
  for (const it of sub.items) {
    if (it.quantity_remaining <= 0) continue;
    if (it.item_type === 'category' && it.category != null) {
      for (const svc of services) {
        if (svc.category?.id !== it.category) continue;
        if (!byServiceId.has(svc.id)) {
          byServiceId.set(svc.id, {
            serviceId: svc.id,
            name: svc.name,
            note: it.category_name,
            remaining: it.quantity_remaining,
          });
        }
      }
    }
  }
  for (const it of sub.items) {
    if (it.quantity_remaining <= 0) continue;
    if (it.item_type === 'service' && it.service != null) {
      byServiceId.set(it.service, {
        serviceId: it.service,
        name: it.service_name,
        note: '',
        remaining: it.quantity_remaining,
      });
    }
  }
  return [...byServiceId.values()].sort((a, b) => a.name.localeCompare(b.name));
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
  const { data: allServices } = useServices({ activeOnly: true });
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
  const serviceOptions = buildRedeemServiceOptions(
    selectedSub,
    allServices ?? [],
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
    <div className="px-4 sm:px-6 py-5 border-t bg-violet-50/40">
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
        <div className="flex flex-col sm:flex-row sm:items-end sm:flex-wrap gap-2">
          <div className="w-full sm:flex-1 sm:min-w-[200px]">
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

          <div className="w-full sm:flex-1 sm:min-w-[200px]">
            <Select
              value={selectedServiceId}
              onValueChange={(v) => setSelectedServiceId(v ?? '')}
              disabled={!selectedSub}
            >
              <SelectTrigger>
                <SelectValue placeholder="Pick a service…" />
              </SelectTrigger>
              <SelectContent>
                {serviceOptions.length === 0 ? (
                  <div className="px-2 py-2 text-xs text-muted-foreground">
                    {selectedSub
                      ? 'No redeemable services this cycle.'
                      : 'Pick a membership first.'}
                  </div>
                ) : (
                  serviceOptions.map((opt) => (
                    <SelectItem
                      key={opt.serviceId}
                      value={String(opt.serviceId)}
                    >
                      <span className="flex items-center justify-between gap-3 w-full">
                        <span className="truncate">
                          {opt.name}
                          {opt.note ? (
                            <span className="text-muted-foreground">
                              {' '}
                              · {opt.note}
                            </span>
                          ) : null}
                        </span>
                        <span className="text-xs text-violet-700 shrink-0">
                          {opt.remaining} left
                        </span>
                      </span>
                    </SelectItem>
                  ))
                )}
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
            className="w-full sm:w-auto"
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

// ── Gift card sale ──────────────────────────────────────────────────

function SellGiftCardPanel({ invoice }: { invoice: Invoice }) {
  const [open, setOpen] = useState(false);
  const [valueDollars, setValueDollars] = useState('');
  const [recipientName, setRecipientName] = useState('');
  const [recipientEmail, setRecipientEmail] = useState('');
  const [useCustomer, setUseCustomer] = useState(true);
  const sale = useAddGiftCardSale(invoice.id);

  // Default to "issue to the customer on this invoice." Operator can
  // toggle off and type a different recipient name (gift to a non-
  // customer). Recipient FK isn't a search picker in v1 — the
  // common case is "this customer pays for their own card or buys
  // it as a gift for someone outside the system."
  const customerName = invoice.customer.full_name;

  const reset = () => {
    setValueDollars('');
    setRecipientName('');
    setRecipientEmail('');
    setUseCustomer(true);
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cents = centsFromDollars(valueDollars);
    if (cents <= 0) {
      toast.error('Enter a dollar amount.');
      return;
    }
    if (!useCustomer && !recipientName.trim()) {
      toast.error('Recipient name required for non-customer gifts.');
      return;
    }

    sale.mutate(
      {
        value_cents: cents,
        recipient_customer_id: useCustomer ? invoice.customer.id : undefined,
        recipient_name: useCustomer ? undefined : recipientName.trim(),
        recipient_email: recipientEmail.trim() || undefined,
      },
      {
        onSuccess: () => {
          toast.success(`Gift card added · $${(cents / 100).toFixed(2)}`);
          reset();
          setOpen(false);
        },
        onError: (err) =>
          toast.error(
            invoiceErrorMessage(err, "Couldn't sell that card."),
          ),
      },
    );
  };

  if (!open) {
    return (
      <div className="px-4 sm:px-6 py-4 border-t bg-emerald-50/30">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-2 text-sm text-emerald-900 hover:text-emerald-950 transition-colors"
        >
          <Gift className="size-4" />
          Sell a gift card
          <ChevronDown className="size-3.5" />
        </button>
      </div>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="px-4 sm:px-6 py-5 border-t bg-emerald-50/30 space-y-3"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-emerald-900 font-medium flex items-center gap-1.5">
            <Gift className="size-3.5" />
            Sell a gift card
          </p>
          <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
            Card activates when the customer pays this invoice.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
          aria-label="Cancel"
        >
          <X className="size-3.5" />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-end">
        <div>
          <label
            htmlFor="gc-value"
            className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium"
          >
            Card value
          </label>
          <div className="relative mt-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
              $
            </span>
            <Input
              id="gc-value"
              type="text"
              inputMode="decimal"
              placeholder="0.00"
              className="pl-7"
              value={valueDollars}
              onChange={(e) => setValueDollars(e.target.value)}
            />
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
            Issue to
          </p>
          <div className="inline-flex items-center gap-0.5 rounded-md border bg-card p-0.5 w-full">
            <button
              type="button"
              onClick={() => setUseCustomer(true)}
              className={cn(
                'flex-1 px-3 h-8 rounded text-xs transition-colors truncate',
                useCustomer
                  ? 'bg-foreground text-background font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {customerName}
            </button>
            <button
              type="button"
              onClick={() => setUseCustomer(false)}
              className={cn(
                'flex-1 px-3 h-8 rounded text-xs transition-colors',
                !useCustomer
                  ? 'bg-foreground text-background font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              Someone else
            </button>
          </div>
        </div>
      </div>

      {!useCustomer ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label
              htmlFor="gc-recipient-name"
              className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium"
            >
              Recipient name
            </label>
            <Input
              id="gc-recipient-name"
              className="mt-1"
              value={recipientName}
              onChange={(e) => setRecipientName(e.target.value)}
              placeholder="e.g. Aunt Mary"
            />
          </div>
          <div>
            <label
              htmlFor="gc-recipient-email"
              className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium"
            >
              Recipient email <span className="text-muted-foreground/70 normal-case">(optional)</span>
            </label>
            <Input
              id="gc-recipient-email"
              type="email"
              className="mt-1"
              value={recipientEmail}
              onChange={(e) => setRecipientEmail(e.target.value)}
              placeholder="mary@example.com"
            />
          </div>
        </div>
      ) : null}

      <div className="flex justify-stretch sm:justify-end pt-2">
        <Button type="submit" disabled={sale.isPending} className="w-full sm:w-auto">
          {sale.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Plus className="size-4" />
          )}
          Add to invoice
        </Button>
      </div>
    </form>
  );
}

// ── Apply gift card (redemption at checkout) ───────────────────────

function ApplyGiftCardPanel({ invoice }: { invoice: Invoice }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState('');
  const [amountDollars, setAmountDollars] = useState('');
  const [lookedUp, setLookedUp] = useState<{
    code: string;
    balance_cents: number;
    balance_dollars: string;
    is_redeemable: boolean;
  } | null>(null);
  const lookup = useGiftCardLookup();
  const apply = useApplyGiftCard(invoice.id);
  const reverse = useReverseGiftCardRedemption(invoice.id);

  const reset = () => {
    setCode('');
    setAmountDollars('');
    setLookedUp(null);
  };

  const onLookup = () => {
    const trimmed = code.trim().toUpperCase();
    if (!trimmed) return;
    lookup.mutate(
      { code: trimmed },
      {
        onSuccess: (card) => {
          setLookedUp({
            code: card.code,
            balance_cents: card.balance_cents,
            balance_dollars: card.balance_dollars,
            is_redeemable: card.is_redeemable,
          });
          // Default to applying the smaller of card balance and amount due.
          const default_cents = Math.min(
            card.balance_cents,
            invoice.amount_due_cents,
          );
          setAmountDollars((default_cents / 100).toFixed(2));
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 404) {
            toast.error('No card with that code.');
          } else {
            toast.error('Lookup failed.');
          }
        },
      },
    );
  };

  const onApply = () => {
    if (!lookedUp) return;
    const cents = centsFromDollars(amountDollars);
    if (cents <= 0) {
      toast.error('Enter an amount.');
      return;
    }
    apply.mutate(
      { code: lookedUp.code, amount_cents: cents },
      {
        onSuccess: () => {
          toast.success(`$${(cents / 100).toFixed(2)} applied`);
          reset();
        },
        onError: (err) =>
          toast.error(
            invoiceErrorMessage(err, "Couldn't apply this card."),
          ),
      },
    );
  };

  // Find applied gift card ledger rows on this invoice so the
  // operator can see what's been credited + reverse if needed.
  // NOTE: the invoice payload doesn't currently include nested
  // ledger entries. For v1 we just show the rolling total from
  // `gift_card_credits_cents`; reversal requires drilling into the
  // gift card's detail page (where the ledger is visible).

  if (!open) {
    return (
      <div className="px-4 sm:px-6 py-4 border-t bg-emerald-50/30">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-2 text-sm text-emerald-900 hover:text-emerald-950 transition-colors"
        >
          <Gift className="size-4" />
          Apply a gift card
          {invoice.gift_card_credits_cents > 0 ? (
            <span className="text-xs text-muted-foreground">
              · ${(invoice.gift_card_credits_cents / 100).toFixed(2)} applied so far
            </span>
          ) : null}
          <ChevronDown className="size-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="px-4 sm:px-6 py-5 border-t bg-emerald-50/30 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-emerald-900 font-medium flex items-center gap-1.5">
            <Gift className="size-3.5" />
            Apply gift card
          </p>
          <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
            Customer presents the code; balance applies as a payment
            tender. The remaining amount due covers via the
            payment method at close.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
          aria-label="Cancel"
        >
          <X className="size-3.5" />
        </button>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-end sm:flex-wrap gap-2">
        <div className="w-full sm:flex-1 sm:min-w-[200px]">
          <label
            htmlFor="agc-code"
            className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium"
          >
            Card code
          </label>
          <Input
            id="agc-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="GC-XXXX-YYYY"
            className="font-mono uppercase mt-1"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                onLookup();
              }
            }}
            disabled={!!lookedUp}
          />
        </div>
        {!lookedUp ? (
          <Button
            type="button"
            onClick={onLookup}
            disabled={lookup.isPending || !code.trim()}
            variant="outline"
            className="w-full sm:w-auto"
          >
            {lookup.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : null}
            Look up
          </Button>
        ) : null}
      </div>

      {lookedUp ? (
        <>
          <div className="rounded-md bg-card border px-3 py-2 flex items-center justify-between gap-3 text-sm">
            <span className="text-muted-foreground">
              {lookedUp.code} · balance
            </span>
            <span className="font-mono font-medium tabular-nums">
              {lookedUp.balance_dollars}
            </span>
          </div>

          {!lookedUp.is_redeemable ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              This card isn&rsquo;t redeemable (voided, expired, or zero balance).
            </div>
          ) : (
            <div className="flex flex-col sm:flex-row sm:items-end sm:flex-wrap gap-2">
              <div className="w-full sm:flex-1 sm:min-w-[200px]">
                <label
                  htmlFor="agc-amount"
                  className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium"
                >
                  Apply how much
                </label>
                <div className="relative mt-1">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                    $
                  </span>
                  <Input
                    id="agc-amount"
                    type="text"
                    inputMode="decimal"
                    className="pl-7"
                    value={amountDollars}
                    onChange={(e) => setAmountDollars(e.target.value)}
                  />
                </div>
                <p className="text-[11px] text-muted-foreground mt-1">
                  Amount due on this invoice: ${(invoice.amount_due_cents / 100).toFixed(2)}
                </p>
              </div>
              <Button
                type="button"
                onClick={onApply}
                disabled={apply.isPending}
                className="w-full sm:w-auto"
              >
                {apply.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="size-4" />
                )}
                Apply
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={reset}
                disabled={apply.isPending}
                className="w-full sm:w-auto"
              >
                Different card
              </Button>
            </div>
          )}
        </>
      ) : null}

      {invoice.gift_card_credits_cents > 0 ? (
        <div className="text-xs text-muted-foreground pt-3 border-t">
          <span className="font-medium text-foreground">
            ${(invoice.gift_card_credits_cents / 100).toFixed(2)}
          </span>{' '}
          applied to this invoice via gift cards. To reverse a
          specific redemption, open the card&rsquo;s detail page and
          use the ledger.
          {/* Suppress unused-warning for the reverse hook — kept on
              hand in case future UX needs inline reversal. */}
          <span hidden>{String(reverse.isPending)}</span>
        </div>
      ) : null}
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
      <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-center gap-2">
        <Button type="button" onClick={onPay} size="lg" className="w-full sm:w-auto">
          <CreditCard className="size-4" />
          Take payment · {formatMoneyCents(invoice.total_cents)}
        </Button>
        {canVoid ? (
          <Button
            type="button"
            variant="outline"
            onClick={onVoid}
            className="w-full sm:w-auto text-destructive hover:text-destructive"
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
      <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-center gap-3">
        <Button type="button" variant="outline" onClick={onReopen} className="w-full sm:w-auto">
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
          toast.success(
            invoice.appointment
              ? 'Payment recorded · appointment marked completed'
              : 'Payment recorded',
            { icon: <CheckCircle2 className="size-4" /> },
          );
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
      <CardContent className="p-4 sm:p-6 space-y-4">
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

        <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-end gap-2 pt-2">
          <Button type="button" variant="outline" disabled={close.isPending} onClick={onCancel} className="w-full sm:w-auto">
            Cancel
          </Button>
          <Button type="button" disabled={close.isPending} onClick={submit} size="lg" className="w-full sm:w-auto sm:size-default">
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
          toast.success(
            invoice.appointment
              ? 'Invoice reopened · appointment back to checked-in'
              : 'Invoice reopened',
          );
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
      <CardContent className="p-4 sm:p-6 space-y-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Reopen invoice
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            {invoice.appointment
              ? 'Reverts the appointment to checked-in so payment can be re-collected or amended.'
              : 'Reopens the invoice so payment can be re-collected or amended.'}{' '}
            The reason is recorded in the audit log.
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
        <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-end gap-2 pt-2">
          <Button type="button" variant="outline" disabled={reopen.isPending} onClick={onCancel} className="w-full sm:w-auto">
            Cancel
          </Button>
          <Button type="button" disabled={reopen.isPending || !trimmed} onClick={submit} className="w-full sm:w-auto">
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
      <CardContent className="p-4 sm:p-6 space-y-4">
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
        <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-end gap-2 pt-2">
          <Button type="button" variant="outline" disabled={voidInv.isPending} onClick={onCancel} className="w-full sm:w-auto">
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={voidInv.isPending || !trimmed}
            onClick={submit}
            className="w-full sm:w-auto"
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
    <div className="px-4 sm:px-8 py-6 sm:py-10 max-w-3xl mx-auto">
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
    <div className="px-4 sm:px-8 py-6 sm:py-10 max-w-3xl mx-auto">
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
    <div className="px-4 sm:px-8 py-6 sm:py-10 max-w-3xl mx-auto">
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

