/**
 * Vertical tool rail on the right side of the calendar workspace.
 *
 * Each tool is Messages, Check-in, Price check, etc. Clicking opens
 * that tool's panel; clicking the same tool again closes it. Active
 * state gets the accent treatment so the user always knows what's
 * open.
 *
 * Two display modes:
 *
 *   - **Expanded** (default) — ~208 px wide, icon + label per row,
 *     "Soon" tag on placeholder tools. Shown to first-time users so
 *     they don't have to guess what each glyph means.
 *   - **Collapsed** — 48 px wide, icon-only with a tooltip on hover.
 *     Reclaims horizontal space once the operator knows the layout.
 *
 * The user toggles between modes via a header button (Lucide
 * `PanelRightClose` / `PanelRightOpen`). Preference persists to
 * `localStorage` so it survives reload and is per-browser, not per-tenant.
 *
 * The order of tools is intentional: highest-frequency front-desk tools
 * sit at the top, less-frequent below, settings at the bottom (UX
 * convention).
 */

'use client';

import {
  BarChart3,
  ClipboardCheck,
  Clock,
  Globe,
  MessageSquare,
  Package,
  PanelRightClose,
  PanelRightOpen,
  Receipt,
  Settings2,
} from 'lucide-react';
import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';

export type CalendarTool =
  | 'messages'
  | 'check-in'
  | 'price-check'
  | 'online-bookings'
  | 'waitlist'
  | 'packages'
  | 'reports'
  | 'view-settings';

export interface ToolDef {
  id: CalendarTool;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** When set, the tool is a placeholder and shows a "coming with Phase X" panel. */
  comingPhase?: string;
}

export const TOOLS: readonly ToolDef[] = [
  { id: 'messages', label: 'Messages', icon: MessageSquare },
  { id: 'check-in', label: 'Employee check-in', icon: ClipboardCheck, comingPhase: 'Phase 2I · Time tracking' },
  { id: 'price-check', label: 'Price check', icon: Receipt },
  { id: 'online-bookings', label: 'Online bookings', icon: Globe },
  { id: 'waitlist', label: 'Waitlist', icon: Clock },
  { id: 'packages', label: 'Custom packages', icon: Package, comingPhase: 'Phase 2B · Packages + 2A · POS' },
  { id: 'reports', label: 'Reports (today)', icon: BarChart3 },
  { id: 'view-settings', label: 'View settings', icon: Settings2 },
];

const COLLAPSED_KEY = 'lume_calendar_rail_collapsed';

export interface RightToolRailProps {
  active: CalendarTool | null;
  onToggle: (tool: CalendarTool) => void;
}

export function RightToolRail({ active, onToggle }: RightToolRailProps) {
  // Default expanded — first-time users need to see the labels. The
  // pref persists per-browser via localStorage, restored on mount so
  // we don't flash the wrong state.
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const stored = window.localStorage.getItem(COLLAPSED_KEY);
    if (stored === '1') setCollapsed(true);
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0');
      }
      return next;
    });
  };

  return (
    <aside
      className={cn(
        // Hidden on touch widths — the rail's icon strip is a desktop
        // affordance that crowds the day grid on a phone. Mobile users
        // get the list view (forced in CalendarPage) and don't need it.
        'hidden sm:flex',
        'shrink-0 border-l bg-sidebar flex-col py-2 transition-[width] duration-200',
        // Expanded: 240 px (w-60). Sized so the longest tool labels —
        // "Employee check-in" + the right-aligned "Soon" pill — sit
        // comfortably without truncation. Collapsed: 48 px icon-only.
        collapsed ? 'w-12 items-center' : 'w-60',
      )}
      aria-label="Calendar tools"
    >
      <RailHeader collapsed={collapsed} onToggle={toggleCollapsed} />

      <nav className={cn('flex flex-col gap-1', collapsed ? 'items-center' : 'px-2')}>
        {TOOLS.map((tool) => (
          <ToolButton
            key={tool.id}
            tool={tool}
            collapsed={collapsed}
            active={active === tool.id}
            onClick={() => onToggle(tool.id)}
          />
        ))}
      </nav>
    </aside>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────

function RailHeader({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  if (collapsed) {
    return (
      <div className="mb-2 flex justify-center">
        <button
          type="button"
          onClick={onToggle}
          aria-label="Expand tools"
          title="Expand tools"
          className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors"
        >
          <PanelRightOpen className="size-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="mb-2 px-2 flex items-center justify-between">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
        Tools
      </p>
      <button
        type="button"
        onClick={onToggle}
        aria-label="Collapse tools"
        title="Collapse"
        className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors"
      >
        <PanelRightClose className="size-4" />
      </button>
    </div>
  );
}

function ToolButton({
  tool,
  collapsed,
  active,
  onClick,
}: {
  tool: ToolDef;
  collapsed: boolean;
  active: boolean;
  onClick: () => void;
}) {
  const Icon = tool.icon;

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-pressed={active}
        aria-label={tool.label}
        title={tool.label + (tool.comingPhase ? ' · coming soon' : '')}
        className={cn(
          'relative inline-flex size-9 items-center justify-center rounded-md transition-colors',
          active
            ? 'bg-accent text-accent-foreground'
            : 'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
        )}
      >
        <Icon className="size-4" />
        {tool.comingPhase ? (
          <span
            className="absolute top-1 right-1 size-1 rounded-full bg-muted-foreground/40"
            aria-hidden
          />
        ) : null}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={tool.comingPhase ? `${tool.label} · coming soon` : tool.label}
      className={cn(
        'flex items-center gap-2.5 h-9 rounded-md px-2.5 text-sm transition-colors text-left',
        active
          ? 'bg-accent text-accent-foreground'
          : 'text-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
      )}
    >
      <Icon className="size-4 shrink-0" />
      <span className="truncate flex-1">{tool.label}</span>
      {tool.comingPhase ? (
        <span
          className={cn(
            'shrink-0 text-[10px] uppercase tracking-wide px-1.5 py-px rounded',
            active
              ? 'bg-accent-foreground/15 text-accent-foreground/90'
              : 'bg-muted text-muted-foreground',
          )}
        >
          Soon
        </span>
      ) : null}
    </button>
  );
}
