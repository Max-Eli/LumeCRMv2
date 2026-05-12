/**
 * Top chrome for the booking calendar workspace.
 *
 * Three regions:
 *   left   — Lumè wordmark, also serves as the navigate-back-to-dashboard
 *            affordance
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
      <div className="flex items-center justify-between gap-2 sm:gap-4 px-3 sm:px-6 py-2 sm:py-3">
        <Link
          href="/dashboard"
          className="flex items-center gap-2 group shrink-0"
          aria-label="Back to dashboard"
        >
          {/* Lockup with text on tablet+. Just the brand icon on phones to
              save horizontal room for the search field. */}
          <BrandMark
            variant="lockup"
            size={32}
            className="hidden sm:inline-flex opacity-80 group-hover:opacity-100 transition-opacity"
          />
          <BrandMark
            variant="icon"
            size={28}
            className="sm:hidden opacity-80 group-hover:opacity-100 transition-opacity"
          />
        </Link>

        <div className="flex-1 flex justify-center min-w-0">
          <CalendarSearch />
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            onClick={onNewAppointment}
            disabled={!onNewAppointment}
            aria-label="New appointment"
          >
            <Plus className="size-4" />
            {/* Hide the label on phones so the search field has more
                horizontal room; the icon + aria-label still convey
                the action. */}
            <span className="hidden sm:inline">New appointment</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
