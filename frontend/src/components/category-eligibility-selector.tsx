/**
 * Reusable selector for "which job titles can perform services in this category."
 *
 * Renders the tenant's job-title list as a checkbox grid grouped by clinical /
 * non-clinical, with select-all helpers for the common patterns (all clinical,
 * all titles, none). Used by both the create-category and edit-category pages.
 */

'use client';

import { Stethoscope, UserCheck } from 'lucide-react';

import { Checkbox } from '@/components/ui/checkbox';
import { useJobTitles, type JobTitle } from '@/lib/job-titles';
import { cn } from '@/lib/utils';

export interface CategoryEligibilitySelectorProps {
  selectedIds: number[];
  onChange: (ids: number[]) => void;
}

export function CategoryEligibilitySelector({
  selectedIds,
  onChange,
}: CategoryEligibilitySelectorProps) {
  const { data: jobTitles, isLoading } = useJobTitles();

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading job titles…</p>;
  }
  if (!jobTitles || jobTitles.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No job titles configured for this tenant. Add some in Django admin under Tenants → Job
        titles.
      </p>
    );
  }

  const clinical = jobTitles.filter((jt) => jt.is_clinical);
  const nonClinical = jobTitles.filter((jt) => !jt.is_clinical);
  const selectedSet = new Set(selectedIds);

  const toggle = (id: number, checked: boolean) => {
    if (checked) {
      onChange([...selectedIds, id]);
    } else {
      onChange(selectedIds.filter((x) => x !== id));
    }
  };

  const setMany = (ids: number[]) => onChange(ids);

  return (
    <div className="space-y-5">
      {/* Quick-select chips */}
      <div className="flex flex-wrap gap-2">
        <QuickSelect
          label="All clinical"
          icon={<Stethoscope className="size-3.5" />}
          active={clinical.length > 0 && clinical.every((jt) => selectedSet.has(jt.id))}
          onClick={() => setMany([...new Set([...selectedIds, ...clinical.map((jt) => jt.id)])])}
        />
        <QuickSelect
          label="Everyone"
          icon={<UserCheck className="size-3.5" />}
          active={jobTitles.every((jt) => selectedSet.has(jt.id))}
          onClick={() => setMany(jobTitles.map((jt) => jt.id))}
        />
        <QuickSelect
          label="No restriction"
          active={selectedIds.length === 0}
          onClick={() => setMany([])}
        />
      </div>

      {/* Clinical group */}
      {clinical.length > 0 ? (
        <Group title="Clinical" subtitle="Eligible to sign chart notes and prescriptions">
          {clinical.map((jt) => (
            <JobTitleRow
              key={jt.id}
              jt={jt}
              checked={selectedSet.has(jt.id)}
              onChange={(c) => toggle(jt.id, c)}
            />
          ))}
        </Group>
      ) : null}

      {/* Non-clinical group */}
      {nonClinical.length > 0 ? (
        <Group title="Non-clinical">
          {nonClinical.map((jt) => (
            <JobTitleRow
              key={jt.id}
              jt={jt}
              checked={selectedSet.has(jt.id)}
              onChange={(c) => toggle(jt.id, c)}
            />
          ))}
        </Group>
      ) : null}

      <p className="text-xs text-muted-foreground">
        Empty selection = no restriction (any bookable staff can perform). When the booking
        calendar lands, this list filters the provider dropdown for appointments in this category.
      </p>
    </div>
  );
}

function Group({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
        {title}
        {subtitle ? <span className="ml-2 normal-case text-muted-foreground/70">{subtitle}</span> : null}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">{children}</div>
    </div>
  );
}

function JobTitleRow({
  jt,
  checked,
  onChange,
}: {
  jt: JobTitle;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = `jt-${jt.id}`;
  return (
    <label
      htmlFor={id}
      className={cn(
        'flex items-center gap-3 px-3 py-2 rounded-md border transition-colors cursor-pointer',
        checked
          ? 'border-accent/60 bg-accent/5'
          : 'border-border hover:border-foreground/20',
      )}
    >
      <Checkbox id={id} checked={checked} onCheckedChange={(v) => onChange(Boolean(v))} />
      <span className="text-sm">{jt.name}</span>
    </label>
  );
}

function QuickSelect({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon?: React.ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors',
        active
          ? 'border-accent bg-accent text-accent-foreground'
          : 'border-border bg-background hover:bg-muted',
      )}
    >
      {icon}
      {label}
    </button>
  );
}
