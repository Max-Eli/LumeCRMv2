/**
 * `/portal/profile` — customer-editable profile + marketing consents.
 *
 * Read-only fields (name, email) appear at the top with a "contact
 * the front desk to change" hint — those changes flow through staff
 * for audit + identity-verification reasons.
 *
 * Editable: phone, email-marketing opt-in, SMS-marketing opt-in.
 * Saving the SMS-marketing toggle on stamps `sms_marketing_consent_at`
 * + sources it to 'portal' on the backend, which satisfies the TCPA
 * consent-trail requirement.
 *
 * Sign-out lives here too — placed at the bottom of the profile page
 * because that's where users intuitively look for it.
 */

'use client';

import { Check, Loader2, LogOut } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { ApiError } from '@/lib/api';
import {
  type PortalCustomer,
  useLogout,
  usePortalMe,
  useUpdatePortalProfile,
} from '@/lib/portal';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export default function PortalProfilePage() {
  const router = useRouter();
  const { data: me, isLoading } = usePortalMe();
  const logout = useLogout();

  const onLogout = async () => {
    await logout.mutateAsync();
    router.replace('/portal/login');
  };

  return (
    <div className="max-w-3xl mx-auto w-full px-6 py-10 space-y-8">
      <header>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          Profile
        </h1>
        <p className="text-sm text-muted-foreground mt-1.5">
          Update your contact info and marketing preferences.
        </p>
      </header>

      {isLoading || !me ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <>
          <ReadOnlySection me={me} />
          <EditableForm me={me} />
        </>
      )}

      <section className="rounded-xl border bg-card shadow-sm p-5 flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Sign out</p>
          <p className="text-xs text-muted-foreground">
            End your portal session on this device.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={onLogout}
          disabled={logout.isPending}
        >
          {logout.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <LogOut className="size-4" />
          )}
          Sign out
        </Button>
      </section>
    </div>
  );
}

function ReadOnlySection({ me }: { me: PortalCustomer }) {
  return (
    <section className="rounded-xl border bg-card shadow-sm p-5 space-y-3">
      <header className="flex items-baseline justify-between">
        <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
          Identity
        </h2>
        <p className="text-[11px] text-muted-foreground">
          Contact the front desk to change
        </p>
      </header>
      <dl className="text-sm space-y-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 sm:gap-3">
          <dt className="text-muted-foreground text-xs sm:text-sm">Name</dt>
          <dd className="font-medium">{me.first_name} {me.last_name}</dd>
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 sm:gap-3">
          <dt className="text-muted-foreground text-xs sm:text-sm">Email</dt>
          <dd>{me.email}</dd>
        </div>
      </dl>
    </section>
  );
}

function EditableForm({ me }: { me: PortalCustomer }) {
  const [phone, setPhone] = useState(me.phone);
  const [emailMarketing, setEmailMarketing] = useState(me.email_marketing_opt_in);
  const [smsMarketing, setSmsMarketing] = useState(me.sms_marketing_opt_in);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const update = useUpdatePortalProfile();

  // Re-sync local state when the source-of-truth changes (e.g. after
  // a successful save or a window-focus refetch).
  useEffect(() => {
    setPhone(me.phone);
    setEmailMarketing(me.email_marketing_opt_in);
    setSmsMarketing(me.sms_marketing_opt_in);
  }, [me]);

  const dirty =
    phone !== me.phone ||
    emailMarketing !== me.email_marketing_opt_in ||
    smsMarketing !== me.sms_marketing_opt_in;

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await update.mutateAsync({
        phone,
        email_marketing_opt_in: emailMarketing,
        sms_marketing_opt_in: smsMarketing,
      });
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1500);
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, string | string[]>;
        const firstError =
          (Array.isArray(body.phone) ? body.phone[0] : body.phone) ??
          (Array.isArray(body.detail) ? body.detail[0] : body.detail);
        setError(typeof firstError === 'string' ? firstError : 'Could not save.');
      } else {
        setError('Could not save.');
      }
    }
  };

  return (
    <form onSubmit={onSave} className="rounded-xl border bg-card shadow-sm overflow-hidden">
      <div className="p-5 space-y-5">
        <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
          Contact &amp; preferences
        </h2>
        <div>
          <label htmlFor="phone" className="text-xs font-medium mb-1.5 block">
            Phone
          </label>
          <Input
            id="phone"
            type="tel"
            autoComplete="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="(555) 123-4567"
          />
          <p className="mt-1 text-[10px] text-muted-foreground">
            Used for appointment confirmations and reminders.
          </p>
        </div>

        <fieldset className="space-y-3">
          <legend className="text-xs font-medium mb-1">Marketing</legend>
          <Toggle
            id="email-marketing"
            label="Email promotions"
            description="Special offers, seasonal campaigns, and new-service announcements."
            checked={emailMarketing}
            onChange={setEmailMarketing}
          />
          <Toggle
            id="sms-marketing"
            label="SMS promotions"
            description="Same idea via text. We never share your phone number."
            checked={smsMarketing}
            onChange={setSmsMarketing}
          />
        </fieldset>

        {error ? <p className="text-xs text-destructive">{error}</p> : null}
      </div>

      <div className="px-5 py-3 border-t bg-muted/30 flex items-center justify-end gap-2">
        <Button
          type="submit"
          disabled={!dirty || update.isPending}
          style={{
            background: 'var(--portal-brand, #1f2937)',
            color: '#fff',
          }}
        >
          {update.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : savedFlash ? (
            <Check className="size-4" />
          ) : null}
          {savedFlash ? 'Saved' : 'Save changes'}
        </Button>
      </div>
    </form>
  );
}

function Toggle({
  id,
  label,
  description,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 p-3 rounded-lg border bg-muted/20">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium cursor-pointer">
          {label}
        </label>
        <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors',
          checked ? '' : 'bg-muted-foreground/30',
        )}
        style={checked ? { background: 'var(--portal-brand, #1f2937)' } : undefined}
      >
        <span
          className={cn(
            'inline-block size-3.5 transform rounded-full bg-white shadow transition-transform',
            checked ? 'translate-x-5' : 'translate-x-1',
          )}
        />
      </button>
    </div>
  );
}
