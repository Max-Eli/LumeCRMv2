/**
 * Add-employee bottom sheet.
 *
 * Mounted from `/staff/employees`'s "Add employee" button (owner +
 * manager only — backend re-validates `MANAGE_STAFF`). Slides up from
 * the bottom of the viewport, centered with `max-w-2xl` (matches the
 * New Appointment sheet treatment).
 *
 * Form: email, role (Select), optional job title (Select), bookable
 * toggle. On submit, hits `POST /api/memberships/invite/` which sends
 * the recipient a tokenized link by email. The recipient clicks the
 * link, lands on `/accept-invitation/<token>`, types their name +
 * password, and is logged in.
 *
 * Replaces the older temp-password-reveal flow (which is still
 * available via `useCreateEmployee` for attaching existing-user
 * accounts — the invite endpoint rejects those because the accept
 * page refuses to clobber an existing password). See ADR 0019.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Mail } from 'lucide-react';
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
  type Invitation,
  ROLE_LABELS,
  type StaffRole,
  useInviteEmployee,
} from '@/lib/tenant';

const schema = z.object({
  email: z.string().email('Enter a valid email'),
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
  /** Called after a successful invitation is sent — parent might
   *  want to refresh the staff page's pending-invites list. */
  onInvited?: (invitation: Invitation) => void;
}

export function AddEmployeeSheet({ open, onOpenChange, onInvited }: AddEmployeeSheetProps) {
  const invite = useInviteEmployee();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: '',
      role: 'front_desk',
      job_title_id: null,
      is_bookable: false,
    },
  });

  // Reset form whenever the sheet closes/reopens.
  useEffect(() => {
    if (open) form.reset();
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
    invite.mutate(
      {
        email: values.email.trim(),
        role: values.role,
        job_title_id: values.job_title_id ?? null,
        is_bookable: values.is_bookable,
      },
      {
        onSuccess: (invitation) => {
          toast.success(`Invitation sent to ${invitation.email}`);
          onInvited?.(invitation);
          onOpenChange(false);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 403) {
            toast.error("You don't have permission to invite employees.");
          } else if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
            const body = err.body as Record<string, string[] | string>;
            // Backend uses `detail` for service-layer rejections (already
            // a member, pending invitation outstanding); field-validator
            // errors land under named field keys.
            const detail =
              'detail' in body
                ? Array.isArray(body.detail) ? body.detail[0] : String(body.detail)
                : (() => {
                    const firstField = Object.keys(body)[0];
                    return firstField
                      ? Array.isArray(body[firstField])
                        ? (body[firstField] as string[])[0]
                        : String(body[firstField])
                      : 'Could not send invitation.';
                  })();
            toast.error(detail);
          } else {
            toast.error('Could not send invitation. Please try again.');
          }
        },
      },
    );
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="max-w-2xl">
        <SheetHeader>
          <SheetTitle>Invite an employee</SheetTitle>
          <SheetDescription>
            We&apos;ll email them a link to set their own password and
            join {/* tenant name comes from the email subject; sheet
            doesn't have it in context here */} your team.
          </SheetDescription>
        </SheetHeader>

        <form onSubmit={onSubmit} className="contents">
          <SheetBody className="space-y-4">
            <Field>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input id="email" type="email" autoFocus {...form.register('email')} />
              <p className="text-[11px] text-muted-foreground mt-1">
                Where to send the invitation. They&apos;ll enter their name and
                password on the accept page when they click the link.
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
              disabled={invite.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={invite.isPending}>
              <Mail className="size-4" />
              {invite.isPending ? 'Sending…' : 'Send invitation'}
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}
