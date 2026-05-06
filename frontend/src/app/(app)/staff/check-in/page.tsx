/**
 * `/staff/check-in` — staff time-tracking surface (clock in / clock out,
 * today's hours, time-entry corrections).
 *
 * Placeholder until Phase 2I lands. The right tool rail in the
 * calendar already exposes a "Employee check-in" placeholder panel
 * for the per-shift quick clock-in/out interaction; this page will
 * be the comprehensive view (history, edits, export to payroll).
 */

import { Clock } from 'lucide-react';

import { PageHeader } from '@/components/page-header';
import { Card, CardContent } from '@/components/ui/card';

export default function StaffCheckInPage() {
  return (
    <div className="px-10 py-10 max-w-7xl">
      <PageHeader
        title="Staff check-in"
        description="Clock in and out, see today's hours, edit past time entries, and export to payroll."
      />
      <ComingSoonCard
        icon={<Clock className="size-6" />}
        title="Time tracking"
        body="Clock-in / clock-out flow, today's hours by staff, manager edits to past entries, and CSV export to payroll. The calendar's right-rail 'Employee check-in' panel will hook into the same data model."
        phase="Phase 2I · Time tracking"
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
