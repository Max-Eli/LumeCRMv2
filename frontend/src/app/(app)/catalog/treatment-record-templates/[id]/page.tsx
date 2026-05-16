/**
 * `/catalog/treatment-record-templates/[id]` — edit an EMR template.
 *
 * Schema changes auto-bump the template version on save; submitted
 * records snapshot the version they were signed against, so editing
 * the template doesn't retroactively change historical records.
 */

'use client';

import { Loader2 } from 'lucide-react';
import { use } from 'react';

import { PageHeader } from '@/components/page-header';
import { useTreatmentTemplate } from '@/lib/treatments';

import { TemplateEditor } from '../_components/template-editor';

export default function EditTreatmentTemplatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const templateId = Number(id);
  const { data: template, isLoading, error } = useTreatmentTemplate(templateId);

  if (isLoading) {
    return (
      <div className="px-10 py-10">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading template…
        </div>
      </div>
    );
  }
  if (error || !template) {
    return (
      <div className="px-10 py-10">
        <PageHeader
          title="Template not found"
          back={{
            href: '/catalog/treatment-record-templates',
            label: 'All templates',
          }}
        />
        <p className="text-sm text-destructive">Couldn&apos;t load this template.</p>
      </div>
    );
  }

  return (
    <div className="px-10 py-10">
      <PageHeader
        title={template.name}
        description={`Version ${template.version} · ${template.service_ids.length} service${template.service_ids.length === 1 ? '' : 's'} assigned`}
        back={{
          href: '/catalog/treatment-record-templates',
          label: 'All templates',
        }}
      />
      <div className="mt-6">
        <TemplateEditor template={template} />
      </div>
    </div>
  );
}
