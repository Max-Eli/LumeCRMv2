/**
 * `/forms/emr-templates` — list of EMR templates that
 * providers fill out at appointment time.
 *
 * Distinct from `/forms` (customer-facing intake + consent). These
 * are clinician-facing structured records — units used, lots,
 * injection sites, observations — that lock after signing and
 * carry the same audit posture as chart notes.
 *
 * One row per template, with a service-assignment count + an
 * "active / inactive" badge. Click a row to edit the schema.
 */

'use client';

import {
  ChevronRight,
  ClipboardCheck,
  Plus,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { useCurrentMembership } from '@/lib/auth';
import {
  type TreatmentRecordTemplate,
  useTreatmentTemplates,
} from '@/lib/treatments';
import { cn } from '@/lib/utils';

import { StarterPickerDialog } from './_components/starter-picker-dialog';

export default function TreatmentTemplatesPage() {
  const me = useCurrentMembership();
  const canManage = me?.role === 'owner' || me?.role === 'manager';
  const { data: templates, isLoading } = useTreatmentTemplates();
  const [pickerOpen, setPickerOpen] = useState(false);

  const active = (templates ?? []).filter((t) => t.is_active);
  const inactive = (templates ?? []).filter((t) => !t.is_active);

  return (
    <div className="px-10 py-10">
      <PageHeader
        title="Treatment record templates"
        description="Structured forms providers fill out per appointment. Locked after signing with the same audit posture as chart notes."
        actions={
          canManage ? (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setPickerOpen(true)}
              >
                <Sparkles className="size-4" />
                Browse template library
              </Button>
              <Button render={<Link href="/forms/emr-templates/new" />} nativeButton={false}>
                <Plus className="size-4" />
                New template
              </Button>
            </div>
          ) : null
        }
      />

      {canManage ? (
        <StarterPickerDialog
          open={pickerOpen}
          onOpenChange={setPickerOpen}
        />
      ) : null}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (templates?.length ?? 0) === 0 ? (
        <EmptyState
          canManage={canManage}
          onBrowseLibrary={() => setPickerOpen(true)}
        />
      ) : (
        <div className="space-y-8 mt-6">
          <Section title="Active" templates={active} />
          {inactive.length > 0 ? (
            <Section title="Inactive" templates={inactive} muted />
          ) : null}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  templates,
  muted = false,
}: {
  title: string;
  templates: TreatmentRecordTemplate[];
  muted?: boolean;
}) {
  return (
    <section>
      <h2 className="text-xs uppercase tracking-wide text-muted-foreground font-medium mb-2">
        {title} ({templates.length})
      </h2>
      <ul className="rounded-xl border bg-card divide-y overflow-hidden">
        {templates.map((t) => (
          <li key={t.id}>
            <Link
              href={`/forms/emr-templates/${t.id}`}
              className={cn(
                'flex items-center gap-3 px-4 py-3 hover:bg-muted transition-colors group',
                muted && 'opacity-60',
              )}
            >
              <div
                className="size-9 inline-flex items-center justify-center rounded-md bg-accent/15 text-accent-foreground shrink-0"
                aria-hidden
              >
                <ClipboardCheck className="size-4" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">
                  {t.name}{' '}
                  <span className="text-xs text-muted-foreground font-normal">
                    v{t.version}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground truncate">
                  {t.schema?.fields?.length ?? 0} field
                  {t.schema?.fields?.length === 1 ? '' : 's'}
                  {' · '}
                  {t.service_ids.length} service
                  {t.service_ids.length === 1 ? '' : 's'} assigned
                </p>
              </div>
              <ChevronRight className="size-4 text-muted-foreground/60 group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function EmptyState({
  canManage,
  onBrowseLibrary,
}: {
  canManage: boolean;
  onBrowseLibrary: () => void;
}) {
  return (
    <div className="mt-8 rounded-xl border border-dashed bg-card px-10 py-16 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted mb-3">
        <Sparkles className="size-5 text-muted-foreground" />
      </div>
      <p className="font-medium">No templates yet</p>
      <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
        Templates are the structured forms your providers fill out after a
        treatment — units used, lots, injection sites, observations. Start
        from the library to skip the setup, or build a custom one from
        scratch.
      </p>
      {canManage ? (
        <div className="mt-5 flex items-center justify-center gap-2">
          <Button type="button" onClick={onBrowseLibrary}>
            <Sparkles className="size-4" />
            Browse template library
          </Button>
          <Button
            render={<Link href="/forms/emr-templates/new" />}
            nativeButton={false}
            variant="outline"
          >
            <Plus className="size-4" />
            Build from scratch
          </Button>
        </div>
      ) : null}
    </div>
  );
}
