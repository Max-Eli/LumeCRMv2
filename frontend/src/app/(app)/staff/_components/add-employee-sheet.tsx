/**
 * Add-employee bottom sheet.
 *
 * Mounted from `/staff/employees`'s "Add employee" button (owner +
 * manager only — backend re-validates `MANAGE_STAFF`). Slides up from
 * the bottom of the viewport, centered with `max-w-2xl` (matches the
 * New Appointment sheet treatment).
 *
 * Form: email, first name, last name, role (Select), optional job
 * title (Select), bookable toggle. On submit, hits
 * `POST /api/memberships/`. The backend either:
 *
 *   1. Attaches an existing User as a new membership of this tenant —
 *      no temp password (the user already has credentials), or
 *   2. Creates a brand-new User with a generated temp password and
 *      returns it once.
 *
 * In case (2), this component swaps to a "share these credentials"
 * confirmation panel showing the email + temp password, with a Copy
 * button. The owner copies it once, hands it to the new employee,
 * then closes the sheet. The password is not recoverable from the
 * server after this point — the polish backlog has the email-invite
 * flow to replace this.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Check, Copy, KeyRound, UserPlus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { ApiError, api } from '@/lib/api';
import {
  ASSIGNABLE_ROLES,
  type CreateEmployeeResponse,
  ROLE_LABELS,
  type StaffRole,
  useCreateEmployee,
} from '@/lib/tenant';

const schema = z.object({
  email: z.string().email('Enter a valid email'),
  first_name: z.string().min(1, 'First name is required').max(150),
  last_name: z.string().min(1, 'Last name is required').max(150),
  role: z.enum([
    'manager',
    'front_desk',
    'provider',
    'bookkeeper',
    'marketing',
  ]),
  job_title_id: z.number().int().nullable().optional(),
  is_bookable: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

interface JobTitleLite {
  id: number;
  name: string;
}

export interface AddEmployeeSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Optional callback when a new employee is successfully added —
   *  e.g. the parent might want to navigate to the new detail page. */
  onCreated?: (employee: CreateEmployeeResponse) => void;
}

