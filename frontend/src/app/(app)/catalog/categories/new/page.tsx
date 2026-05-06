'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Sparkles, Users as UsersIcon } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { CategoryEligibilitySelector } from '@/components/category-eligibility-selector';
import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { useCreateServiceCategory } from '@/lib/services';

const schema = z.object({
  name: z.string().min(1, 'Name is required').max(100),
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/, 'Use a 6-digit hex like #6b7280'),
  sort_order: z.coerce.number().int(),
});

type FormValues = z.infer<typeof schema>;

const DEFAULT_COLORS = ['#6b7280', '#d97706', '#10b981', '#7c3aed', '#0ea5e9', '#f43f5e', '#ec4899'];

export default function NewCategoryPage() {
  const router = useRouter();
  const create = useCreateServiceCategory();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', color: '#6b7280', sort_order: 0 },
  });
  const watched = form.watch();

  // M2M lives outside RHF since it's not a primitive form value.
  const [eligibleIds, setEligibleIds] = useState<number[]>([]);

  const onSubmit = (values: FormValues) => {
    create.mutate(
      { ...values, eligible_job_title_ids: eligibleIds },
      {
        onSuccess: (created) => {
          toast.success(`${created.name} created`);
          router.push(`/services/categories/${created.id}`);
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
            toast.error('Failed to create category. Please try again.');
          }
        },
      },
    );
  };

  return (
    <div className="px-10 py-10 max-w-4xl">
      <PageHeader
        title="New category"
        description="Group services and define which staff can perform them."
        back={{ href: '/catalog/categories', label: 'All categories' }}
      />

      <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-10">
        <Section title="Basics" icon={<Sparkles className="size-4" />}>
          <Field data-invalid={form.formState.errors.name ? true : undefined}>
            <FieldLabel htmlFor="name">Category name</FieldLabel>
            <Input id="name" autoFocus placeholder="e.g. Injectables" {...form.register('name')} />
            {form.formState.errors.name ? (
              <FieldError>{form.formState.errors.name.message}</FieldError>
            ) : null}
          </Field>

          <Field data-invalid={form.formState.errors.color ? true : undefined}>
            <FieldLabel htmlFor="color">Color</FieldLabel>
            <div className="flex items-center gap-2">
              <input
                type="color"
                id="color-picker"
                value={watched.color}
                onChange={(e) => form.setValue('color', e.target.value, { shouldDirty: true })}
                className="size-10 rounded-md border cursor-pointer p-1"
                aria-label="Pick color"
              />
              <Input id="color" className="w-32 font-mono" {...form.register('color')} />
              <div className="flex gap-1">
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
              className="w-32"
              {...form.register('sort_order')}
            />
            <p className="text-xs text-muted-foreground mt-1">
              Lower numbers appear first on the categories grid.
            </p>
          </Field>
        </Section>

        <Section title="Who can perform" icon={<UsersIcon className="size-4" />}>
          <CategoryEligibilitySelector
            selectedIds={eligibleIds}
            onChange={setEligibleIds}
          />
        </Section>

        <div className="sticky bottom-0 -mx-10 px-10 py-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="flex items-center justify-end gap-2 max-w-4xl mx-auto">
            <Button render={<Link href="/catalog/categories" />} nativeButton={false} variant="outline">
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Saving…' : 'Create category'}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="flex items-center gap-2 mb-4 pb-2 border-b">
        <span className="text-muted-foreground">{icon}</span>
        <h2 className="text-sm font-medium uppercase tracking-wide text-foreground">{title}</h2>
      </header>
      <FieldGroup>{children}</FieldGroup>
    </section>
  );
}
