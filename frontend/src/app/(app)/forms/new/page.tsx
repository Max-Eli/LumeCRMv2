/**
 * `/forms/new` — create a new form template. Owner-only.
 *
 * Two-step flow:
 *
 *   1. **Picker** (default landing). Operator chooses a starter
 *      template (Botox consent, intake, etc.) or "Blank form."
 *      Starter content lives in `lib/form-template-starters.ts`
 *      — no DB seeding, no per-tenant pollution.
 *   2. **Builder** (after picking). The shared `<FormTemplateBuilder>`
 *      pre-filled with the chosen starter's schema. A yellow
 *      disclaimer banner reminds the operator that starters are
 *      structural templates and need legal / medical-director review
 *      before activation.
 *
 * URL state: `?starter={id}` controls which starter is active.
 * `?starter=blank` (or `?type=` set) goes straight to an empty
 * builder. Direct links to `/forms/new?starter=botox-consent` land
 * on the pre-filled builder — useful when surfacing starters from
 * elsewhere (empty-state CTAs on /forms list).
 */

'use client';

import { ArrowLeft, ClipboardCheck, ClipboardList, FileText, TriangleAlert } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  FORM_TYPE_LABELS,
  type FormType,
  useCreateFormTemplate,
} from '@/lib/form-templates';
import {
  type FormTemplateStarter,
  getStarter,
  startersByType,
} from '@/lib/form-template-starters';
import { cn } from '@/lib/utils';

import {
  FormTemplateBuilder,
  type FormTemplateBuilderValues,
} from '../_components/form-template-builder';

export default function NewFormTemplatePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const me = useCurrentMembership();
  const create = useCreateFormTemplate();

  const starterId = searchParams.get('starter');
  const initialType = searchParams.get('type') as FormType | null;
  const initialFormType: FormType | undefined =
    initialType === 'intake' || initialType === 'consent' ? initialType : undefined;

  // Picker step is the default landing. Skipped when `?starter=` is
  // set (operator picked one) OR when `?type=` is set (clicked an
  // empty-state CTA on the list page that wants a blank of that type).
  const showPicker = !starterId && !initialFormType;
  const starter = starterId && starterId !== 'blank' ? getStarter(starterId) : null;

  if (me && me.role !== 'owner') {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <PageHeader
          title="New form"
          back={{ href: '/forms', label: 'Back to forms' }}
        />
        <p className="text-sm text-destructive">Only owners can create forms.</p>
      </div>
    );
  }

  if (showPicker) {
    return <StarterPicker />;
  }

  const handleSubmit = (values: FormTemplateBuilderValues) => {
    create.mutate(
      {
        name: values.name,
        description: values.description,
        form_type: values.form_type,
        recurrence: values.recurrence,
        is_active: values.is_active,
        schema: values.schema,
        set_service_ids: values.form_type === 'consent' ? values.service_ids : [],
      },
      {
        onSuccess: (template) => {
          toast.success(`${template.name} created`);
          router.push(`/forms/${template.id}`);
        },
        onError: (err) => surfaceError(err),
      },
    );
  };

  // Pre-fill the builder from the starter (if any), else use a blank
  // template scoped to the requested form_type.
  const initialValues: Partial<FormTemplateBuilderValues> | undefined = starter
    ? {
        name: starter.name,
        description: '',
        form_type: starter.form_type,
        recurrence: starter.recurrence,
        is_active: true,
        schema: starter.schema,
        service_ids: [],
      }
    : undefined;

  return (
    <div className="max-w-6xl px-10 py-10 space-y-6">
      <PageHeader
        title={starter ? `New form · ${starter.name}` : 'New form'}
        description={
          starter
            ? "Customize the starter for your spa, then save."
            : 'Set up a template that gets auto-assigned to client appointments.'
        }
        back={{
          href: starter ? '/forms/new' : '/forms',
          label: starter ? 'Back to starters' : 'Back to forms',
        }}
      />

      {starter ? <StarterDisclaimerBanner /> : null}

      <FormTemplateBuilder
        initialValues={initialValues}
        initialFormType={initialFormType}
        onSubmit={handleSubmit}
        onCancel={() => router.push(starter ? '/forms/new' : '/forms')}
        isSubmitting={create.isPending}
      />
    </div>
  );
}

// ── Starter picker ──────────────────────────────────────────────────

