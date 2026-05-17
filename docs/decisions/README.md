# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records for Lumè CRM. ADRs capture significant architectural choices in a lightweight, durable format so future readers (including future-us) understand the **why** behind the code.

## Format

We use the Michael Nygard ADR format:

- **Status** — one of Proposed, Accepted, Deprecated, Superseded.
- **Context** — what problem and constraints existed at decision time.
- **Decision** — what was decided.
- **Consequences** — pros, cons, trade-offs, follow-on impacts.

## When to write an ADR

Write one when:

- You make a non-trivial architectural choice (data model, auth strategy, dependency selection, framework version).
- You'd want to know *why* if you came back to the code in 6 months.
- You'd want a teammate to understand the trade-offs without you having to re-explain them.

**Write the ADR in the same PR as the code change**, not retroactively. The whole point is to capture reasoning while it's fresh.

## When NOT to write an ADR

- Routine bug fixes.
- Trivial refactors.
- "We picked the obvious thing."
- Decisions captured fully in PR descriptions or commit messages.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-multi-tenancy-strategy.md) | Multi-tenancy strategy | Accepted |
| [0002](0002-authentication-strategy.md) | Authentication strategy | Accepted (interim) |
| [0003](0003-permission-model.md) | Permission model | Accepted |
| [0004](0004-audit-logging.md) | Audit logging | Accepted |
| [0005](0005-frontend-stack.md) | Frontend stack | Accepted |
| [0006](0006-visual-design-system.md) | Visual design system | Accepted |
| [0007](0007-invoicing-and-completion-gate.md) | Invoicing and the appointment-completion gate | Accepted |
| [0008](0008-forms-and-e-signature.md) | Forms and e-signature | Accepted |
| [0009](0009-multi-location-architecture.md) | Multi-location architecture | Accepted |
| [0010](0010-per-provider-scheduling.md) | Per-provider scheduling | Accepted |
| [0011](0011-form-submissions-and-tokenized-fill.md) | Form submissions and tokenized fill | Accepted |
| [0012](0012-email-infrastructure-and-signed-form-copy.md) | Email infrastructure and signed-form copy | Accepted |
| [0013](0013-reports-module.md) | Reports module | Accepted |
| [0014](0014-public-online-booking.md) | Public online booking | Accepted |
| [0015](0015-clinical-chart-notes.md) | Clinical chart notes | Accepted |
| [0016](0016-email-and-sms-marketing.md) | Email + SMS marketing | Accepted |
| [0017](0017-phi-redaction.md) | PHI redaction in logs and audit metadata | Accepted |
| [0018](0018-invoice-pdf-rendering.md) | Invoice PDF rendering | Accepted |
| [0019](0019-staff-invitations.md) | Staff invitations | Accepted |
| [0020](0020-form-submission-pdfs.md) | Form submission PDFs | Accepted |
| [0021](0021-appointment-sms.md) | Appointment SMS confirmations + reminders | Accepted |
| [0022](0022-customer-messaging-inbox.md) | Customer messaging inbox | Accepted |
| [0023](0023-messaging-polish-templates-review.md) | Messaging polish — templates + review automation | Accepted |
| [0024](0024-customer-portal-mvp.md) | Customer portal MVP | Accepted |
| [0025](0025-emr-v2-protocols-and-treatment-records.md) | EMR v2 — protocols + treatment record templates | Accepted |
| [0026](0026-tenant-isolation-enforcement.md) | Tenant isolation enforcement | Accepted |
| [0027](0027-meta-instagram-dm-integration.md) | Meta Instagram DM integration | Accepted |
| [0028](0028-ecs-deploy-contract.md) | ECS deploy contract (Terraform vs CI) | Accepted |
| [0029](0029-ses-bounce-complaint-suppression.md) | SES bounce + complaint suppression pipeline | Accepted |
| [0030](0030-zenoti-customer-import.md) | Zenoti customer import | Accepted |

## Numbering

ADRs are numbered sequentially starting at 0001. Don't reuse numbers, don't skip numbers, don't renumber. If an ADR is superseded by a later one, update its status to "Superseded by ADR NNNN" and leave the original in place — the history is part of the value.
