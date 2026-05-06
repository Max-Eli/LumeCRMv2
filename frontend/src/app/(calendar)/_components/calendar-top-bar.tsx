/**
 * Top chrome for the booking calendar workspace.
 *
 * Three regions:
 *   left   — Lumè wordmark with a "Calendar" sub-label, also serves as the
 *            navigate-back-to-dashboard affordance
 *   center — client search (the front desk's most-used affordance)
 *   right  — primary action ("New appointment")
 *
 * Date controls, filters, and the view toggle live in `CalendarFilterBar`
 * below. Keeping them out of the top bar reduces clutter and gives the search
 * input the room it needs.
 */

'use client';

import { Plus } from 'lucide-react';
import Link from 'next/link';

import { BrandMark } from '@/components/brand-mark';
import { Button } from '@/components/ui/button';

import { CalendarSearch } from './calendar-search';

export interface CalendarTopBarProps {
  onNewAppointment?: () => void;
}

export function CalendarTopBar({ onNewAppointment }: CalendarTopBarProps) {
  return (
    <header className="shrink-0 border-b bg-background">
      <div className="flex items-center justify-between gap-4 px-6 py-3">
        <Link
          href="/dashboard"
          className="flex items-center gap-2 group shrink-0"
          aria-label="Back to dashboard"
        >
          <BrandMark variant="lockup" size={32} className="opacity-80 group-hover:opacity-100 transition-opacity" />
          <span className="text-muted-foreground/60">·</span>
          <span className="text-sm text-muted-foreground">Calendar</span>
        </Link>

        <div className="flex-1 flex justify-center">
          <CalendarSearch />
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button onClick={onNewAppointment} disabled={!onNewAppointment}>
            <Plus className="size-4" />
            New appointment
          </Button>
        </div>
      </div>
    </header>
  );
}
