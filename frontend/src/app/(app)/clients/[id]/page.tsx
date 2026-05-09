/**
 * Customer detail page — the "client 360" view.
 *
 * Tabbed shell with the customer's hero (avatar + name + status + referral code)
 * persistent across all tabs. Active tab is driven by `?tab=` so deep links
 * work. Each tab renders independently — most are placeholders today, awaiting
 * features built in later phases.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import {
  Ban,
  Calendar,
  Camera,
  Check,
  CheckCircle2,
  CircleAlert,
  ClipboardCopy,
  ClipboardList,
  CreditCard,
  FileText,
  Gift,
  Heart,
  Image as ImageIcon,
  Mail,
  MapPin,
  Megaphone,
  Package,
  Pill,
  Shield,
  ShoppingBag,
  Stethoscope,
  User,
  Users as UsersIcon,
  Wallet,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { use, useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { InitialsAvatar } from '@/components/initials-avatar';
import { PageHeader } from '@/components/page-header';
import { StatusBadge, customerStatusTone } from '@/components/status-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type FormSubmissionListItem,
  useEmailSubmission,
  useFormSubmissions,
} from '@/lib/form-submissions';
import { cn } from '@/lib/utils';
import {
  type CustomerDetail,
  useCustomer,
  useUpdateCustomer,
} from '@/lib/customers';
import {
  type SendLogRow,
  useCustomerMarketingHistory,
} from '@/lib/marketing';

import { AppointmentsTab } from './_tabs/appointments-tab';
import { GiftCardsTab } from './_tabs/gift-cards-tab';
import { MembershipsTab } from './_tabs/memberships-tab';
import { NotesTab } from './_tabs/notes-tab';
import { PackagesTab } from './_tabs/packages-tab';
import { WalletTab } from './_tabs/wallet-tab';

// ── Tab definitions ──────────────────────────────────────────────────────

type TabDef = {
  id: string;
  label: string;
  /** When set, this tab is a placeholder and renders ComingSoonTab. */
  comingPhase?: string;
};

const TABS: readonly TabDef[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'profile', label: 'Profile' },
  { id: 'appointments', label: 'Appointments' },
  { id: 'notes', label: 'Notes' },
  { id: 'products', label: 'Products', comingPhase: 'Phase 2A · POS' },
  { id: 'memberships', label: 'Memberships' },
  { id: 'packages', label: 'Packages' },
  { id: 'gift-cards', label: 'Gift cards' },
  { id: 'wallet', label: 'Wallet' },
  { id: 'payments', label: 'Payments', comingPhase: 'Phase 2A · POS' },
  { id: 'forms', label: 'Treatment forms' },
  { id: 'referrals', label: 'Referrals' },
  { id: 'prescriptions', label: 'Prescriptions', comingPhase: 'Phase 4D · Prescriptions' },
  { id: 'marketing', label: 'Marketing' },
  { id: 'gallery', label: 'Gallery', comingPhase: 'Phase 4B · Photos' },
];

const TAB_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  overview: User,
  profile: User,
  appointments: Calendar,
  notes: ClipboardList,
  products: ShoppingBag,
  memberships: CreditCard,
  packages: Package,
  'gift-cards': Gift,
  wallet: Wallet,
  payments: CreditCard,
  forms: FileText,
  referrals: UsersIcon,
  prescriptions: Pill,
  marketing: Megaphone,
  gallery: ImageIcon,
};

// ── Page ─────────────────────────────────────────────────────────────────

