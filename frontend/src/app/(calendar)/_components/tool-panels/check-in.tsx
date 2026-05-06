'use client';

import { ClipboardCheck } from 'lucide-react';

import { PlaceholderPanel } from './_placeholder';

export function CheckInPanel({ phase }: { phase?: string }) {
  return (
    <PlaceholderPanel
      icon={ClipboardCheck}
      title="Employee check-in"
      summary="Front desk clocks staff in and out from here as they arrive. Self-service punch from the staff app comes alongside. Hours feed into payroll exports."
      bullets={[
        'List of bookable staff with current state (clocked-in / out / on break)',
        'One-click clock in / clock out + today’s running total per person',
        'Forgot-to-punch correction with manager approval',
        'Audit log on every punch (IP + source) for FLSA posture',
      ]}
      phase={phase ?? 'Phase 2I · Time tracking'}
    />
  );
}
