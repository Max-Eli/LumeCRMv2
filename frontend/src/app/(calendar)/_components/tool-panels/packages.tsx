'use client';

import { Package } from 'lucide-react';

import { PlaceholderPanel } from './_placeholder';

export function PackagesPanel({ phase }: { phase?: string }) {
  return (
    <PlaceholderPanel
      icon={Package}
      title="Custom package"
      summary="Build a package right at the front desk: pick the customer, drop in any combination of services, products, and memberships, set quantities and an expiration date, and open the POS to take payment."
      bullets={[
        'Customer search + multi-line builder (services / products / memberships)',
        'Per-line custom price override + total preview with tax',
        'Expiration date picker; package balance tracks redemption per service',
        'On save: creates an Invoice and pushes the user to the POS for payment',
      ]}
      phase={phase ?? 'Phase 2B · Packages + 2A · POS'}
    />
  );
}