export function AddEmployeeSheet({ open, onOpenChange, onCreated }: AddEmployeeSheetProps) {
  const create = useCreateEmployee();
  // After a brand-new user is created, swap the form for the
  // share-credentials panel. Existing-user attaches close the sheet
  // immediately (no password to share).
  const [tempCreds, setTempCreds] = useState<
    | { email: string; password: string; firstName: string; lastName: string }
    | null
  >(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: '',
      first_name: '',
      last_name: '',
      role: 'front_desk',
      job_title_id: null,
      is_bookable: false,
    },
  });

  // Reset form + clear creds whenever the sheet closes/reopens.
  useEffect(() => {
    if (open) {
      form.reset();
      setTempCreds(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Job titles are tenant-scoped; load lazily when the sheet opens.
  const [jobTitles, setJobTitles] = useState<JobTitleLite[]>([]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .get<JobTitleLite[]>('/api/job-titles/')
      .then((rows) => {
        if (!cancelled) setJobTitles(rows);
      })
      .catch(() => {
        // Job titles are optional — silently degrade if the lookup fails.
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const onSubmit = form.handleSubmit((values) => {
    create.mutate(
      {
        email: values.email.trim(),
        first_name: values.first_name.trim(),
        last_name: values.last_name.trim(),
        role: values.role,
        job_title_id: values.job_title_id ?? null,
        is_bookable: values.is_bookable,
      },
      {
        onSuccess: (employee) => {
          if (employee.temp_password) {
            // Brand-new user — surface the credentials for the owner
            // to share, then keep the sheet open so they can copy.
            setTempCreds({
              email: employee.user_email,
              password: employee.temp_password,
              firstName: employee.user_first_name,
              lastName: employee.user_last_name,
            });
          } else {
            // Existing user attached — just close + toast.
            toast.success(
              `${employee.user_first_name} ${employee.user_last_name} added to the team`,
            );
            onOpenChange(false);
          }
          onCreated?.(employee);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 403) {
            toast.error("You don't have permission to add employees.");
          } else if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
            const body = err.body as Record<string, string[] | string>;
            const firstField = Object.keys(body)[0];
            const detail = firstField
              ? Array.isArray(body[firstField])
                ? (body[firstField] as string[])[0]
                : String(body[firstField])
              : 'Could not add employee.';
            toast.error(detail);
          } else {
            toast.error('Could not add employee. Please try again.');
          }
        },
      },
    );
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="max-w-2xl">
        {tempCreds ? (
          <ShareCredentialsPanel
            creds={tempCreds}
            onDone={() => onOpenChange(false)}
          />
        ) : (
          <>
            <SheetHeader>
              <SheetTitle>Add employee</SheetTitle>
              <SheetDescription>
                Add a new person to your team. They&apos;ll be able to sign in at your
                portal once you share their credentials.
              </SheetDescription>
            </SheetHeader>

            <form onSubmit={onSubmit} className="contents">
              <SheetBody className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <Field>
                    <FieldLabel htmlFor="first_name">First name</FieldLabel>
                    <Input id="first_name" {...form.register('first_name')} autoFocus />
                    <FieldError>{form.formState.errors.first_name?.message}</FieldError>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="last_name">Last name</FieldLabel>
                    <Input id="last_name" {...form.register('last_name')} />
                    <FieldError>{form.formState.errors.last_name?.message}</FieldError>
                  </Field>
                </div>

                <Field>
                  <FieldLabel htmlFor="email">Email</FieldLabel>
                  <Input id="email" type="email" {...form.register('email')} />
                  <p className="text-[11px] text-muted-foreground mt-1">
                    They&apos;ll use this to sign in. If they&apos;re already a
                    user in the system (e.g. they work at another spa on Lumè),
                    we&apos;ll attach them as a new employee here.
                  </p>
                  <FieldError>{form.formState.errors.email?.message}</FieldError>
                </Field>

                <div className="grid grid-cols-2 gap-3">
                  <Field>
                    <FieldLabel htmlFor="role">Role</FieldLabel>
                    <Select
                      value={form.watch('role')}
                      onValueChange={(v) =>
                        form.setValue(
                          'role',
                          v as Exclude<StaffRole, 'owner'>,
                          { shouldDirty: true },
                        )
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ASSIGNABLE_ROLES.map((r) => (
                          <SelectItem key={r} value={r}>
                            {ROLE_LABELS[r]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-[11px] text-muted-foreground mt-1">
                      Owners are added through a separate flow.
                    </p>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="job_title_id">Job title (optional)</FieldLabel>
                    <Select
                      value={
                        form.watch('job_title_id') ? String(form.watch('job_title_id')) : 'none'
                      }
                      onValueChange={(v) =>
                        form.setValue('job_title_id', v === 'none' ? null : Number(v), {
                          shouldDirty: true,
                        })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="None" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">None</SelectItem>
                        {jobTitles.map((jt) => (
                          <SelectItem key={jt.id} value={String(jt.id)}>
                            {jt.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                </div>

                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    {...form.register('is_bookable')}
                    className="mt-0.5 size-4 rounded border-border text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
                  />
                  <div>
                    <span className="text-sm font-medium">Bookable on the calendar</span>
                    <p className="text-[11px] text-muted-foreground">
                      Appears as a column on the booking calendar so customers can
                      book appointments with them.
                    </p>
                  </div>
                </label>
              </SheetBody>

              <SheetFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled={create.isPending}
                  onClick={() => onOpenChange(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={create.isPending}>
                  <UserPlus className="size-4" />
                  {create.isPending ? 'Adding…' : 'Add employee'}
                </Button>
              </SheetFooter>
            </form>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ── Share credentials panel ─────────────────────────────────────────

/**
 * One-time post-create view showing the temp credentials. The owner
 * copies them, hands them off, then closes. Once the sheet closes the
 * password is gone — there's no "show me again" flow because the
 * password isn't stored in plaintext anywhere on the server.
 *
 * Replaced by the email-invite flow when Phase 1F lands (polish backlog).
 */
function ShareCredentialsPanel({
  creds,
  onDone,
}: {
  creds: { email: string; password: string; firstName: string; lastName: string };
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const fullName = `${creds.firstName} ${creds.lastName}`.trim();

  const copyAll = async () => {
    const blob = `Email: ${creds.email}\nTemporary password: ${creds.password}`;
    try {
      await navigator.clipboard.writeText(blob);
      setCopied(true);
      toast.success('Credentials copied');
      setTimeout(() => setCopied(false), 2500);
    } catch {
      toast.error('Could not copy — copy manually below.');
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle>Employee added</SheetTitle>
        <SheetDescription>
          Share these credentials with {fullName || 'the new employee'} —{' '}
          they&apos;ll sign in with them and can change the password
          afterward. We won&apos;t show this password again.
        </SheetDescription>
      </SheetHeader>

      <SheetBody className="space-y-4">
        <div className="rounded-md border border-accent/40 bg-accent/[0.04] p-4 space-y-3">
          <div className="flex items-center gap-2 text-accent">
            <KeyRound className="size-4" />
            <p className="text-sm font-medium">One-time credentials</p>
          </div>

          <div className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
            <span className="text-muted-foreground">Email</span>
            <span className="font-mono">{creds.email}</span>
            <span className="text-muted-foreground">Temp password</span>
            <span className="font-mono select-all">{creds.password}</span>
          </div>
        </div>

        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Email-based invitations land with Phase 1F. Until then this is the
          way to get a new employee logged in. The password isn&apos;t stored
          in a way we can show you again — copy it now.
        </p>
      </SheetBody>

      <SheetFooter>
        <Button type="button" variant="outline" onClick={copyAll}>
          {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          {copied ? 'Copied' : 'Copy email + password'}
        </Button>
        <Button type="button" onClick={onDone}>
          Done
        </Button>
      </SheetFooter>
    </>
  );
}