export default function ClientDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const customerId = Number(id);
  const { data: customer, isLoading, error } = useCustomer(customerId);

  const searchParams = useSearchParams();
  const requestedTab = searchParams.get('tab') ?? 'overview';
  const activeTab = TABS.find((t) => t.id === requestedTab) ?? TABS[0];

  if (isLoading) {
    return <div className="px-4 sm:px-8 py-8 sm:py-10 text-sm text-muted-foreground">Loading client…</div>;
  }
  if (error || !customer) {
    return (
      <div className="px-4 sm:px-8 py-8 sm:py-10">
        <PageHeader
          title="Client not found"
          back={{ href: '/clients', label: 'Back to clients' }}
        />
        <p className="text-sm text-destructive">Failed to load this client.</p>
      </div>
    );
  }

  return (
    <div>
      {/* Back link — scrolls away with content */}
      <div className="px-4 sm:px-8 pt-6 sm:pt-10">
        <PageHeader title="" back={{ href: '/clients', label: 'Back to clients' }} className="mb-0" />
      </div>

      {/*
       * Sticky band — hero + referral chip + tabs nav stay pinned to the top
       * of <main> while the tab content scrolls beneath. Backdrop blur masks
       * content scrolling under it; the tabs nav's own border-b provides the
       * lower edge so we don't double up on lines.
       */}
      <div className="sticky top-0 z-10 mt-3 sm:mt-4 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="px-4 sm:px-8 pt-2">
          <Hero customer={customer} />
          <ReferralCodeChip code={customer.referral_code} />
          <TabsNav active={activeTab.id} />
        </div>
      </div>

      {/* Tab content — scrolls under the sticky band */}
      <div className="px-4 sm:px-8 mt-6 sm:mt-8 pb-10">
        {activeTab.id === 'overview' ? (
          <OverviewTab customer={customer} />
        ) : activeTab.id === 'profile' ? (
          <ProfileTab customer={customer} />
        ) : activeTab.id === 'referrals' ? (
          <ReferralsTab customer={customer} />
        ) : activeTab.id === 'forms' ? (
          <FormsTab customerId={customer.id} />
        ) : activeTab.id === 'notes' ? (
          <NotesTab customerId={customer.id} />
        ) : activeTab.id === 'appointments' ? (
          <AppointmentsTab customerId={customer.id} />
        ) : activeTab.id === 'wallet' ? (
          <WalletTab customerId={customer.id} />
        ) : activeTab.id === 'packages' ? (
          <PackagesTab customerId={customer.id} />
        ) : activeTab.id === 'memberships' ? (
          <MembershipsTab customerId={customer.id} />
        ) : activeTab.id === 'gift-cards' ? (
          <GiftCardsTab customerId={customer.id} />
        ) : activeTab.id === 'marketing' ? (
          <MarketingTab customer={customer} />
        ) : (
          <ComingSoonTab tab={activeTab} />
        )}
      </div>
    </div>
  );
}

// ── Hero ─────────────────────────────────────────────────────────────────

