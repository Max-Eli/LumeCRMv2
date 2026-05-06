/**
 * `/marketing/audiences/new` — create a new customer segment.
 *
 * Two-pane layout:
 *   - Left: name + description + filter spec editor (per-dimension
 *     toggle + value input)
 *   - Right: live preview card showing total + per-channel
 *     eligibility counts. Updates as the operator changes filters.
 *
 * The preview hits `/api/marketing/audiences/<id>/preview/` only
 * after save — until then we build a temporary audience to do the
 * preview against. v1 simplification: save the audience first
 * (creates it), then immediately fetch the preview, then offer to
 * either go to the audience detail page or create another. This
 * is one extra request than the "preview-without-save" alternative
 * but the code surface is half the size.
 */

'use client';

import {
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  Loader2,
  Mail,
  MessageSquare,
  Users,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  type AudienceFilterSpec,
  useCreateAudience,
  usePreviewAudience,
} from '@/lib/marketing';
import { cn } from '@/lib/utils';

interface FormState {
  name: string;
  description: string;
  // Each dimension toggle is independent — UI binds the bool to
  // whether the spec key gets included in the final POST.
  use_last_visit_within: boolean;
  last_visit_within_days: number;
  use_last_visit_more_than: boolean;
  last_visit_more_than_days: number;
  use_created_within: boolean;
  created_within_days: number;
  use_email_opt_in: boolean;
  email_opt_in_value: boolean;
  use_sms_opt_in: boolean;
  sms_opt_in_value: boolean;
}

const INITIAL: FormState = {
  name: '',
  description: '',
  use_last_visit_within: false,
  last_visit_within_days: 30,
  use_last_visit_more_than: false,
  last_visit_more_than_days: 90,
  use_created_within: false,
  created_within_days: 30,
  use_email_opt_in: false,
  email_opt_in_value: true,
  use_sms_opt_in: false,
  sms_opt_in_value: true,
};

