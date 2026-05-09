/**
 * `/catalog/categories/[id]` — edit a service category.
 *
 * Layout matches `org/business` and `staff/employees/[id]`: a wide
 * `max-w-7xl` container with two-column sections (label + description
 * on the left, fields on the right). Sticky save bar at the bottom.
 *
 * Sections:
 *   - Identity   — name, color, sort order
 *   - Eligibility — which job titles can perform services in this
 *                   category (the eligibility selector handles the
 *                   list-of-clinical-roles UX itself).
 *
 * Delete lives in the page header. Disabled with a tooltip when the
 * category still has services attached — categories with services
 * can't be deleted server-side either, this just front-runs the
 * error message.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Palette, Trash2, UserCheck, Users as UsersIcon } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { use, useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { CategoryEligibilitySelector } from '@/components/category-eligibility-selector';
import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  type ServiceCategory,
  useDeleteServiceCategory,
  useServiceCategory,
  useUpdateServiceCategory,
} from '@/lib/services';

const schema = z.object({
  name: z.string().min(1, 'Name is required').max(100),
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/, 'Use a 6-digit hex like #6b7280'),
  // Plain `z.number()` (not `z.coerce.number()`) so the schema's
  // input + output types both stay `number` and zodResolver doesn't
  // get a Resolver<input=unknown> ↔ FormValues<output=number>
  // mismatch. The `<Input>` is registered with `valueAsNumber: true`
  // below to coerce the HTML string to number on the RHF side.
  sort_order: z.number().int(),
});

type FormValues = z.infer<typeof schema>;

const DEFAULT_COLORS = ['#6b7280', '#d97706', '#10b981', '#7c3aed', '#0ea5e9', '#f43f5e', '#ec4899'];

function categoryToValues(c: ServiceCategory): FormValues {
  return { name: c.name, color: c.color, sort_order: c.sort_order };
}

export default function EditCategoryPage({ params }: { params: Promise<{ id: string }> }) {
  const router = useRouter();
  const { id } = use(params);
  const categoryId = Number(id);
  const { data: category, isLoading, error } = useServiceCategory(categoryId);
  const update = useUpdateServiceCategory(categoryId);
  const remove = useDeleteServiceCategory();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: category ? categoryToValues(category) : { name: '', color: '#6b7280', sort_order: 0 },
  });
  const watched = form.watch();
  const [eligibleIds, setEligibleIds] = useState<number[]>([]);
  const [savedEligibleIds, setSavedEligibleIds] = useState<number[]>([]);

  useEffect(() => {
    if (category) {
      form.reset(categoryToValues(category));
      const ids = category.eligible_job_titles.map((jt) => jt.id);
      setEligibleIds(ids);
      setSavedEligibleIds(ids);
    }
  }, [category, form]);

  if (isLoading) {
    return <div className="px-10 py-10 text-sm text-muted-foreground">Loading category…</div>;
  }
  if (error || !category) {
    return (
      <div className="px-10 py-10 max-w-7xl">
        <PageHeader title="Category not found" back={{ href: '/catalog/categories', label: 'All categories' }} />
        <p className="text-sm text-destructive">Failed to load this category.</p>
      </div>
    );
  }

  const eligibilityDirty =
    eligibleIds.length !== savedEligibleIds.length ||
    eligibleIds.some((id) => !savedEligibleIds.includes(id));
  const isDirty = form.formState.isDirty || eligibilityDirty;
  const canDelete = category.service_count === 0;

  const onSubmit = (values: FormValues) => {
    update.mutate(
      { ...values, eligible_job_title_ids: eligibleIds },
      {
        onSuccess: (updated) => {
          toast.success('Category saved');
          form.reset(categoryToValues(updated));
          setSavedEligibleIds(updated.eligible_job_titles.map((jt) => jt.id));
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
            const fieldErrors = err.body as Record<string, string[] | string>;
            for (const [field, msgs] of Object.entries(fieldErrors)) {
              const message = Array.isArray(msgs) ? msgs[0] : String(msgs);
              if (field in form.getValues()) {
                form.setError(field as keyof FormValues, { message });
              }
            }
            toast.error('Please fix the highlighted fields.');
          } else {
            toast.error('Save failed. Please try again.');
          }
        },
      },
    );
  };

  const onDelete = () => {
    if (!canDelete) {
      toast.error(
        `Can't delete — ${category.service_count} services are still in this category. Reassign them first.`,
      );
      return;
    }
    if (!window.confirm(`Delete the "${category.name}" category? This cannot be undone.`)) return;
    remove.mutate(categoryId, {
      onSuccess: () => {
        toast.success('Category deleted');
        router.push('/catalog/categories');
      },
      onError: () => toast.error('Delete failed. Please try again.'),
    });
  };

  return (
    <div className="px-10 py-10 max-w-7xl">
      <PageHeader
        title={category.name}
        description={`${category.service_count} ${category.service_count === 1 ? 'service' : 'services'} in this category`}
        back={{ href: '/catalog/categories', label: 'All categories' }}
        actions={
          <Button
            variant="outline"
            onClick={onDelete}
            disabled={remove.isPending || !canDelete}
            title={canDelete ? 'Delete this category' : 'Reassign services before deleting'}
          >
            <Trash2 className="size-4" />
            Delete
          </Button>
        }
      />

      <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
        <div className="divide-y border-t border-b">
          <Section
            title="Identity"
            description="The category's display name, brand color, and where it sits in the list (lower numbers sort first). Color shows up as the badge in the services table and in the calendar's appointment blocks."
            icon={<Palette className="size-4 text-muted-foreground" />}
          >
            <Field data-invalid={form.formState.errors.name ? true : undefined}>
              <FieldLabel htmlFor="name">Category name</FieldLabel>
              <Input id="name" {...form.register('name')} />
              {form.formState.errors.name ? (
                <FieldError>{form.formState.errors.name.message}</FieldError>
              ) : null}
            </Field>

            <Field data-invalid={form.formState.errors.color ? true : undefined}>
              <FieldLabel htmlFor="color">Color</FieldLabel>
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  type="color"
                  value={watched.color}
                  onChange={(e) => form.setValue('color', e.target.value, { shouldDirty: true })}
                  className="size-10 rounded-md border cursor-pointer p-1"
                  aria-label="Pick color"
                />
                <Input
                  id="color"
                  className="w-32 font-mono uppercase"
                  {...form.register('color')}
                />
                <div className="flex gap-1.5">
                  {DEFAULT_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => form.setValue('color', c, { shouldDirty: true })}
                      className="size-6 rounded-full border-2 border-background ring-1 ring-border hover:scale-110 transition-transform"
                      style={{ backgroundColor: c }}
                      aria-label={`Use ${c}`}
                    />
                  ))}
                </div>
              </div>
              {form.formState.errors.color ? (
                <FieldError>{form.formState.errors.color.message}</FieldError>
              ) : null}
            </Field>

            <Field>
              <FieldLabel htmlFor="sort_order">Sort order</FieldLabel>
              <Input
                id="sort_order"
                type="number"
                className="w-32 tabular-nums"
                {...form.register('sort_order', { valueAsNumber: true })}
              />
              <p className="text-[11px] text-muted-foreground mt-1">
                Lower numbers appear first in lists. Categories with the same number
                fall back to alphabetical order.
              </p>
            </Field>
          </Section>

          <Section
            title="Who can perform"
            description="Limit which job titles are allowed to perform services in this category. Leave empty to allow any bookable provider — useful for general-purpose categories like Consultations or Add-ons."
            icon={<UserCheck className="size-4 text-muted-foreground" />}
          >
            <CategoryEligibilitySelector
              selectedIds={eligibleIds}
              onChange={setEligibleIds}
            />
          </Section>

          <Section
            title="Usage"
            description="How this category is being used right now. To delete the category, reassign any attached services first."
            icon={<UsersIcon className="size-4 text-muted-foreground" />}
          >
            <div className="rounded-md border bg-muted/20 px-4 py-3 flex items-baseline gap-3">
              <p className="font-serif text-2xl font-semibold tracking-tight tabular-nums text-foreground">
                {category.service_count}
              </p>
              <p className="text-sm text-muted-foreground">
                {category.service_count === 1 ? 'service' : 'services'} attached
              </p>
            </div>
          </Section>
        </div>

        <div className="sticky bottom-0 -mx-10 px-10 py-4 mt-6 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="flex items-center justify-between gap-2 max-w-7xl mx-auto">
            <p className="text-xs text-muted-foreground">
              {isDirty ? 'Unsaved changes' : 'No changes'}
            </p>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!isDirty || update.isPending}
                onClick={() => {
                  form.reset(categoryToValues(category));
                  setEligibleIds(savedEligibleIds);
                }}
              >
                Discard
              </Button>
              <Button type="submit" disabled={!isDirty || update.isPending}>
                {update.isPending ? 'Saving…' : 'Save changes'}
              </Button>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}

// ── Layout primitives ────────────────────────────────────────────────

function Section({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6 lg:gap-12 py-6 first:pt-8 last:pb-8">
      <header>
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-serif text-base font-semibold tracking-tight">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
            {description}
          </p>
        ) : null}
      </header>
      <div className="space-y-3 max-w-2xl">{children}</div>
    </section>
  );
}
