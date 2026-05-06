/**
 * `/forms/[id]` — edit a form template. Owner-only.
 *
 * Uses the same `<FormTemplateBuilder>` as the create page in edit
 * mode (pre-fills + shows the version-bump hint when schema changes
 * are pending).
 */

'use client';

import { use } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  useFormTemplate,
  useUpdateFormTemplate,
} from '@/lib/form-templates';

import {
  FormTemplateBuilder,
  type FormTemplateBuilderValues,
} from '../_components/form-template-builder';

export default function EditFormTemplatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const templateId = Number(id);
  const router = useRouter();

  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner';
  const { data: template, isLoading, error } = useFormTemplate(templateId);
  const update = useUpdateFormTemplate(templateId);

  if (isLoading) {
    return (
      <div className="px-10 py-10 text-sm text-muted-foreground">
        Loading form…
      </div>
    );
  }
  if (error || !template) {
    return (
      <div className="px-10 py-10">
        <PageHeader
          title="Form not found"
          back={{ href: '/forms', label: 'Back to forms' }}
        />
        <p className="text-sm text-destructive">Could not load this form.</p>
      </div>
    );
  }

  const handleSubmit = (values: FormTemplateBuilderValues) => {
    if (!canEdit) return;
    update.mutate(
      {
        name: values.name,
        description: values.description,
        form_type: values.form_type,
        recurrence: values.recurrence,
        is_active: values.is_active,
        schema: values.schema,
        // Only send `set_service_ids` for consent forms — for intake
        // forms the backend rejects any non-empty list, and sending
        // an empty list every time would add noise to the audit log.
        ...(values.form_type === 'consent'
          ? { set_service_ids: values.service_ids }
          : {}),
      },
      {
        onSuccess: () => toast.success('Form saved'),
        onError: (err) => surfaceError(err),
      },
    );
  };

  return (
    <div className="max-w-6xl px-10 py-10 space-y-6">
      <PageHeader
        title={template.name}
        description={`Form template · v${template.version}`}
        back={{ href: '/forms', label: 'Back to forms' }}
      />
      <fieldset disabled={!canEdit} className="contents">
        <FormTemplateBuilder
          existing={template}
          onSubmit={handleSubmit}
          onCancel={() => router.push('/forms')}
          isSubmitting={update.isPending}
        />
      </fieldset>
      {!canEdit ? (
        <p className="text-xs text-muted-foreground text-right">
          You can view this form but only owners can edit it.
        </p>
      ) : null}
    </div>
  );
}

function surfaceError(err: unknown) {
  if (err instanceof ApiError && err.status === 403) {
    toast.error("You don't have permission to edit forms.");
    return;
  }
  if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
    const body = err.body as Record<string, string[] | string>;
    const firstField = Object.keys(body)[0];
    const detail = firstField
      ? Array.isArray(body[firstField])
        ? (body[firstField] as string[])[0]
        : String(body[firstField])
      : 'Could not save form.';
    toast.error(detail);
    return;
  }
  toast.error('Could not save form. Please try again.');
}
