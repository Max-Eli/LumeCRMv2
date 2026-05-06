/**
 * Sidebar location switcher.
 *
 * Renders only when the tenant has 2+ active locations — single-location
 * tenants don't pay any IA tax for a feature they can't use. Picking a
 * location writes the `lume_active_location` cookie via
 * `useSwitchLocation()`, which also invalidates the location-scoped
 * queries (currently appointments — its day-window timezone shifts per
 * site). The calendar / dashboard rerender against the new site
 * immediately, no reload.
 *
 * Visually sits under the tenant name in the sidebar header — the
 * "context strip" pattern: tenant identifies WHO you are (the
 * business), the switcher identifies WHERE you are within that
 * business. Always shows the current selection's name + a default-
 * star indicator if applicable.
 *
 * Collapsed sidebar (icon rail) condenses to just the MapPin icon
 * with the location name as a hover tooltip; clicking still opens the
 * popover. Keeps the chrome consistent with the rest of the rail.
 */

'use client';

import { Check, MapPin, Star } from 'lucide-react';
import { useState } from 'react';

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  type Location,
  hasMultipleLocations,
  locationDisplayName,
  useActiveLocation,
  useLocations,
  useSwitchLocation,
} from '@/lib/locations';
import { cn } from '@/lib/utils';

export interface LocationSwitcherProps {
  /** Sidebar collapsed state — drives the compact icon-only render.
   *  Ignored when `variant='inline'`. */
  collapsed?: boolean;
  /** Where the switcher is being rendered:
   *
   *    'sidebar' — the original sidebar header placement (default).
   *                Tinted with sidebar-accent colors to fit the rail.
   *    'inline'  — page-context placement (e.g. on `/staff/schedule`).
   *                Card-styled trigger that reads as a regular page
   *                control and includes a leading "Location:" label
   *                so the operator knows what they're switching.
   *
   *  Both variants share the same popover content + cookie-writing
   *  switch behavior. Single-location tenants get nothing rendered
   *  in either variant (no IA tax for a feature they can't use).
   */
  variant?: 'sidebar' | 'inline';
}

export function LocationSwitcher({
  collapsed = false,
  variant = 'sidebar',
}: LocationSwitcherProps) {
  const { data: locations } = useLocations();
  const { location: active } = useActiveLocation();
  const switchLocation = useSwitchLocation();
  const [open, setOpen] = useState(false);

  // Hide entirely for single-location tenants — they have nothing to
  // switch to. The IA stays clean for the 80% case.
  if (!hasMultipleLocations(locations)) return null;

  const activeLocations = (locations ?? []).filter((l) => l.is_active);
  const activeName = active ? locationDisplayName(active) : 'Pick a location';
  const isInline = variant === 'inline';

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={`Active location: ${activeName}. Click to switch.`}
            title={collapsed && !isInline ? activeName : undefined}
            className={cn(
              'inline-flex items-center gap-2 rounded-md text-sm transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
              isInline
                ? cn(
                    // Page-context styling: card surface with a soft
                    // border that reads as a regular control, not a
                    // sidebar element.
                    'h-8 px-2.5 border bg-card hover:bg-muted',
                    'aria-expanded:bg-muted aria-expanded:border-ring/40',
                  )
                : cn(
                    'w-full',
                    'border border-sidebar-border/60 bg-sidebar-accent/40',
                    'hover:bg-sidebar-accent hover:border-sidebar-border',
                    'aria-expanded:bg-sidebar-accent aria-expanded:border-sidebar-border',
                    collapsed ? 'h-9 justify-center p-2' : 'h-9 px-2.5',
                  ),
            )}
          >
            <MapPin
              className={cn(
                'size-3.5 shrink-0',
                isInline ? 'text-accent' : 'text-muted-foreground',
              )}
              aria-hidden
            />
            {collapsed && !isInline ? null : (
              <>
                {isInline ? (
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground/80 font-medium">
                    Location
                  </span>
                ) : null}
                <span className="min-w-0 flex-1 truncate text-left font-medium">
                  {activeName}
                </span>
                {active?.is_default ? (
                  <Star className="size-3 shrink-0 text-accent" aria-hidden />
                ) : null}
                <Chevron />
              </>
            )}
          </button>
        }
      />
      <PopoverContent
        align={collapsed && !isInline ? 'start' : 'center'}
        side={collapsed && !isInline ? 'right' : 'bottom'}
        sideOffset={6}
        className="w-60 p-1"
      >
        <p className="px-2 py-1.5 text-[10px] uppercase tracking-wide text-muted-foreground/80 font-medium">
          Switch location
        </p>
        <ul className="space-y-0.5">
          {activeLocations.map((loc) => (
            <LocationOption
              key={loc.id}
              location={loc}
              isActive={active?.id === loc.id}
              onPick={() => {
                if (active?.id !== loc.id) switchLocation(loc.slug);
                setOpen(false);
              }}
            />
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function LocationOption({
  location,
  isActive,
  onPick,
}: {
  location: Location;
  isActive: boolean;
  onPick: () => void;
}) {
  const subtitle = [location.city, location.state].filter(Boolean).join(', ');
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        className={cn(
          'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
          isActive
            ? 'bg-accent/15 text-foreground'
            : 'text-foreground/90 hover:bg-muted',
        )}
        aria-pressed={isActive}
      >
        <MapPin className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate font-medium">{locationDisplayName(location)}</span>
            {location.is_default ? (
              <Star
                className="size-3 shrink-0 text-accent"
                aria-label="Default location"
              />
            ) : null}
          </div>
          {subtitle ? (
            <p className="text-[11px] text-muted-foreground truncate">{subtitle}</p>
          ) : null}
        </div>
        {isActive ? (
          <Check className="size-3.5 shrink-0 text-accent" aria-hidden />
        ) : null}
      </button>
    </li>
  );
}

function Chevron() {
  // Tiny chevron — matches the popover-trigger affordance the rest of
  // the chrome uses (Select, etc.). Inline SVG to avoid pulling
  // another lucide import for a single 3x3 glyph.
  return (
    <svg
      aria-hidden
      width="10"
      height="10"
      viewBox="0 0 10 10"
      className="shrink-0 text-muted-foreground/70"
    >
      <path
        d="M2 4l3 3 3-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
