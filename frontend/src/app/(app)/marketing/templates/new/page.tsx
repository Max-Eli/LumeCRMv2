/**
 * `/marketing/templates/new` — create a new template.
 */

'use client';

import { ChevronLeft } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { PageHeader } from '@/components/page-header';

import { TemplateEditor } from '../_template-editor';

export default function NewTemplatePage() {
  const router = useRouter();
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
        title="New template"
        description="Email or SMS body with personalization tokens. The token validator enforces the HIPAA + CAN-SPAM allowlist at save time."
      />

      <TemplateEditor onSaved={(t) => router.push(`/marketing/templates/${t.id}`)} />
    </div>
  );
}
