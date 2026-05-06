/**
 * Status indicator — colored dot + label.
 *
 * Used for customer status, appointment status, invoice status, etc. The
 * colored dot reads faster than a colored chip and feels more refined.
 */

import { cn } from '@/lib/utils';

type Tone = 'success' | 'neutral' | 'warning' | 'destructive' | 'info';

const TONE_CLASSES: Record<Tone, string> = {
  success: 'bg-emerald-500',
  neutral: 'bg-muted-foreground/40',
  warning: 'bg-amber-500',
  destructive: 'bg-red-500',
  info: 'bg-sky-500',
};

export interface StatusBadgeProps {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}

export function StatusBadge({ tone = 'neutral', children, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs font-medium text-foreground/80 capitalize',
        className,
      )}
    >
      <span className={cn('size-1.5 rounded-full', TONE_CLASSES[tone])} aria-hidden />
      {children}
    </span>
  );
}

/** Map a customer status string to the StatusBadge tone. */
export function customerStatusTone(status: string): Tone {
  if (status === 'active') return 'success';
  if (status === 'blocked') return 'destructive';
  return 'neutral';
}
