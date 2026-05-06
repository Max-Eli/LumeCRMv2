/**
 * `/marketing/unsubscribe/[token]` — public one-click unsubscribe.
 *
 * Lives in the `(book)` route group because it's no-auth, no-CSRF,
 * tokenized — same posture as the booking-manage flow. The token
 * is the security boundary; visiting the URL doesn't leak the
 * customer's identity to anyone but them.
 *
 * Two states:
 *   - **pending**: GET shows "Click to unsubscribe from {Spa} marketing
 *     emails." POST flips the suppression flag.
 *   - **unsubscribed**: confirmed state. Idempotent — refreshing
 *     stays in the unsubscribed view.
 *
 * No design system styling beyond what the public booking layout
 * already provides; this is a transactional page that the
 * customer sees once.
 */

'use client';

import { Ban, CheckCircle2, Loader2, MailX, MessageSquareOff, XCircle } from 'lucide-react';
import { use, useState } from 'react';

import { ApiError } from '@/lib/api';

interface UnsubscribePayload {
  tenant_name: string;
  channel: 'email' | 'sms';
  channel_label: string;
  customer_first_name: string;
  is_unsubscribed: boolean;
  unsubscribed_at: string | null;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function fetchUnsub(token: string): Promise<UnsubscribePayload> {
  const res = await fetch(`${API_URL}/api/marketing/unsubscribe/${token}/`);
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // empty
    }
    throw new ApiError(res.status, body, `Unsubscribe lookup failed: ${res.status}`);
  }
  return res.json();
}

async function confirmUnsub(token: string): Promise<UnsubscribePayload> {
  const res = await fetch(`${API_URL}/api/marketing/unsubscribe/${token}/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // empty
    }
    throw new ApiError(res.status, body, `Unsubscribe failed: ${res.status}`);
  }
  return res.json();
}

export default function UnsubscribePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);

  const [state, setState] = useState<'loading' | 'pending' | 'done' | 'notfound' | 'error'>('loading');
  const [data, setData] = useState<UnsubscribePayload | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Initial GET on mount.
  if (state === 'loading') {
    fetchUnsub(token)
      .then((d) => {
        setData(d);
        setState(d.is_unsubscribed ? 'done' : 'pending');
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setState('notfound');
        } else {
          setState('error');
        }
      });
  }

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      const updated = await confirmUnsub(token);
      setData(updated);
      setState('done');
    } catch {
      setState('error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-12">
      <div className="max-w-md w-full">
        {state === 'loading' ? (
          <div className="text-center">
            <Loader2 className="size-6 animate-spin text-stone-500 mx-auto" />
          </div>
        ) : state === 'notfound' ? (
          <div className="rounded-lg border border-stone-200 bg-white p-6 text-center">
            <XCircle className="size-7 text-stone-700 mx-auto mb-3" />
            <h1 className="font-serif text-xl font-semibold tracking-tight">
              Link not recognized
            </h1>
            <p className="text-sm text-stone-600 mt-2 leading-relaxed">
              This unsubscribe link doesn&rsquo;t match any record we have. If
              you&rsquo;re trying to opt out of marketing from a spa, please
              reach out to them directly.
            </p>
          </div>
        ) : state === 'error' ? (
          <div className="rounded-lg border border-stone-200 bg-white p-6 text-center">
            <XCircle className="size-7 text-red-600 mx-auto mb-3" />
            <h1 className="font-serif text-xl font-semibold tracking-tight">
              Something went wrong
            </h1>
            <p className="text-sm text-stone-600 mt-2">
              Please try again in a few minutes.
            </p>
          </div>
        ) : state === 'done' && data ? (
          <DoneView data={data} />
        ) : state === 'pending' && data ? (
          <PendingView
            data={data}
            submitting={submitting}
            onConfirm={handleConfirm}
          />
        ) : null}
      </div>
    </main>
  );
}

function PendingView({
  data,
  submitting,
  onConfirm,
}: {
  data: UnsubscribePayload;
  submitting: boolean;
  onConfirm: () => void;
}) {
  const Icon = data.channel === 'email' ? MailX : MessageSquareOff;
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="size-10 rounded-full bg-stone-100 inline-flex items-center justify-center">
          <Icon className="size-5 text-stone-600" />
        </div>
        <div>
          <h1 className="font-serif text-lg font-semibold tracking-tight">
            Unsubscribe from {data.channel_label.toLowerCase()}
          </h1>
          <p className="text-xs text-stone-500">{data.tenant_name}</p>
        </div>
      </div>

      <p className="text-sm text-stone-700 leading-relaxed mb-4">
        {data.customer_first_name ? `Hi ${data.customer_first_name} — ` : ''}
        click below to stop receiving marketing {data.channel_label.toLowerCase()} from{' '}
        <span className="font-medium text-stone-900">{data.tenant_name}</span>.
        Booking confirmations and other transactional messages will keep
        coming as usual.
      </p>

      <button
        type="button"
        onClick={onConfirm}
        disabled={submitting}
        className="w-full inline-flex items-center justify-center gap-2 rounded-md bg-stone-900 text-white hover:bg-stone-800 px-4 py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
      >
        {submitting ? <Loader2 className="size-4 animate-spin" /> : <Ban className="size-4" />}
        {submitting ? 'Unsubscribing…' : `Confirm unsubscribe`}
      </button>

      <p className="text-[11px] text-stone-500 mt-3 text-center leading-relaxed">
        This action records the unsubscribe permanently. To opt back in, you can
        ask the spa directly the next time you book.
      </p>
    </div>
  );
}

function DoneView({ data }: { data: UnsubscribePayload }) {
  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-6">
      <div className="flex items-center gap-3 mb-3">
        <div className="size-10 rounded-full bg-emerald-100 inline-flex items-center justify-center">
          <CheckCircle2 className="size-5 text-emerald-700" />
        </div>
        <div>
          <h1 className="font-serif text-lg font-semibold tracking-tight text-emerald-900">
            You&rsquo;re unsubscribed
          </h1>
          <p className="text-xs text-emerald-800">{data.tenant_name}</p>
        </div>
      </div>
      <p className="text-sm text-emerald-900 leading-relaxed">
        We&rsquo;ve removed you from the marketing {data.channel_label.toLowerCase()} list for{' '}
        <span className="font-medium">{data.tenant_name}</span>. You won&rsquo;t
        receive promotional messages on this channel anymore.
      </p>
      <p className="text-xs text-emerald-800 mt-3">
        Booking confirmations and other transactional messages will continue —
        these aren&rsquo;t marketing, and you opted into them when you booked.
      </p>
    </div>
  );
}
