'use client';

import { ChevronLeft, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { use } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { useAutomation, useDeleteAutomation } from '@/lib/marketing';

import { AutomationEditor } from '../_automation-editor';

export default function EditAutomationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const aid = Number(id);
  const router = useRouter();
  const { data: automation, isLoading, error } = useAutomation(aid);
  const del = useDeleteAutomation();

  if (isLoading) {
    return <div className="px-10 py-10 max-w-3xl"><p className="text-sm text-muted-foreground">Loading…</p></div>;
  }
  if (error || !automation) {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <p className="text-sm text-destructive">Could not load automation.</p>
        <Link href="/marketing/automations" className="mt-3 inline-block text-sm font-medium underline">
          Back to automations
        </Link>
      </div>
    );
  }

  const handleDelete = () => {
    if (!confirm(`Delete "${automation.name}"? This stops future fires; past send-log rows are preserved.`)) return;
    del.mutate(automation.id, {
      onSuccess: () => {
        toast.success('Automation deleted');
        router.push('/marketing/automations');
      },
      onError: () => toast.error("Couldn't delete."),
    });
  };

  return (
    <div className="px-10 py-10 max-w-7xl space-y-6">
      <Link href="/marketing/automations" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ChevronLeft className="size-3.5" />
        Back to automations
      </Link>
      <PageHeader
        title={automation.name}
        description={automation.description || 'No description'}
        actions={
          <Button type="button" variant="outline" onClick={handleDelete} disabled={del.isPending}>
            <Trash2 className="size-4" />
            Delete
          </Button>
        }
      />
      <AutomationEditor initial={automation} onSaved={() => {}} />
    </div>
  );
}
