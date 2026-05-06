/**
 * Standard page-header treatment used at the top of every authenticated app
 * page. Title in serif, subtitle in muted sans, optional actions row aligned
 * right, optional "back" breadcrumb above the title.
 *
 * Used to keep type and spacing rhythm consistent across pages — if every
 * page composes its own header, the app feels stitched together. Centralizing
 * here means design tweaks apply everywhere at once.
 */

import Link from 'next/link';
import { ChevronLeft } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  back?: { href: string; label: string };
  className?: string;
}

export function PageHeader({ title, description, actions, back, className }: PageHeaderProps) {
  return (
    <div className={cn('mb-8', className)}>
      {back ? (
        <Link
          href={back.href}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-3"
        >
          <ChevronLeft className="size-3.5" />
          {back.label}
        </Link>
      ) : null}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
            {title}
          </h1>
          {description ? (
            <p className="text-sm text-muted-foreground mt-1.5">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}
