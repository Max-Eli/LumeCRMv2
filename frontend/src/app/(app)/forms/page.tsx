/**
 * `/forms` — list of form templates (intake + consent).
 *
 * Owner manages templates here; front desk has read-only access (so
 * they can see what forms exist when chasing a client to sign one).
 *
 * Grouped by form type — intake templates and consent templates serve
 * different purposes and the operator usually thinks about them
 * separately ("which intake form do I use?" vs "which consent forms
 * apply to my services?"). Each row links to the builder.
 */

'use client';

import {
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  FileText,
  Plus,
} from 'lucide-react';
import Link from 'next/link';

import { PageHeader } from '@/components/page-header';
import { useCurrentMembership } from '@/lib/auth';
import {
  FORM_TYPE_LABELS,
  type FormTemplate,
  type FormType,
  RECURRENCE_LABELS,
  useFormTemplates,
} from '@/lib/form-templates';
import { cn } from '@/lib/utils';

export default function FormsListPage() {
  const me = useCurrentMembership();
  const canManage = me?.role === 'owner';
  const { data: templates, isLoading, error } = useFormTemplates();

  const intake = (templates ?? []).filter((t) => t.form_type === 'intake');
  const consent = (templates ?? []).filter((t) => t.form_type === 'consent');

  return (
    <div className="px-10 py-10 max-w-7xl space-y-8">
      <PageHeader
        title="Forms"
        description="Templates for client intake + per-service consent. Forms get auto-assigned to appointments based on their type and stay pending until the client signs them."
        actions={
          canManage ? (
            <Link
              href="/forms/new"
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-foreground text-background text-xs font-medium hover:bg-foreground/90 transition-colors"
            >
              <Plus className="size-3.5" />
              New form
            </Link>
          ) : null
        }
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading forms…</p>
      ) : error ? (
        <p className="text-sm text-destructive">Could not load forms.</p>
      ) : (templates ?? []).length === 0 ? (
        <EmptyState canManage={canManage} />
      ) : (
        <>
          <FormGroup
            type="intake"
            templates={intake}
            description="Auto-assigned to a client's first-ever appointment, regardless of which service they're booking. Use these for medical history, contact preferences, photo consent — anything you ask once."
            canManage={canManage}
          />
          <FormGroup
            type="consent"
            templates={consent}
            description="Mapped to specific services and auto-assigned when those services are booked. Use these for treatment-specific informed consent (Botox, fillers, lasers, etc.)."
            canManage={canManage}
          />
        </>
      )}
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function FormGroup({
  type,
  templates,
  description,
  canManage,
}: {
  type: FormType;
  templates: FormTemplate[];
  description: string;
  canManage: boolean;
}) {
  const Icon = type === 'intake' ? ClipboardList : ClipboardCheck;
  return (
    <section>
      <header className="mb-3">
        <div className="flex items-center gap-2">
          <Icon className="size-4 text-muted-foreground" />
          <h2 className="font-serif text-base font-semibold tracking-tight">
            {FORM_TYPE_LABELS[type]}
          </h2>
        </div>
        <p className="text-xs text-muted-foreground mt-1.5 max-w-2xl leading-relaxed">
          {description}
        </p>
      </header>
      {templates.length === 0 ? (
        <div className="border border-dashed rounded-lg bg-muted/20 px-6 py-8 text-center">
          <p className="text-sm text-muted-foreground">
            No {FORM_TYPE_LABELS[type].toLowerCase()} forms yet.
          </p>
          {canManage ? (
            <Link
              href={`/forms/new?type=${type}`}
              className="inline-flex items-center gap-1 text-xs text-foreground hover:underline underline-offset-2 mt-2"
            >
              <Plus className="size-3" />
              Create one
            </Link>
          ) : null}
        </div>
      ) : (
        <ul className="border rounded-lg divide-y bg-card">
          {templates.map((t) => (
            <FormRow key={t.id} template={t} canOpen={canManage} />
          ))}
        </ul>
      )}
    </section>
  );
}

function FormRow({
  template,
  canOpen,
}: {
  template: FormTemplate;
  canOpen: boolean;
}) {
  const fieldCount = template.schema?.fields?.length ?? 0;
  const detailHref = `/forms/${template.id}`;

  return (
    <li
      className={cn(
        'group relative flex items-center gap-4 px-4 py-3 transition-colors',
        !template.is_active && 'bg-muted/30',
        canOpen && 'hover:bg-muted/40',
      )}
    >
      {canOpen ? (
        <Link
          href={detailHref}
          className="absolute inset-0 z-0 rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring/40"
          aria-label={`Edit ${template.name}`}
        >
          <span className="sr-only">Edit</span>
        </Link>
      ) : null}

      <div
        className={cn(
          'inline-flex size-9 items-center justify-center rounded-md border bg-background',
          !template.is_active && 'opacity-60',
        )}
        aria-hidden
      >
        <FileText className="size-4 text-muted-foreground" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p
            className={cn(
              'text-sm font-medium truncate',
              !template.is_active && 'text-muted-foreground line-through',
            )}
          >
            {template.name}
          </p>
          <span className="text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-muted text-muted-foreground font-mono">
            v{template.version}
          </span>
          {!template.is_active ? (
            <span className="text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-muted text-muted-foreground">
              Inactive
            </span>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground truncate mt-0.5">
          {fieldCount} field{fieldCount === 1 ? '' : 's'}
          <span className="text-muted-foreground/60"> · </span>
          {RECURRENCE_LABELS[template.recurrence]}
          {template.form_type === 'consent' && template.service_ids.length > 0 ? (
            <>
              <span className="text-muted-foreground/60"> · </span>
              {template.service_ids.length} service
              {template.service_ids.length === 1 ? '' : 's'}
            </>
          ) : null}
          {template.form_type === 'consent' && template.service_ids.length === 0 ? (
            <>
              <span className="text-muted-foreground/60"> · </span>
              <span className="text-amber-600 dark:text-amber-500">
                Not mapped to any service
              </span>
            </>
          ) : null}
        </p>
      </div>

      <div className="relative z-10 flex items-center gap-2">
        {canOpen ? (
          <ChevronRight className="size-4 text-muted-foreground/60 group-hover:text-muted-foreground transition-colors" />
        ) : null}
      </div>
    </li>
  );
}

function EmptyState({ canManage }: { canManage: boolean }) {
  return (
    <div className="border rounded-lg bg-card px-6 py-12 text-center">
      <FileText className="size-6 mx-auto mb-3 text-muted-foreground/60" />
      <p className="text-sm text-foreground font-medium">No forms yet</p>
      <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto leading-relaxed">
        Forms get auto-assigned to appointments — intake forms for new clients,
        consent forms for the services you map them to. Create your first one
        to get started.
      </p>
      {canManage ? (
        <Link
          href="/forms/new"
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-foreground text-background text-xs font-medium hover:bg-foreground/90 transition-colors mt-5"
        >
          <Plus className="size-3.5" />
          New form
        </Link>
      ) : (
        <p className="text-[11px] text-muted-foreground/80 mt-5">
          Only owners can create forms. Ask your owner to set them up.
        </p>
      )}
    </div>
  );
}
