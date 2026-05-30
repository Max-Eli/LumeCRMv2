/**
 * UpsellModal — fires when a backend endpoint returns 402 (the
 * ``PlanFeatureRequired`` permission gate).
 *
 * Architecture: listens for the global ``lume:plan-feature-required``
 * CustomEvent that ``lib/api.ts`` dispatches on every 402. Decouples
 * the modal from the call sites — every API call across the app
 * gets the same friendly upsell UX, no per-component wiring needed.
 *
 * The 402 body shape (from ``apps.tenants.plan_permissions``):
 *   {
 *     detail: "Your current plan (starter) does not include the
 *              \"email_marketing\" feature.",
 *     code: "feature_not_in_plan",
 *     feature: "email_marketing",
 *     current_plan: "starter",
 *     upgrade_url: "/settings/billing"
 *   }
 *
 * Mounted once in the (app) layout — siblings with the children
 * tree so any page in the CRM benefits. Not rendered in the portal
 * or auth surfaces.
 */

'use client';

import { ArrowRight, Sparkles } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useCurrentMembership } from '@/lib/auth';

/** Wire-shape echoed from the backend 402 body. */
interface PlanFeatureRequiredPayload {
  detail: string;
  code: string;
  feature: string;
  current_plan: string;
  upgrade_url: string;
}

export function UpsellModal() {
  const membership = useCurrentMembership();
  const [payload, setPayload] = useState<PlanFeatureRequiredPayload | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<PlanFeatureRequiredPayload>;
      if (!ce.detail || typeof ce.detail !== 'object') return;
      // Only one upsell at a time — if a modal is already open, the
      // second 402 just gets dropped. Avoids stacking + reduces
      // confusion when an operator triggers multiple Pro features in
      // quick succession.
      setPayload(ce.detail);
    };
    window.addEventListener('lume:plan-feature-required', handler);
    return () => window.removeEventListener('lume:plan-feature-required', handler);
  }, []);

  if (!payload) return null;

  const isOwner = membership?.role === 'owner';
  const featureCopy = FEATURE_COPY[payload.feature] ?? {
    title: humanize(payload.feature),
    body: 'This feature isn’t included in your current plan.',
  };

  return (
    <Dialog
      open={!!payload}
      onOpenChange={(open) => !open && setPayload(null)}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-amber-500" aria-hidden />
            Upgrade to use {featureCopy.title}
          </DialogTitle>
          <DialogDescription>
            {featureCopy.body}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3 text-sm">
          <p>
            Your spa is currently on the{' '}
            <span className="font-medium text-foreground capitalize">
              {payload.current_plan}
            </span>{' '}
            plan. Pro tier includes {featureCopy.title.toLowerCase()} plus the
            full clinical + marketing + ops surface.
          </p>
          {isOwner ? (
            <p className="text-xs text-muted-foreground">
              Pro is a sales-assisted upgrade — book a quick demo and we’ll
              walk you through the workflow + activate it the same day.
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Ask the account owner to upgrade — only owners can change the
              plan tier.
            </p>
          )}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setPayload(null)}
          >
            Not now
          </Button>
          {isOwner ? (
            <>
              <Button
                type="button"
                variant="outline"
                nativeButton={false}
                render={(props) => (
                  <Link {...props} href="/org/billing">
                    View billing
                  </Link>
                )}
              />
              <Button
                type="button"
                nativeButton={false}
                render={(props) => (
                  <a
                    {...props}
                    href="https://www.lume-crm.com/demo"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Book demo
                    <ArrowRight className="size-3.5" />
                  </a>
                )}
              />
            </>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Per-feature copy ──────────────────────────────────────────────
//
// Per-feature title + body so each upsell speaks the language of
// the specific Pro thing the operator just tried to use. Falls back
// to a humanized key for any feature not enumerated here.

const FEATURE_COPY: Record<string, { title: string; body: string }> = {
  email_marketing: {
    title: 'Email marketing',
    body: 'Send campaigns, build audiences, automate follow-ups. Built into Pro.',
  },
  sms_inbox: {
    title: '2-way SMS inbox',
    body: 'Have full SMS conversations with customers, save replies, automate templates.',
  },
  commissions: {
    title: 'Commissions tracking',
    body: 'Per-provider commission rules, accrual on each invoice close, full payroll-ready reports.',
  },
  payroll_export: {
    title: 'Payroll export',
    body: 'Period-end payroll exports including commissions + time tracking. Pro tier.',
  },
  provider_scheduler: {
    title: 'Per-provider scheduling',
    body: 'Weekly schedules per provider, split shifts, location-specific hours.',
  },
  all_reports: {
    title: 'Advanced reports',
    body: 'All 23+ reports across Financial, Staff, Guests, and Operations categories.',
  },
  white_label_basic: {
    title: 'White-label branding',
    body: 'Your color + logo on the login + public booking page. Pro tier.',
  },
  custom_merchant: {
    title: 'Custom merchant integrations',
    body: 'Bring your own payment processor — Worldpay, Square, Heartland, etc.',
  },
  customer_portal_full: {
    title: 'Full customer portal',
    body: 'Memberships, packages, payment history visible to your clients in their portal.',
  },
  social_integrations: {
    title: 'Social integrations',
    body: 'Instagram + Facebook + WhatsApp DM inbox unified with your CRM.',
  },
};

function humanize(key: string): string {
  return key
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}
