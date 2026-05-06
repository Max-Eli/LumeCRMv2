'use client';

import { ChevronLeft } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { PageHeader } from '@/components/page-header';

import { AutomationEditor } from '../_automation-editor';

export default function NewAutomationPage() {
  const router = useRouter();
  return (
    <div className="px-10 py-10 max-w-7xl space-y-6">
      <Link href="/marketing/automations" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ChevronLeft className="size-3.5" />
        Back to automations
      </Link>
      <PageHeader
        title="New automation"
        description="Triggered campaigns that fire when customers become eligible. Lands paused — flip on after previewing the eligibility count."
      />
      <AutomationEditor onSaved={(a) => router.push(`/marketing/automations/${a.id}`)} />
    </div>
  );
}
