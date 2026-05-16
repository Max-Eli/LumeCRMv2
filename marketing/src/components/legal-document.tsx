/**
 * Shared chrome for /privacy, /terms, and /baa.
 *
 * Editorial restraint applied to legal documents — a constrained
 * reading column, restrained type, numbered section markers in the
 * burgundy accent, and a top-of-page notice block for the "this
 * isn't your final contract" disclaimer. Reads like a magazine
 * legal column, not a generic Terms-and-Conditions dump.
 *
 * Three components compose:
 *
 *   <LegalDocument>   — the outer container with the prose-styled
 *                       reading column.
 *   <LegalNotice>     — the highlighted box at the top of each
 *                       legal page. Use once per page.
 *   <LegalSection>    — a numbered section with eyebrow + heading
 *                       + the prose body.
 *
 * Body content (paragraphs, lists, etc.) uses unstyled HTML — the
 * outer container applies prose styles via a `legal-prose` CSS
 * class defined in globals.css.
 */

import type { ReactNode } from 'react';

export function LegalDocument({ children }: { children: ReactNode }) {
  return (
    <section>
      <div className="mx-auto max-w-3xl px-6 lg:px-10 py-20 lg:py-28">
        <div className="legal-prose space-y-12">{children}</div>
      </div>
    </section>
  );
}

export function LegalNotice({ children }: { children: ReactNode }) {
  return (
    <aside
      role="note"
      className="border-l-2 border-accent bg-foreground/[0.03] px-6 py-5 text-sm leading-relaxed text-foreground/80"
    >
      <p className="eyebrow text-foreground/60">Notice</p>
      <p className="mt-3">{children}</p>
    </aside>
  );
}

export function LegalSection({
  number,
  title,
  children,
}: {
  number: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="border-t border-foreground/15 pt-8">
      <div className="flex items-baseline gap-4">
        <span className="font-display text-2xl text-accent/80">{number}</span>
        <h2 className="font-serif text-2xl font-medium text-foreground sm:text-3xl">
          {title}
        </h2>
      </div>
      <div className="mt-5 space-y-4 text-base leading-[1.85] text-foreground/85">
        {children}
      </div>
    </section>
  );
}
