import { PageHero } from '@/components/page-hero';
import { ProductFrame } from '@/components/product-frame';
import { AuditLogMock } from '@/components/product-mocks';
import { ScrollReveal } from '@/components/scroll-reveal';

import type { Metadata } from 'next';

const COMPLIANCE_MARKERS = [
  { label: 'HIPAA', body: 'Compliant by architecture.' },
  { label: 'BAA', body: 'Signed with every customer.' },
  { label: 'Audit logging', body: 'Append-only on every PHI read.' },
  { label: 'AWS', body: 'BAA-eligible infrastructure.' },
];

export const metadata: Metadata = {
  title: 'Security & HIPAA',
  description:
    'Tenant isolation at the database. Role-based permissions resolved per request. Append-only audit logging on every PHI access. AWS infrastructure under a signed BAA.',
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
        standfirst="HIPAA compliance was a day-one design constraint, not an afterthought. Tenant data is isolated at the database. Permissions resolve per request. Every PHI read writes an audit entry. AWS sits under a signed BAA."
      />

      {/* Compliance marker strip — four scannable labels for the
          quick-scan reader. Type-driven, no icons. */}
      <section className="border-b border-border bg-foreground/[0.02]">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-14 lg:py-16">
          <ul className="grid gap-y-8 gap-x-12 sm:grid-cols-2 lg:grid-cols-4">
            {COMPLIANCE_MARKERS.map((marker) => (
              <li key={marker.label} className="border-l-2 border-accent/50 pl-5">
                <p className="font-display text-2xl text-foreground sm:text-3xl">
                  {marker.label}
                </p>
                <p className="mt-2 text-sm text-foreground/70">{marker.body}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <div className="grid gap-16 lg:grid-cols-12">
            {/* Long-form essay */}
            <article className="lg:col-span-7">
              <ScrollReveal>
                <p className="text-lg leading-[1.85] text-foreground/85">
                  Most CRM platforms treat HIPAA as a tier upgrade. A
                  "secure" plan at 2x the regular price, with a few
                  extra features bolted on. That model creates a
                  two-track product, where the compliance posture is a
                  marketing line, not an architectural one.
                </p>
                <p className="mt-4 text-lg leading-[1.85] text-foreground/85">
                  Lumè doesn't have a "secure tier." Every customer is
                  on the HIPAA-compliant architecture because there's
                  only one architecture. Tenant isolation, role-based
                  permissions, audit logging, and PHI containment are
                  foundational. They're built into the models and the
                  middleware, not patched on as an upsell.
                </p>
              </ScrollReveal>

              <ScrollReveal delay={140}>
                <h2 className="mt-12 eyebrow text-foreground/60">
                  What "HIPAA-compliant" means here
                </h2>
                <p className="mt-4 text-base leading-[1.85] text-foreground/85">
                  Lumè is built on a defense-in-depth architecture:
                  least privilege, traceability, change management,
                  separation of duties. Production runs on AWS services
                  covered by a Business Associate Agreement. Postgres
                  is KMS-encrypted at rest. Email goes through SES with
                  the right SPF, DKIM, and DMARC posture. Backups are
                  encrypted, key rotation is automated, access is
                  logged.
                </p>
                <p className="mt-4 text-base leading-[1.85] text-foreground/85">
                  The product also makes the hard choice consistently.
                  Email containing PHI (a signed-consent copy, for
                  example) sends only when an operator initiates it,
                  because automated PHI delivery would require
                  per-customer authorization most spas don't capture
                  today. CSV exports of per-customer data fire a
                  confirmation gate before the download. Every
                  confirmation is logged.
                </p>
              </ScrollReveal>

              <ScrollReveal delay={280}>
                <h2 className="mt-12 eyebrow text-foreground/60">
                  Production posture
                </h2>
                <p className="mt-4 text-base leading-[1.85] text-foreground/85">
                  Production runs on AWS under a signed BAA. Postgres
                  encrypted at rest with KMS. Backups encrypted, key
                  rotation automated. SES handles email with DKIM, SPF,
                  and DMARC configured. Audit log tables are append-only
                  at the database trigger level. UPDATE and DELETE
                  statements are rejected.
                </p>
                <p className="mt-4 text-base leading-[1.85] text-foreground/85">
                  If your compliance team needs documentation —
                  architecture diagrams, control mappings, or answers
                  to a vendor questionnaire — we respond directly.
                  Contact us at{' '}
                  <a
                    href="mailto:security@xn--lumcrm-5ua.com"
                    className="text-accent underline underline-offset-2 hover:text-foreground"
                  >
                    security@lumècrm.com
                  </a>
                  .
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

      {/* Visual proof: the audit log surface, rendered. This is the
          one HIPAA control most operators want to see "live" before
          they trust the architecture claim. */}
      <section className="border-t border-border bg-foreground/[0.02]">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <div className="grid items-center gap-12 lg:grid-cols-12 lg:gap-16">
            <ScrollReveal className="lg:col-span-5">
              <p className="eyebrow text-foreground/60">The audit trail, in practice</p>
              <h2 className="mt-4 font-serif text-3xl font-medium text-foreground sm:text-4xl">
                Every PHI read, every state change, recorded.
              </h2>
              <p className="mt-5 text-base leading-relaxed text-foreground/75 sm:text-lg">
                The audit log is append-only at the database trigger
                level — UPDATE and DELETE statements on the audit
                table are rejected. Owners and managers can query by
                date, user, or resource. The log includes IP and
                user-agent on every entry.
              </p>
              <p className="mt-3 text-sm leading-relaxed text-foreground/65">
                Entries shown right are illustrative. The real
                surface is identical.
              </p>
            </ScrollReveal>
            <ScrollReveal delay={140} className="lg:col-span-7 lg:col-start-6">
              <ProductFrame url="/audit?range=last_60_min">
                <AuditLogMock />
              </ProductFrame>
            </ScrollReveal>
          </div>
        </div>
      </section>
    </>
  );
}
