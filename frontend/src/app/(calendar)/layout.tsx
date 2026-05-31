/**
 * Calendar route-group shell — sibling of `(app)` and `(auth)`.
 *
 * The booking calendar is a dedicated workspace, not just another tab. This
 * layout owns its own viewport: full width, no left sidebar, with calendar-
 * specific chrome (top bar holding date controls, view toggle, search, and
 * the New Appointment action). Closing the calendar — via the "Back" link in
 * the top bar — returns the user to `/dashboard` in the `(app)` shell.
 *
 * Auth is gated here independently of `(app)` because route groups don't
 * inherit each other's layouts. Same redirect-to-login pattern.
 */

'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { EscalationNotifier } from '@/components/ai-inbox/escalation-notifier';
import { useUser } from '@/lib/auth';

export default function CalendarShellLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data: user, isLoading } = useUser();

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace('/login');
    }
  }, [isLoading, user, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (!user) return null;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-background">
      {children}
      {/* AI escalation notifier — same instance as the (app) shell so
          the bell badge + toast are omnipresent regardless of which
          route group the operator is in. */}
      <EscalationNotifier />
    </div>
  );
}
