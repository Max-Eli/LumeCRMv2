/**
 * `/staff/payroll` — payroll runs, commission calculations, tip
 * distributions, paystubs.
 *
 * Placeholder until the payroll feature lands (Phase 2 — exact phase
 * TBD; depends on time-tracking from Phase 2I + commission rules from
 * the service-catalog work).
 */

import { Wallet } from 'lucide-react';

import { PageHeader } from '@/components/page-header';
import { Card, CardContent } from '@/components/ui/card';

export default function StaffPayrollPage() {
  return (
    <div className="px-10 py-10 max-w-7xl">
      <PageHeader
        title="Payroll"
        description="Pay periods, commission calculations, tip distributions, and paystubs for your staff."
      />
      <ComingSoonCard
        icon={<Wallet className="size-6" />}
        title="Payroll runs"
        body="Bi-weekly / monthly pay periods, hourly + commission + tip splits, paystub PDFs, and a CSV export for your bookkeeper or payroll provider. Depends on time-tracking (Phase 2I) and per-service commission rules (currently a placeholder on the service detail page)."
        phase="Phase 2 · Payroll"
      />
    </div>
  );
}

function ComingSoonCard({
  icon,
  title,
  body,
  phase,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  phase: string;
}) {
  return (
    <Card>
      <CardContent className="px-8 py-12 text-center">
        <div className="inline-flex size-12 items-center justify-center rounded-full bg-accent/15 text-accent mb-4">
          {icon}
        </div>
        <h2 className="font-serif text-xl font-semibold tracking-tight">{title}</h2>
        <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
          {body}
        </p>
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground/80 mt-4 font-medium">
          Coming with {phase}
        </p>
      </CardContent>
    </Card>
  );
}