function Hero({ customer }: { customer: CustomerDetail }) {
  return (
    <div className="flex items-center gap-3 sm:gap-5">
      <InitialsAvatar name={customer.full_name} size="xl" />
      <div className="min-w-0 flex-1">
        <h1 className="font-serif text-2xl sm:text-3xl font-semibold tracking-tight truncate">
          {customer.full_name}
        </h1>
        {customer.preferred_name && customer.first_name !== customer.preferred_name ? (
          <p className="text-xs sm:text-sm text-muted-foreground mt-1 truncate">
            Legal: {customer.first_name} {customer.last_name}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2 sm:gap-3 mt-2 sm:mt-3">
          <StatusBadge tone={customerStatusTone(customer.status)}>{customer.status}</StatusBadge>
          {customer.tags.map((t) => (
            <Badge
              key={t.id}
              variant="outline"
              style={{ borderColor: `${t.color}66`, color: t.color }}
              className="font-normal"
            >
              {t.name}
            </Badge>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Referral code chip ───────────────────────────────────────────────────

function ReferralCodeChip({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success('Referral code copied');
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error('Could not copy to clipboard');
    }
  };

  return (
    <div className="mt-4 inline-flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-1.5 text-sm">
      <UsersIcon className="size-3.5 text-muted-foreground" />
      <span className="text-muted-foreground text-xs uppercase tracking-wide">Referral</span>
      <code className="font-mono font-medium tracking-wider">{code || '—'}</code>
      {code ? (
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Copy referral code"
          title="Copy"
        >
          {copied ? <Check className="size-3.5" /> : <ClipboardCopy className="size-3.5" />}
        </button>
      ) : null}
    </div>
  );
}

// ── Tabs nav ─────────────────────────────────────────────────────────────

function TabsNav({ active }: { active: string }) {
  const pathname = usePathname();
  return (
    <div className="mt-5 -mx-2 overflow-x-auto">
      <nav className="flex min-w-max border-b" role="tablist">
        {TABS.map((tab) => {
          const Icon = TAB_ICONS[tab.id] ?? User;
          const isActive = active === tab.id;
          return (
            <Link
              key={tab.id}
              href={`${pathname}?tab=${tab.id}`}
              scroll={false}
              role="tab"
              aria-selected={isActive}
              className={cn(
                'inline-flex items-center gap-2 px-3 py-2.5 text-sm whitespace-nowrap border-b-2 -mb-px transition-colors',
                isActive
                  ? 'border-accent text-foreground font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30',
              )}
            >
              <Icon className="size-3.5" />
              {tab.label}
              {tab.comingPhase ? (
                <span className="size-1.5 rounded-full bg-muted-foreground/30" aria-label="coming soon" />
              ) : null}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

// ── Overview tab ─────────────────────────────────────────────────────────

function OverviewTab({ customer }: { customer: CustomerDetail }) {
  const dob = customer.date_of_birth ? formatDate(customer.date_of_birth) : null;
  const age = customer.date_of_birth ? computeAge(customer.date_of_birth) : null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <ContactCell icon={<Mail className="size-4" />} label="Email" value={customer.email} />
        <ContactCell icon={<Mail className="size-4" />} label="Phone" value={customer.phone} />
        <ContactCell
          icon={<User className="size-4" />}
          label="Date of birth"
          value={dob ? `${dob}${age ? ` · ${age} yr` : ''}` : null}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SectionCard title="Address" icon={<MapPin className="size-4" />}>
          <Row label="Street" value={customer.address_line1} />
          <Row label="Apt / Suite" value={customer.address_line2} />
          <Row label="City" value={customer.city} />
          <Row label="State" value={customer.state} />
          <Row label="Zip" value={customer.zip_code} />
        </SectionCard>

        <SectionCard title="Emergency contact" icon={<Shield className="size-4" />}>
          <Row label="Name" value={customer.emergency_name} />
          <Row label="Phone" value={customer.emergency_phone} />
          <Row label="Relationship" value={customer.emergency_relationship} />
        </SectionCard>

        <SectionCard title="Marketing" icon={<Megaphone className="size-4" />}>
          <Row label="Email opt-in" value={customer.email_opt_in ? 'Yes' : 'No'} />
          <Row label="SMS opt-in" value={customer.sms_opt_in ? 'Yes' : 'No'} />
          <Row label="Referral source" value={customer.referral_source} />
        </SectionCard>

        <SectionCard title="Demographics" icon={<Heart className="size-4" />}>
          <Row label="Sex" value={customer.sex} />
          <Row
            label="Skin type (Fitzpatrick)"
            value={customer.skin_type_fitzpatrick ? `Type ${customer.skin_type_fitzpatrick}` : null}
          />
        </SectionCard>
      </div>

      <Card className="border-accent/30 bg-accent/[0.04]">
        <CardHeader className="flex-row items-center gap-2 space-y-0">
          <Stethoscope className="size-4 text-accent" />
          <CardTitle className="text-sm font-medium uppercase tracking-wide">
            Medical (PHI)
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
          <PhiBlock label="Medical history" value={customer.medical_history} />
          <PhiBlock label="Allergies" value={customer.allergies} />
          <PhiBlock label="Medications" value={customer.medications} />
        </CardContent>
      </Card>

      {customer.notes ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium uppercase tracking-wide">Notes</CardTitle>
          </CardHeader>
          <CardContent className="text-sm whitespace-pre-wrap">{customer.notes}</CardContent>
        </Card>
      ) : null}

      <p className="text-xs text-muted-foreground">
        Created {formatDate(customer.created_at)} · Updated {formatDate(customer.updated_at)}
      </p>
    </div>
  );
}

// ── Profile tab (editable form) ──────────────────────────────────────────

const profileSchema = z.object({
  first_name: z.string().min(1, 'First name is required').max(100),
  last_name: z.string().min(1, 'Last name is required').max(100),
  preferred_name: z.string().max(100),
  email: z.string().email('Enter a valid email').or(z.literal('')),
  phone: z.string().max(20),
  date_of_birth: z.string(),
  sex: z.enum(['', 'female', 'male', 'other', 'prefer_not_to_say']),
  status: z.enum(['active', 'inactive', 'blocked']),
  address_line1: z.string().max(200),
  address_line2: z.string().max(200),
  city: z.string().max(100),
  state: z.string().max(2),
  zip_code: z.string().max(10),
  emergency_name: z.string().max(200),
  emergency_phone: z.string().max(20),
  emergency_relationship: z.string().max(50),
  medical_history: z.string(),
  allergies: z.string(),
  medications: z.string(),
  skin_type_fitzpatrick: z.string(),
  notes: z.string(),
  referral_source: z.string().max(100),
  email_opt_in: z.boolean(),
  sms_opt_in: z.boolean(),
});

type ProfileFormValues = z.infer<typeof profileSchema>;

function customerToFormValues(c: CustomerDetail): ProfileFormValues {
  return {
    first_name: c.first_name ?? '',
    last_name: c.last_name ?? '',
    preferred_name: c.preferred_name ?? '',
    email: c.email ?? '',
    phone: c.phone ?? '',
    date_of_birth: c.date_of_birth ?? '',
    sex: (c.sex || '') as ProfileFormValues['sex'],
    status: c.status,
    address_line1: c.address_line1 ?? '',
    address_line2: c.address_line2 ?? '',
    city: c.city ?? '',
    state: c.state ?? '',
    zip_code: c.zip_code ?? '',
    emergency_name: c.emergency_name ?? '',
    emergency_phone: c.emergency_phone ?? '',
    emergency_relationship: c.emergency_relationship ?? '',
    medical_history: c.medical_history ?? '',
    allergies: c.allergies ?? '',
    medications: c.medications ?? '',
    skin_type_fitzpatrick: c.skin_type_fitzpatrick != null ? String(c.skin_type_fitzpatrick) : '',
    notes: c.notes ?? '',
    referral_source: c.referral_source ?? '',
    email_opt_in: c.email_opt_in,
    sms_opt_in: c.sms_opt_in,
  };
}

function ProfileTab({ customer }: { customer: CustomerDetail }) {
  const router = useRouter();
  const update = useUpdateCustomer(customer.id);
  const form = useForm<ProfileFormValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: customerToFormValues(customer),
  });
  const watched = form.watch();

  // Reset whenever the loaded customer changes (e.g., navigating between clients)
  useEffect(() => {
    form.reset(customerToFormValues(customer));
  }, [customer, form]);

  const onSubmit = (values: ProfileFormValues) => {
    const skin = values.skin_type_fitzpatrick.trim();
    const payload = {
      ...values,
      date_of_birth: values.date_of_birth || null,
      sex: values.sex || undefined,
      state: values.state ? values.state.toUpperCase() : '',
      skin_type_fitzpatrick: skin === '' ? null : Number(skin),
    };
    update.mutate(payload, {
      onSuccess: (updated) => {
        toast.success('Profile saved');
        form.reset(customerToFormValues(updated));
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
          const fieldErrors = err.body as Record<string, string[] | string>;
          for (const [field, msgs] of Object.entries(fieldErrors)) {
            const message = Array.isArray(msgs) ? msgs[0] : String(msgs);
            form.setError(field as keyof ProfileFormValues, { message });
          }
          toast.error('Please fix the highlighted fields.');
        } else {
          toast.error('Save failed. Please try again.');
        }
      },
    });
  };

  const isDirty = form.formState.isDirty;

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
      <div className="space-y-10">
        <Section title="Identity" icon={<User className="size-4" />}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field data-invalid={form.formState.errors.first_name ? true : undefined}>
              <FieldLabel htmlFor="first_name">First name</FieldLabel>
              <Input id="first_name" {...form.register('first_name')} />
              {form.formState.errors.first_name ? (
                <FieldError>{form.formState.errors.first_name.message}</FieldError>
              ) : null}
            </Field>
            <Field data-invalid={form.formState.errors.last_name ? true : undefined}>
              <FieldLabel htmlFor="last_name">Last name</FieldLabel>
              <Input id="last_name" {...form.register('last_name')} />
              {form.formState.errors.last_name ? (
                <FieldError>{form.formState.errors.last_name.message}</FieldError>
              ) : null}
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="preferred_name">Preferred name</FieldLabel>
            <Input id="preferred_name" {...form.register('preferred_name')} />
          </Field>
          <Field>
            <FieldLabel htmlFor="status">Status</FieldLabel>
            <Select
              value={watched.status}
              onValueChange={(value) =>
                form.setValue('status', value as ProfileFormValues['status'], { shouldDirty: true })
              }
            >
              <SelectTrigger id="status" className="w-full md:w-1/2">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="inactive">Inactive</SelectItem>
                <SelectItem value="blocked">Blocked</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </Section>

        <Section title="Contact" icon={<User className="size-4" />}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field data-invalid={form.formState.errors.email ? true : undefined}>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input id="email" type="email" {...form.register('email')} />
              {form.formState.errors.email ? (
                <FieldError>{form.formState.errors.email.message}</FieldError>
              ) : null}
            </Field>
            <Field>
              <FieldLabel htmlFor="phone">Phone</FieldLabel>
              <Input id="phone" type="tel" {...form.register('phone')} />
            </Field>
          </div>
        </Section>

        <Section title="Personal" icon={<Heart className="size-4" />}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field>
              <FieldLabel htmlFor="date_of_birth">Date of birth</FieldLabel>
              <Input id="date_of_birth" type="date" {...form.register('date_of_birth')} />
            </Field>
            <Field>
              <FieldLabel htmlFor="sex">Sex</FieldLabel>
              <Select
                value={watched.sex}
                onValueChange={(value) =>
                  form.setValue('sex', (value || '') as ProfileFormValues['sex'], { shouldDirty: true })
                }
              >
                <SelectTrigger id="sex" className="w-full">
                  <SelectValue placeholder="Select sex" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="female">Female</SelectItem>
                  <SelectItem value="male">Male</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                  <SelectItem value="prefer_not_to_say">Prefer not to say</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="skin_type_fitzpatrick">Skin type (Fitzpatrick 1–6)</FieldLabel>
            <Input
              id="skin_type_fitzpatrick"
              type="number"
              min={1}
              max={6}
              className="w-32"
              {...form.register('skin_type_fitzpatrick')}
            />
          </Field>
        </Section>

        <Section title="Address" icon={<MapPin className="size-4" />}>
          <Field>
            <FieldLabel htmlFor="address_line1">Street</FieldLabel>
            <Input id="address_line1" {...form.register('address_line1')} />
          </Field>
          <Field>
            <FieldLabel htmlFor="address_line2">Apt / Suite</FieldLabel>
            <Input id="address_line2" {...form.register('address_line2')} />
          </Field>
          <div className="grid grid-cols-1 md:grid-cols-6 gap-4">
            <Field className="md:col-span-3">
              <FieldLabel htmlFor="city">City</FieldLabel>
              <Input id="city" {...form.register('city')} />
            </Field>
            <Field className="md:col-span-1">
              <FieldLabel htmlFor="state">State</FieldLabel>
              <Input id="state" maxLength={2} {...form.register('state')} />
            </Field>
            <Field className="md:col-span-2">
              <FieldLabel htmlFor="zip_code">ZIP</FieldLabel>
              <Input id="zip_code" {...form.register('zip_code')} />
            </Field>
          </div>
        </Section>

        <Section title="Emergency contact" icon={<Shield className="size-4" />}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Field>
              <FieldLabel htmlFor="emergency_name">Name</FieldLabel>
              <Input id="emergency_name" {...form.register('emergency_name')} />
            </Field>
            <Field>
              <FieldLabel htmlFor="emergency_phone">Phone</FieldLabel>
              <Input id="emergency_phone" type="tel" {...form.register('emergency_phone')} />
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="emergency_relationship">Relationship</FieldLabel>
            <Input id="emergency_relationship" {...form.register('emergency_relationship')} />
          </Field>
        </Section>

        <Section title="Medical (PHI)" icon={<Stethoscope className="size-4 text-accent" />}>
          <Field>
            <FieldLabel htmlFor="medical_history">Medical history</FieldLabel>
            <textarea
              id="medical_history"
              rows={3}
              className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              {...form.register('medical_history')}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="allergies">Allergies</FieldLabel>
            <textarea
              id="allergies"
              rows={2}
              className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              {...form.register('allergies')}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="medications">Medications</FieldLabel>
            <textarea
              id="medications"
              rows={2}
              className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              {...form.register('medications')}
            />
          </Field>
        </Section>

        <Section title="CRM" icon={<ClipboardList className="size-4" />}>
          <Field>
            <FieldLabel htmlFor="referral_source">Referral source</FieldLabel>
            <Input
              id="referral_source"
              placeholder="Instagram, friend, walk-in…"
              {...form.register('referral_source')}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="notes">General notes</FieldLabel>
            <textarea
              id="notes"
              rows={3}
              className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              {...form.register('notes')}
            />
          </Field>
        </Section>

        <Section title="Communication preferences" icon={<Megaphone className="size-4" />}>
          <div className="space-y-3">
            <CheckboxRow
              id="email_opt_in"
              label="Send appointment confirmations and reminders by email"
              checked={watched.email_opt_in}
              onChange={(v) => form.setValue('email_opt_in', v, { shouldDirty: true })}
            />
            <CheckboxRow
              id="sms_opt_in"
              label="Send appointment confirmations and reminders by text message"
              checked={watched.sms_opt_in}
              onChange={(v) => form.setValue('sms_opt_in', v, { shouldDirty: true })}
            />
          </div>
        </Section>
      </div>

      {/* Sticky save bar — its negative margins must match the parent
          container's px-* so it spans edge-to-edge at every breakpoint. */}
      <div className="sticky bottom-0 -mx-4 sm:-mx-8 mt-8 sm:mt-10 px-4 sm:px-8 py-3 sm:py-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            {isDirty ? 'Unsaved changes' : 'No changes'}
          </p>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!isDirty || update.isPending}
              onClick={() => form.reset(customerToFormValues(customer))}
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
  );
}

// ── Referrals tab ────────────────────────────────────────────────────────

function ReferralsTab({ customer }: { customer: CustomerDetail }) {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium uppercase tracking-wide">
            Their referral code
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <code className="font-mono text-2xl font-medium tracking-[0.2em] px-4 py-2 rounded-md bg-muted">
              {customer.referral_code}
            </code>
          </div>
          <p className="text-sm text-muted-foreground">
            Share this code with potential clients. Once reward redemption ships in Phase 2H,
            successful referrals can credit both the referrer and the new client according to
            your tenant's referral program settings.
          </p>
        </CardContent>
      </Card>

      <Card className="bg-muted/30">
        <CardHeader>
          <CardTitle className="text-sm font-medium uppercase tracking-wide">
            Referral history
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-2">
          <p>
            <strong className="text-foreground">Referred by:</strong> coming with Phase 1A.2 (the
            "Referred by code" input on the new-client form).
          </p>
          <p>
            <strong className="text-foreground">People they've referred:</strong> coming with
            Phase 1A.2.
          </p>
          <p>
            <strong className="text-foreground">Reward credit balance + redemption history:</strong>{' '}
            coming with Phase 2H.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Forms tab (Phase 1D session 2/3) ───────────────────────────────────

function FormsTab({ customerId }: { customerId: number }) {
  const { data: submissions, isLoading, error } = useFormSubmissions({ customerId });

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          Loading forms…
        </CardContent>
      </Card>
    );
  }
  if (error) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-destructive">
          Could not load forms.
        </CardContent>
      </Card>
    );
  }

  const all = submissions ?? [];
  const pending = all.filter((s) => s.status === 'pending');
  const completed = all.filter((s) => s.status === 'completed');
  const voided = all.filter((s) => s.status === 'voided');

  if (all.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="py-12 text-center">
          <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground mb-4">
            <FileText className="size-5" />
          </div>
          <p className="text-sm text-foreground font-medium">No forms yet</p>
          <p className="text-xs text-muted-foreground mt-1.5 max-w-md mx-auto leading-relaxed">
            Forms get auto-assigned when this customer books an appointment for
            a service mapped to a consent template (or on their first
            appointment ever for the intake form).
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {pending.length > 0 ? (
        <SubmissionGroup
          title="Pending signature"
          subtitle="Open the signing link to share with the client (or hand them an iPad)."
          submissions={pending}
        />
      ) : null}
      {completed.length > 0 ? (
        <SubmissionGroup
          title="Signed"
          subtitle={`${completed.length} signed form${completed.length === 1 ? '' : 's'} on file.`}
          submissions={completed}
        />
      ) : null}
      {voided.length > 0 ? (
        <SubmissionGroup
          title="Voided"
          subtitle="Replaced or invalidated. Kept for the audit trail."
          submissions={voided}
          tone="muted"
        />
      ) : null}
    </div>
  );
}

function SubmissionGroup({
  title,
  subtitle,
  submissions,
  tone,
}: {
  title: string;
  subtitle: string;
  submissions: FormSubmissionListItem[];
  tone?: 'muted';
}) {
  return (
    <section>
      <header className="mb-3">
        <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
          {title}
        </h2>
        <p className="text-xs text-muted-foreground/80 mt-0.5">{subtitle}</p>
      </header>
      <ul className="border rounded-lg divide-y bg-card">
        {submissions.map((sub) => (
          <SubmissionRow key={sub.id} submission={sub} tone={tone} />
        ))}
      </ul>
    </section>
  );
}

function SubmissionRow({
  submission,
  tone,
}: {
  submission: FormSubmissionListItem;
  tone?: 'muted';
}) {
  return (
    <li
      className={cn(
        'flex items-start gap-4 px-4 py-3',
        tone === 'muted' && 'bg-muted/30',
      )}
    >
      <div className="inline-flex size-8 items-center justify-center rounded-md border bg-background shrink-0">
        <FileText className="size-3.5 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{submission.template_name}</p>
        <p className="text-[11px] text-muted-foreground truncate mt-0.5">
          {submission.template_form_type === 'intake' ? 'Intake' : 'Consent'} ·
          v{submission.template_version_at_assignment}
          {submission.signed_at ? (
            <> · signed {new Date(submission.signed_at).toLocaleDateString()}</>
          ) : null}
          {submission.voided_at ? (
            <> · voided {new Date(submission.voided_at).toLocaleDateString()}</>
          ) : null}
        </p>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        {submission.status === 'completed' ? (
          <EmailSignedCopyButton submissionId={submission.id} />
        ) : null}
        {submission.status === 'pending' ? (
          <a
            href={`/sign/${submission.token}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md border bg-card text-xs font-medium hover:bg-muted transition-colors"
          >
            Open for signing
          </a>
        ) : submission.status === 'completed' ? (
          <a
            href={`/sign/${submission.token}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            View signed
          </a>
        ) : null}
      </div>
    </li>
  );
}

/**
 * Operator-initiated "email this signed copy to the client" button.
 * Two-step confirmation flow so we don't fire PHI emails on
 * accidental clicks: first click → button shifts to a confirm
 * affordance ("Email to client?" with Cancel + Confirm). Operator's
 * second click triggers the send.
 *
 * Backend is owner+manager gated and audit-logged with the
 * recipient's domain only — see ADR 0012.
 */
function EmailSignedCopyButton({ submissionId }: { submissionId: number }) {
  const me = useCurrentMembership();
  const canEmail = me?.role === 'owner' || me?.role === 'manager';
  const send = useEmailSubmission(submissionId);
  const [confirming, setConfirming] = useState(false);

  if (!canEmail) return null;

  if (confirming) {
    return (
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => setConfirming(false)}
          disabled={send.isPending}
          className="inline-flex items-center h-7 px-2 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => {
            send.mutate(undefined, {
              onSuccess: (resp) => {
                toast.success(`Sent to ${resp.recipient}`);
                setConfirming(false);
              },
              onError: (err) => {
                if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
                  const body = err.body as { detail?: string };
                  toast.error(body.detail ?? 'Could not send. Please try again.');
                } else if (err instanceof ApiError && err.status === 403) {
                  toast.error("You don't have permission to email signed forms.");
                } else {
                  toast.error('Could not send. Please try again.');
                }
                setConfirming(false);
              },
            });
          }}
          disabled={send.isPending}
          className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-foreground text-background text-xs font-medium hover:bg-foreground/90 transition-colors disabled:opacity-50"
        >
          {send.isPending ? 'Sending…' : 'Confirm send'}
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      title="Email a signed copy to the client (only if they asked for one)"
      className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
    >
      <Mail className="size-3.5" />
      Email
    </button>
  );
}