function StarterPicker() {
  const grouped = startersByType();
  return (
    <div className="max-w-5xl px-10 py-10 space-y-8">
      <PageHeader
        title="New form"
        description="Start from a template or build your own. Templates are structural starters — review and customize the language before activating."
        back={{ href: '/forms', label: 'Back to forms' }}
      />

      <BlankFormCard />

      <PickerSection
        type="intake"
        starters={grouped.intake}
        icon={<ClipboardList className="size-4 text-muted-foreground" />}
        description="Asked once on a client's first appointment ever."
      />
      <PickerSection
        type="consent"
        starters={grouped.consent}
        icon={<ClipboardCheck className="size-4 text-muted-foreground" />}
        description="Mapped to specific services and assigned per appointment."
      />

      <StarterDisclaimerBanner inline />
    </div>
  );
}

function BlankFormCard() {
  return (
    <Link
      href="/forms/new?starter=blank"
      className="block group rounded-lg border bg-card p-4 hover:border-foreground/30 transition-colors"
    >
      <div className="flex items-center gap-3">
        <div className="inline-flex size-10 items-center justify-center rounded-md border bg-background">
          <FileText className="size-5 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">Start from blank</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Build a custom form from scratch — pick the type and add your
            own fields.
          </p>
        </div>
        <ArrowLeft className="size-4 text-muted-foreground/60 rotate-180 group-hover:text-foreground transition-colors" aria-hidden />
      </div>
    </Link>
  );
}

function PickerSection({
  type,
  starters,
  icon,
  description,
}: {
  type: FormType;
  starters: FormTemplateStarter[];
  icon: React.ReactNode;
  description: string;
}) {
  return (
    <section>
      <header className="mb-3">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-serif text-base font-semibold tracking-tight">
            {FORM_TYPE_LABELS[type]} starters
          </h2>
        </div>
        <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
          {description}
        </p>
      </header>
      <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {starters.map((starter) => (
          <StarterCard key={starter.id} starter={starter} />
        ))}
      </ul>
    </section>
  );
}

function StarterCard({ starter }: { starter: FormTemplateStarter }) {
  const fieldCount = starter.schema.fields.length;
  const Icon = starter.form_type === 'intake' ? ClipboardList : ClipboardCheck;
  return (
    <li>
      <Link
        href={`/forms/new?starter=${starter.id}`}
        className="block group rounded-lg border bg-card p-4 hover:border-foreground/30 transition-colors h-full"
      >
        <div className="flex items-start gap-3">
          <div className="inline-flex size-9 items-center justify-center rounded-md border bg-background shrink-0">
            <Icon className="size-4 text-muted-foreground" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{starter.name}</p>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              {starter.description}
            </p>
            <p className="text-[11px] text-muted-foreground/80 mt-2 font-mono">
              {fieldCount} field{fieldCount === 1 ? '' : 's'}
            </p>
          </div>
        </div>
      </Link>
    </li>
  );
}

// ── Disclaimer ─────────────────────────────────────────────────────

function StarterDisclaimerBanner({ inline = false }: { inline?: boolean }) {
  return (
    <div
      className={cn(
        'rounded-md border border-amber-500/40 bg-amber-50/60 dark:bg-amber-950/20 px-4 py-3 flex items-start gap-2.5',
        inline && 'mt-2',
      )}
    >
      <TriangleAlert className="size-4 shrink-0 text-amber-700 dark:text-amber-500 mt-0.5" />
      <div className="text-xs text-foreground/90 leading-relaxed">
        <p className="font-medium text-amber-700 dark:text-amber-500 mb-0.5">
          These templates are structural starters, not legal documents.
        </p>
        <p>
          Common-knowledge medspa intake / consent content is included to
          save build time. Before activating, have your medical director
          review the risks + clinical questions, and have an attorney
          review the language for your state(s) — informed-consent
          requirements vary (CA, NY, FL all have additional disclosures).
        </p>
      </div>
    </div>
  );
}

function surfaceError(err: unknown) {
  if (err instanceof ApiError && err.status === 403) {
    toast.error("You don't have permission to create forms.");
    return;
  }
  if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
    const body = err.body as Record<string, string[] | string>;
    const firstField = Object.keys(body)[0];
    const detail = firstField
      ? Array.isArray(body[firstField])
        ? (body[firstField] as string[])[0]
        : String(body[firstField])
      : 'Could not create form.';
    toast.error(detail);
    return;
  }
  toast.error('Could not create form. Please try again.');
}
