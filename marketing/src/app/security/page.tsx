import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Security & HIPAA',
  description:
    'How Lumè handles patient data: tenant isolation at the database, role-based permissions, append-only audit logging, and AWS infrastructure under a signed BAA.',
};

const COMMITMENTS = [
  {
    label: 'Tenant isolation',
    body:
      'Every PHI-bearing model carries a tenant FK at the database schema level. Queries route through a tenant-scoped manager exclusively. Cross-tenant data access is impossible without explicit code paths that don\'t exist in the API surface.',
    citation: 'ADR 0001',
  },
  {
    label: 'Role-based permissions',
    body:
      'Forty-plus permissions resolved per request from a central catalog. Six default roles — owner, manager, front desk, provider, bookkeeper, marketing — each with a defensible default permission set. Per-user overrides are explicit and audit-logged. Locked permissions cannot be granted ad-hoc.',
    citation: 'ADR 0003',
  },
  {
    label: 'Append-only audit logging',
    body:
      'Every PHI read, every state transition, every report run, every CSV export writes an audit log entry. Production enforces append-only via a Postgres trigger that rejects UPDATE and DELETE on the audit table. Satisfies HIPAA §164.312(b) and SOC 2 CC 6.1.',
    citation: 'ADR 0004',
  },
  {
    label: 'PHI containment',
    body:
      'Audit metadata records what happened, never the PHI itself — a customer name appears in the chart, never in the audit log. Email addresses are reduced to their domain in the audit trail. Reports that surface per-customer data require explicit confirmation before CSV export.',
    citation: 'ADR 0013',
  },
  {
    label: 'Tokenized public flows',
    body:
      '256-bit URL-path tokens (never query string) for the public form-fill page and similar customer-facing surfaces. Single-use for state-changing actions. The rest of the application is session-cookie authenticated with CSRF protection.',
    citation: 'ADR 0011',
  },
  {
    label: 'BAA-eligible infrastructure',
    body:
      'AWS under a signed Business Associate Agreement: Fargate compute, RDS Postgres encrypted at rest with KMS, SES for email with DKIM/SPF/DMARC. Email containing PHI sends only on operator action with the customer\'s request on file.',
    citation: 'ADR 0012',
  },
];

export default function SecurityPage() {
  return (
    <>
      <PageHero
        eyebrow="Security & compliance"
        headline={
          <>
            HIPAA-compliant by{' '}
            <span className="accent-italic">architecture, not by checkbox.</span>
          </>
        }
        standfirst="Lumè was designed from day one with HIPAA compliance baked into every layer: tenant isolation enforced at the database, role-based permissions resolved per request, append-only audit logging on every PHI access, and AWS infrastructure under a signed Business Associate Agreement."
      />

      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <div className="grid gap-16 lg:grid-cols-12">
            {/* Long-form essay */}
            <article className="lg:col-span-7">
              <ScrollReveal>
                <p className="text-lg leading-[1.85] text-foreground/85">
                  Most CRM platforms treat HIPAA compliance as a tier
                  upgrade — a "secure" plan that costs 2x the regular
                  plan and ships with a few extra features bolted on.
                  That model creates a two-track product where the
                  compliance posture is a marketing differentiator, not
                  an architectural one.
                </p>
                <p className="mt-4 text-lg leading-[1.85] text-foreground/85">
                  Lumè doesn't have a "secure tier." Every customer is
                  on the HIPAA-compliant architecture from day one
                  because there's only one architecture. Tenant
                  isolation, role-based permissions, audit logging, and
                  PHI containment are foundational — built into the
                  models and middleware, not patched on as an upsell.
                </p>
              </ScrollReveal>

              <ScrollReveal delay={140}>
                <h2 className="mt-12 eyebrow text-foreground/60">
                  What "HIPAA-compliant" means here
                </h2>
                <p className="mt-4 text-base leading-[1.85] text-foreground/85">
                  The product surface is built on a SOC 2-aligned spine:
                  least privilege, traceability, change management,
                  separation of duties. Production infrastructure runs
                  on AWS services covered by a Business Associate
                  Agreement. Postgres is KMS-encrypted at rest. Email
                  goes through SES with the proper SPF / DKIM / DMARC
                  posture. Backups are encrypted; key rotation is
                  automated; access is logged.
                </p>
                <p className="mt-4 text-base leading-[1.85] text-foreground/85">
                  The product also makes the hard choice consistently.
                  Email containing PHI — a signed-consent copy, for
                  example — sends only when an operator initiates the
                  send, because automated PHI delivery would require
                  per-customer authorization that most spas don't
                  capture today. CSV exports of per-customer data fire
                  a confirmation gate before the download. Every
                  confirmation is logged.
                </p>
              </ScrollReveal>

              <ScrollReveal delay={280}>
                <h2 className="mt-12 eyebrow text-foreground/60">
                  Production posture
                </h2>
                <p className="mt-4 text-base leading-[1.85] text-foreground/85">
                  Lumè's production environment runs on AWS under a
                  signed BAA. Postgres is encrypted at rest with KMS;
                  backups are encrypted; key rotation is automated. SES
                  handles email with DKIM, SPF, and DMARC configured.
                  Audit log tables are append-only at the database
                  trigger level — UPDATE and DELETE statements are
                  rejected.
                </p>
                <p className="mt-4 text-base leading-[1.85] text-foreground/85">
                  SOC 2 Type II is in progress. We can share the in-progress
                  audit scope and a list of mapped controls on request.
                </p>
              </ScrollReveal>
            </article>

            {/* Sidebar of concrete commitments */}
            <aside className="lg:col-span-5">
              <div className="sticky top-8">
                <p className="eyebrow text-foreground/60">Concrete commitments</p>
                <ol className="mt-6 space-y-8">
                  {COMMITMENTS.map((c, i) => (
                    <ScrollReveal as="li" key={c.label} delay={i * 80} className="border-l-2 border-accent/40 pl-5">
                      <div className="flex items-baseline gap-3">
                        <span className="font-display text-xl text-accent">
                          {String(i + 1).padStart(2, '0')}
                        </span>
                        <h3 className="font-serif text-lg font-medium text-foreground">
                          {c.label}
                        </h3>
                      </div>
                      <p className="mt-2 text-sm leading-relaxed text-foreground/75">
                        {c.body}
                      </p>
                      <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-foreground/45">
                        Reference: {c.citation}
                      </p>
                    </ScrollReveal>
                  ))}
                </ol>
              </div>
            </aside>
          </div>
        </div>
      </section>
    </>
  );
}
