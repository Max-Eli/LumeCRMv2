/**
 * `/marketing/templates/[id]` — edit an existing template.
 */

'use client';

import { ChevronLeft, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { use } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api';
import { useDeleteTemplate, useTemplate } from '@/lib/marketing';

import { TemplateEditor } from '../_template-editor';

export default function EditTemplatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const tplId = Number(id);
  const router = useRouter();
  const { data: template, isLoading, error } = useTemplate(tplId);
  const del = useDeleteTemplate();

  if (isLoading) {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }
  if (error || !template) {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <p className="text-sm text-destructive">Could not load template.</p>
        <Link href="/marketing/templates" className="mt-3 inline-block text-sm font-medium text-foreground underline">
          Back to templates
        </Link>
      </div>
    );
  }

  const handleDelete = () => {
    if (!confirm(`Delete "${template.name}"? Templates referenced by an active campaign cannot be deleted — set them inactive instead.`)) return;
    del.mutate(template.id, {
      onSuccess: () => {
        toast.success('Template deleted');
        router.push('/marketing/templates');
      },
      onError: (err) => {
        if (err instanceof ApiError && err.body && typeof err.body === 'object') {
          const detail = (err.body as { detail?: unknown }).detail;
          toast.error(typeof detail === 'string' ? detail : "Couldn't delete.");
        } else {
          toast.error("Couldn't delete.");
        }
      },
    });
  };

  return (
    <div className="px-10 py-10 max-w-7xl space-y-6">
      <Link
        href="/marketing/templates"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="size-3.5" />
        Back to templates
      </Link>

      <PageHeader
        title={template.name}
        description={`${template.channel === 'email' ? 'Email' : 'SMS'} template`}
        actions={
          <Button type="button" variant="outline" onClick={handleDelete} disabled={del.isPending}>
            <Trash2 className="size-4" />
            Delete
          </Button>
        }
      />

      <TemplateEditor
        initial={template}
        onSaved={() => {
          // Stay on the page; the editor's save toast is enough feedback.
        }}
      />
    </div>
  );
}