// ── Marketing tab (Phase 1L) ─────────────────────────────────────────────

function MarketingTab({ customer }: { customer: CustomerDetail }) {
  const update = useUpdateCustomer(customer.id);
  const history = useCustomerMarketingHistory(customer.id);

  const onTogglePromoConsent = (channel: 'email' | 'sms', value: boolean) => {
    const field =
      channel === 'email' ? 'email_marketing_opt_in' : 'sms_marketing_opt_in';
    update.mutate(
      { [field]: value },
      {
        onSuccess: () =>
          toast.success(
            value
              ? `${channel.toUpperCase()} marketing opt-in saved`
              : `${channel.toUpperCase()} marketing opt-in removed`,
          ),
        onError: () => toast.error('Could not save. Please try again.'),
      },
    );
  };

  const emailSuppressed = Boolean(customer.email_marketing_suppressed_at);
  const smsSuppressed = Boolean(customer.sms_marketing_suppressed_at);

  return (
    <div className="space-y-6">
      {/* Channel state */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium uppercase tracking-wide">
            Promotional consent
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            Separate from booking confirmations + reminders, which are
            transactional and always sent. Suppression overrides opt-in:
            once a client unsubscribes or bounces, they&apos;re removed from
            campaigns until manually re-engaged.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <ChannelConsentRow
            label="Email marketing"
            optIn={customer.email_marketing_opt_in}
            consentAt={customer.email_marketing_consent_at}
            consentSource={customer.email_marketing_consent_source}
            suppressedAt={customer.email_marketing_suppressed_at}
            suppressionSource={customer.email_marketing_suppression_source}
            disabled={update.isPending || emailSuppressed}
            suppressed={emailSuppressed}
            onChange={(v) => onTogglePromoConsent('email', v)}
          />
          <div className="border-t" />
          <ChannelConsentRow
            label="SMS marketing"
            optIn={customer.sms_marketing_opt_in}
            consentAt={customer.sms_marketing_consent_at}
            consentSource={customer.sms_marketing_consent_source}
            suppressedAt={customer.sms_marketing_suppressed_at}
            suppressionSource={customer.sms_marketing_suppression_source}
            disabled={update.isPending || smsSuppressed}
            suppressed={smsSuppressed}
            onChange={(v) => onTogglePromoConsent('sms', v)}
          />
        </CardContent>
      </Card>

      {/* Send history */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium uppercase tracking-wide">
            Send history
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            Most recent 50 marketing sends. Suppressed rows are kept as
            an audit record of &ldquo;we attempted but didn&apos;t
            send&rdquo; &mdash; that&apos;s the proof CAN-SPAM and HIPAA
            require.
          </p>
        </CardHeader>
        <CardContent>
          {history.isLoading ? (
            <p className="text-sm text-muted-foreground py-4">Loading…</p>
          ) : history.error ? (
            <p className="text-sm text-destructive py-4">
              Could not load history.
            </p>
          ) : !history.data || history.data.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4">
              No marketing sent to this client yet.
            </p>
          ) : (
            <ul className="border rounded-md divide-y">
              {history.data.map((row) => (
                <SendHistoryRow key={row.id} row={row} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ChannelConsentRow({
  label,
  optIn,
  consentAt,
  consentSource,
  suppressedAt,
  suppressionSource,
  disabled,
  suppressed,
  onChange,
}: {
  label: string;
  optIn: boolean;
  consentAt: string | null;
  consentSource: string;
  suppressedAt: string | null;
  suppressionSource: string;
  disabled: boolean;
  suppressed: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{label}</p>
        {suppressed ? (
          <div className="mt-1.5 flex items-start gap-1.5 text-xs text-amber-700">
            <Ban className="size-3.5 shrink-0 mt-0.5" />
            <span>
              Suppressed
              {suppressedAt ? <> on {formatDate(suppressedAt)}</> : null}
              {suppressionSource ? (
                <> via {humanizeSource(suppressionSource)}</>
              ) : null}
              . Re-enable only after explicit re-confirmation.
            </span>
          </div>
        ) : optIn ? (
          <div className="mt-1.5 flex items-start gap-1.5 text-xs text-muted-foreground">
            <CheckCircle2 className="size-3.5 shrink-0 mt-0.5 text-emerald-600" />
            <span>
              Opted in
              {consentAt ? <> on {formatDate(consentAt)}</> : null}
              {consentSource ? <> via {humanizeSource(consentSource)}</> : null}.
            </span>
          </div>
        ) : (
          <div className="mt-1.5 flex items-start gap-1.5 text-xs text-muted-foreground">
            <CircleAlert className="size-3.5 shrink-0 mt-0.5" />
            <span>Not opted in. Won&apos;t receive promotional sends.</span>
          </div>
        )}
      </div>
      <label className="flex items-center gap-2 shrink-0 cursor-pointer">
        <Checkbox
          checked={optIn && !suppressed}
          onCheckedChange={(v) => onChange(v === true)}
          disabled={disabled}
        />
        <span className="text-xs text-muted-foreground">
          {suppressed ? 'Locked' : optIn ? 'On' : 'Off'}
        </span>
      </label>
    </div>
  );
}

function SendHistoryRow({ row }: { row: SendLogRow }) {
  const sentAt = row.sent_at ?? row.created_at;
  const channelLabel = row.channel === 'email' ? 'Email' : 'SMS';
  const tone =
    row.status === 'delivered' || row.status === 'sent'
      ? 'sent'
      : row.status === 'suppressed'
        ? 'suppressed'
        : row.status === 'failed'
          ? 'failed'
          : 'pending';
  return (
    <li className="flex items-start gap-3 px-3 py-2.5">
      <div
        className={cn(
          'size-7 rounded-md inline-flex items-center justify-center shrink-0 mt-0.5',
          tone === 'sent' && 'bg-emerald-50 text-emerald-700',
          tone === 'suppressed' && 'bg-amber-50 text-amber-700',
          tone === 'failed' && 'bg-red-50 text-red-700',
          tone === 'pending' && 'bg-muted text-muted-foreground',
        )}
      >
        {row.channel === 'email' ? (
          <Mail className="size-3.5" />
        ) : (
          <Megaphone className="size-3.5" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{row.campaign_name}</p>
        <p className="text-[11px] text-muted-foreground mt-0.5">
          {channelLabel} · {formatDateTime(sentAt)}
          {row.status === 'suppressed' && row.suppression_reason ? (
            <> · suppressed ({humanizeSource(row.suppression_reason)})</>
          ) : null}
          {row.status === 'failed' ? <> · failed</> : null}
        </p>
      </div>
      <span
        className={cn(
          'text-[11px] uppercase tracking-wide font-medium px-2 py-0.5 rounded-md shrink-0',
          tone === 'sent' && 'bg-emerald-50 text-emerald-700',
          tone === 'suppressed' && 'bg-amber-50 text-amber-700',
          tone === 'failed' && 'bg-red-50 text-red-700',
          tone === 'pending' && 'bg-muted text-muted-foreground',
        )}
      >
        {row.status}
      </span>
    </li>
  );
}

function humanizeSource(value: string): string {
  if (!value) return '';
  return value.replaceAll('_', ' ');
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

// ── Coming soon tab ──────────────────────────────────────────────────────

function ComingSoonTab({ tab }: { tab: TabDef }) {
  const Icon = TAB_ICONS[tab.id] ?? Camera;
  return (
    <Card className="border-dashed">
      <CardContent className="py-16 text-center">
        <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground mb-4">
          <Icon className="size-5" />
        </div>
        <h3 className="font-serif text-xl font-semibold tracking-tight">{tab.label}</h3>
        <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto">
          This section will fill in when the underlying feature ships.
        </p>
        <p className="text-xs text-muted-foreground mt-3 uppercase tracking-wide">
          Coming with {tab.comingPhase}
        </p>
      </CardContent>
    </Card>
  );
}

// ── Shared helpers ───────────────────────────────────────────────────────

function ContactCell({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide mb-1.5">
        {icon}
        {label}
      </div>
      <p className="text-sm font-medium truncate">{value || '—'}</p>
    </div>
  );
}

function SectionCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
        <span className="text-muted-foreground">{icon}</span>
        <CardTitle className="text-sm font-medium uppercase tracking-wide">{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm space-y-2">{children}</CardContent>
    </Card>
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

function CheckboxRow({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label htmlFor={id} className="flex items-start gap-3 text-sm cursor-pointer">
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(v) => onChange(Boolean(v))}
        className="mt-0.5"
      />
      <span className="leading-relaxed">{label}</span>
    </label>
  );
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="font-medium text-right truncate">{value || '—'}</span>
    </div>
  );
}

function PhiBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1.5">{label}</p>
      <p className="whitespace-pre-wrap text-foreground/90">{value || '—'}</p>
    </div>
  );
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}

function computeAge(iso: string) {
  const dob = new Date(iso);
  if (Number.isNaN(dob.getTime())) return null;
  const now = new Date();
  let age = now.getFullYear() - dob.getFullYear();
  const m = now.getMonth() - dob.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < dob.getDate())) age--;
  return age;
}
