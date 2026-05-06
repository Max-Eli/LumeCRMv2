/**
 * Shared placeholder shell for not-yet-built tool panels.
 *
 * Each placeholder panel uses this to render a consistent "coming with Phase X"
 * card. Concrete panels (Messages, Check-in, etc.) wrap this and add their
 * own short summary of what the tool will do once shipped, so the UI never
 * feels dead — it tells the user exactly what to expect.
 */

import { ChevronRight } from 'lucide-react';

export interface PlaceholderPanelProps {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  summary: string;
  bullets?: string[];
  phase: string;
}

export function PlaceholderPanel({
  icon: Icon,
  title,
  summary,
  bullets,
  phase,
}: PlaceholderPanelProps) {
  return (
    <div className="p-4">
      <div className="rounded-lg border border-dashed bg-muted/30 p-5">
        <div className="inline-flex size-10 items-center justify-center rounded-full bg-card text-muted-foreground border mb-3">
          <Icon className="size-4" />
        </div>
        <h3 className="font-serif text-base font-semibold tracking-tight">{title}</h3>
        <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">{summary}</p>

        {bullets && bullets.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {bullets.map((b) => (
              <li key={b} className="flex items-start gap-2 text-xs text-muted-foreground">
                <ChevronRight className="size-3 mt-0.5 shrink-0 text-muted-foreground/50" />
                <span>{b}</span>
              </li>
            ))}
          </ul>
        ) : null}

        <p className="mt-5 pt-4 border-t border-dashed text-[11px] uppercase tracking-wide text-muted-foreground">
          Coming with {phase}
        </p>
      </div>
    </div>
  );
}