export default function NewAudiencePage() {
  const router = useRouter();
  const create = useCreateAudience();
  const [state, setState] = useState<FormState>(INITIAL);
  const [error, setError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<number | null>(null);

  const previewMutation = usePreviewAudience(createdId ?? 0);

  const buildFilterSpec = (): AudienceFilterSpec => {
    const spec: AudienceFilterSpec = {};
    if (state.use_last_visit_within) {
      spec.last_visit_within_days = state.last_visit_within_days;
    }
    if (state.use_last_visit_more_than) {
      spec.last_visit_more_than_days = state.last_visit_more_than_days;
    }
    if (state.use_created_within) {
      spec.created_within_days = state.created_within_days;
    }
    if (state.use_email_opt_in) {
      spec.email_marketing_opt_in = state.email_opt_in_value;
    }
    if (state.use_sms_opt_in) {
      spec.sms_marketing_opt_in = state.sms_opt_in_value;
    }
    return spec;
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!state.name.trim()) {
      setError('Give your audience a name.');
      return;
    }
    create.mutate(
      {
        name: state.name.trim(),
        description: state.description.trim(),
        filter_spec: buildFilterSpec(),
      },
      {
        onSuccess: (audience) => {
          toast.success('Audience created');
          setCreatedId(audience.id);
          // Auto-fire the preview so the operator sees the channel
          // breakdown without an extra click.
          previewMutation.mutate();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as Record<string, unknown>;
            const firstKey = Object.keys(body)[0];
            if (firstKey === 'name' && Array.isArray(body[firstKey])) {
              setError(String((body[firstKey] as string[])[0]));
              return;
            }
            if (firstKey === 'filter_spec' && typeof body[firstKey] === 'object') {
              const spec = body[firstKey] as Record<string, unknown>;
              const innerKey = Object.keys(spec)[0];
              setError(`${innerKey}: ${String(spec[innerKey])}`);
              return;
            }
            if (typeof body.detail === 'string') {
              setError(body.detail);
              return;
            }
          }
          setError("Couldn't create audience. Please try again.");
        },
      },
    );
  };

  // Once created + preview lands, show the success screen. Operator
  // chooses to view the audience detail or build another.
  if (createdId !== null && previewMutation.data) {
    const p = previewMutation.data;
    return (
      <div className="px-10 py-10 max-w-3xl">
        <SuccessState
          audienceId={createdId}
          totalCount={p.total_count}
          emailEligibleCount={p.email_eligible_count}
          smsEligibleCount={p.sms_eligible_count}
          onCreateAnother={() => {
            setCreatedId(null);
            setState(INITIAL);
            setError(null);
          }}
        />
      </div>
    );
  }

  return (
    <div className="px-10 py-10 max-w-7xl space-y-6">
      <Link
        href="/marketing/audiences"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="size-3.5" />
        Back to audiences
      </Link>

      <PageHeader
        title="New audience"
        description="Describe the segment with one or more filters. We'll show you a live count + per-channel breakdown when you save."
      />

      <form onSubmit={handleSave} className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6">
        {/* Left — form */}
        <div className="space-y-6">
          <section className="rounded-lg border bg-card p-5 space-y-4">
            <h2 className="font-serif text-base font-semibold tracking-tight">
              Identity
            </h2>
            <Field>
              <FieldLabel>Name</FieldLabel>
              <Input
                value={state.name}
                onChange={(e) => setState((s) => ({ ...s, name: e.target.value }))}
                placeholder="VIP customers"
                maxLength={100}
              />
            </Field>
            <Field>
              <FieldLabel>Description (optional)</FieldLabel>
              <Input
                value={state.description}
                onChange={(e) => setState((s) => ({ ...s, description: e.target.value }))}
                placeholder="Top-spend customers tagged VIP for premium offers"
                maxLength={200}
              />
            </Field>
          </section>

          <section className="rounded-lg border bg-card p-5 space-y-4">
            <h2 className="font-serif text-base font-semibold tracking-tight">
              Filters
            </h2>
            <p className="text-xs text-muted-foreground -mt-2">
              All filters are AND&rsquo;d together — a customer must match every
              enabled filter to be included.
            </p>

            <DimensionRow
              label="Visited recently"
              description="Customer had a completed appointment in the last N days."
              checked={state.use_last_visit_within}
              onCheck={(v) => setState((s) => ({ ...s, use_last_visit_within: v }))}
            >
              <DaysInput
                value={state.last_visit_within_days}
                onChange={(v) => setState((s) => ({ ...s, last_visit_within_days: v }))}
                disabled={!state.use_last_visit_within}
              />
            </DimensionRow>

            <DimensionRow
              label="Win-back (no visit in N days)"
              description="No completed appointment in N days OR never visited at all."
              checked={state.use_last_visit_more_than}
              onCheck={(v) => setState((s) => ({ ...s, use_last_visit_more_than: v }))}
            >
              <DaysInput
                value={state.last_visit_more_than_days}
                onChange={(v) => setState((s) => ({ ...s, last_visit_more_than_days: v }))}
                disabled={!state.use_last_visit_more_than}
              />
            </DimensionRow>

            <DimensionRow
              label="Recently signed up"
              description="Customer record created in the last N days."
              checked={state.use_created_within}
              onCheck={(v) => setState((s) => ({ ...s, use_created_within: v }))}
            >
              <DaysInput
                value={state.created_within_days}
                onChange={(v) => setState((s) => ({ ...s, created_within_days: v }))}
                disabled={!state.use_created_within}
              />
            </DimensionRow>

            <DimensionRow
              label="Email marketing consent"
              description="Filter to customers who explicitly opted in (or out) of marketing email."
              checked={state.use_email_opt_in}
              onCheck={(v) => setState((s) => ({ ...s, use_email_opt_in: v }))}
            >
              <select
                disabled={!state.use_email_opt_in}
                value={state.email_opt_in_value ? 'in' : 'out'}
                onChange={(e) =>
                  setState((s) => ({ ...s, email_opt_in_value: e.target.value === 'in' }))
                }
                className="h-8 rounded-md border bg-card px-2 text-xs disabled:opacity-50"
              >
                <option value="in">Opted in</option>
                <option value="out">Opted out</option>
              </select>
            </DimensionRow>

            <DimensionRow
              label="SMS marketing consent"
              description="Filter to customers who explicitly opted in (or out) of marketing SMS."
              checked={state.use_sms_opt_in}
              onCheck={(v) => setState((s) => ({ ...s, use_sms_opt_in: v }))}
            >
              <select
                disabled={!state.use_sms_opt_in}
                value={state.sms_opt_in_value ? 'in' : 'out'}
                onChange={(e) =>
                  setState((s) => ({ ...s, sms_opt_in_value: e.target.value === 'in' }))
                }
                className="h-8 rounded-md border bg-card px-2 text-xs disabled:opacity-50"
              >
                <option value="in">Opted in</option>
                <option value="out">Opted out</option>
              </select>
            </DimensionRow>
          </section>

          {error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : null}

          <div className="flex items-center gap-2">
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : null}
              Save audience
            </Button>
            <Link
              href="/marketing/audiences"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Cancel
            </Link>
          </div>
        </div>

        {/* Right — live preview placeholder. Real preview shows after save. */}
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="rounded-lg border border-dashed bg-muted/20 p-5">
            <div className="flex items-center gap-2 mb-2">
              <Users className="size-4 text-muted-foreground" />
              <h3 className="text-sm font-semibold tracking-tight">Live preview</h3>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Save your audience to see the total + per-channel eligibility
              count. After saving, you can refresh the count any time as your
              customer base grows.
            </p>
          </div>
        </aside>
      </form>
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function DimensionRow({
  label,
  description,
  checked,
  onCheck,
  children,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheck: (v: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-2 border-t first:border-t-0 first:pt-0">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onCheck(e.target.checked)}
        className="mt-1 size-4 rounded border-input"
      />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-foreground">{label}</div>
        <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
          {description}
        </p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function DaysInput({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <Input
        type="number"
        inputMode="numeric"
        min={1}
        max={3650}
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || 1)}
        disabled={disabled}
        className="w-20 h-8 text-xs tabular-nums disabled:opacity-50"
      />
      <span className={cn('text-xs', disabled ? 'text-muted-foreground/60' : 'text-muted-foreground')}>
        days
      </span>
    </div>
  );
}

function SuccessState({
  audienceId,
  totalCount,
  emailEligibleCount,
  smsEligibleCount,
  onCreateAnother,
}: {
  audienceId: number;
  totalCount: number;
  emailEligibleCount: number;
  smsEligibleCount: number;
  onCreateAnother: () => void;
}) {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 flex items-start gap-3">
        <CheckCircle2 className="size-5 text-emerald-600 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-emerald-900">
            Audience saved
          </p>
          <p className="text-xs text-emerald-800 mt-0.5">
            Here&rsquo;s how many customers match — and how many you can
            actually reach through each channel after applying TCPA + CAN-SPAM
            consent gates.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Stat
          icon={Users}
          label="Total in segment"
          value={totalCount}
          sub="All customers matching the filter"
        />
        <Stat
          icon={Mail}
          label="Email-eligible"
          value={emailEligibleCount}
          sub="Opted-in + not suppressed + has email"
          tone="email"
        />
        <Stat
          icon={MessageSquare}
          label="SMS-eligible"
          value={smsEligibleCount}
          sub="Opted-in + not suppressed + has phone"
          tone="sms"
        />
      </div>

      <div className="flex items-center gap-2">
        <Link
          href={`/marketing/audiences/${audienceId}`}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 px-4 h-9 text-sm font-medium transition-colors"
        >
          View audience
          <ArrowRight className="size-4" />
        </Link>
        <Button type="button" variant="outline" onClick={onCreateAnother}>
          Create another
        </Button>
      </div>
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  sub,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  sub: string;
  tone?: 'email' | 'sms';
}) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className="size-3.5 text-muted-foreground" />
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
          {label}
        </p>
      </div>
      <p
        className={cn(
          'text-2xl font-semibold tabular-nums tracking-tight',
          tone === 'email' && 'text-blue-700',
          tone === 'sms' && 'text-emerald-700',
        )}
      >
        {value}
      </p>
      <p className="text-[11px] text-muted-foreground mt-0.5">{sub}</p>
    </div>
  );
}
