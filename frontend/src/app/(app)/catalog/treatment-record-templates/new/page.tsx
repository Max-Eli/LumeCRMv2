/**
 * `/catalog/treatment-record-templates/new` — author a new EMR
 * template. Routes to the detail page on save.
 */

'use client';

import Link from 'next/link';

import { PageHeader } from '@/components/page-header';

import { TemplateEditor } from '../_components/template-editor';

export default function NewTreatmentTemplatePage() {
  return (
    <div className="px-10 py-10">
      <PageHeader
        title="New treatment template"
        description="Build the structured form your providers will fill out after a treatment."
        back={{
          href: '/catalog/treatment-record-templates',
          label: 'All templates',
        }}
      />
      <div className="mt-6">
        <TemplateEditor />
      </div>
    </div>
  );
}
