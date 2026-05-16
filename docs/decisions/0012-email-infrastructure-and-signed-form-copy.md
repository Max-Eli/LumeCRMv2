# ADR 0012 — Email infrastructure + operator-initiated signed-form copy

## Status

Accepted (2026-05-03 — Forms Sessions 2/3 follow-up; written at design time per the discipline)

## Context

A real workflow gap surfaced after Forms Sessions 2/3 shipped: the
spa needs to send signed copies of consent forms to clients who ask.
This is a HIPAA-regulated communication (the email body or
attachment IS PHI), and there's no existing email-sending
infrastructure in the codebase to lean on.

Two distinct concerns mixed together if we're not careful:

1. **Email infrastructure** — Django email backend, provider, BAA,
   how dev vs prod differ, where templates live. This is a
   foundational piece that future features (SMS reminders Phase 1F,
   appointment confirmations, password reset, online-booking
   confirmations Phase 1I, marketing campaigns Phase 3B) will all
   sit on top of.
2. **Operator-initiated send-a-copy flow** — the immediate UX:
   "client asked for a copy of their consent." Operator clicks a
   button, email goes out. Different concern than automated reminder
   emails or signed-on-submit confirmations.

Both ship in this session, but the design needs to keep them
separable so the infrastructure doesn't get coupled to one specific
use case.

### HIPAA + SOC 2 framing

Email containing PHI — and a signed informed-consent absolutely
qualifies — has specific requirements:

- **Encryption in transit**: TLS between our server and the email
  provider, then between provider and the recipient's mail server.
  AWS SES uses STARTTLS opportunistically; recipient's MX is the
  weak link (some MTAs still negotiate TLS but accept plain). HHS
  guidance: TLS in transit is acceptable when both sides support it;
  customer assumes the risk of email-as-channel for PHI.
- **BAA with the provider**: AWS SES is BAA-eligible under the AWS
  HIPAA-Eligible Services list (since 2017). Required contractual
  posture before SES touches PHI.
- **Customer authorization**: HIPAA Privacy Rule allows PHI by email
  with the patient's request or authorization (45 CFR 164.524(c)(2),
  HHS guidance Aug 2013). The OPERATOR is responsible for confirming
  the customer asked for the email — we capture this through
  operator-initiated send (the operator clicks a button, the system
  doesn't auto-email).
- **Audit log**: Every PHI-containing email send needs an audit log
  entry naming who triggered it, the recipient, and the resource —
  HIPAA §164.312(b) audit controls. The send action writes
  `AuditLog` with metadata `{customer_id, email_recipient (hashed?
  full?), template_id, status_at_send: 'completed'}`.
- **Minimum-necessary**: The email body shouldn't carry information
  beyond what the customer requested. For a signed consent: the
  template name, signed date, the signed answers. NOT the
  appointment time, NOT other consent statuses, NOT chart history.
- **No PHI in audit metadata**: Same rule as form submissions — we
  log the SEND happened, NOT the contents.

### Industry pattern check

Looked at how Vagaro / Boulevard / Mindbody / Aesthetic Record
handle this:

- All have operator-initiated "email a copy" buttons on signed
  consents.
- None auto-email signed consents to clients on submission (would
  require explicit per-customer email-PHI consent which most spas
  don't bother capturing).
- All include the signed contents in the email body (HTML render),
  some also attach PDF.
- Most use the same provider (SES, SendGrid w/ BAA, Postmark) for
  this + transactional emails (booking confirmations, reminders).

Our shape matches: operator-initiated, HTML body, PDF deferred,
SES path for prod.

## Decision

**Use Django's email framework with a configurable backend (console
in dev, AWS SES in prod via Phase 0c). Send signed-form copies as
operator-initiated POSTs against `/api/form-submissions/{id}/email/`.
The send gates on owner+manager `MANAGE_STAFF`. The email body is
HTML rendering of the signed answers + a link to view the same
content at `/sign/[token]`. Audit-logged with no PHI in the
metadata. PDF attachment, automatic-on-signing, and SMS deferred to
their own follow-ups.**

### Infrastructure shape

| Piece | Local dev | Production (Phase 0c) |
|---|---|---|
| `EMAIL_BACKEND` | `django.core.mail.backends.console.EmailBackend` — prints emails to runserver console | `django_ses.SESBackend` — sends via AWS SES |
| `DEFAULT_FROM_EMAIL` | `noreply@dev.lumecrm.local` | Per-tenant from address (e.g. `noreply@acmespa.lume-crm.com` — Phase 0c subdomain wiring) |
| Template loader | Django default (`apps/forms/templates/...`) | Same |
| BAA | None needed (no real PHI flowing) | AWS SES under AWS BAA — must be in a BAA-signed AWS account |
| Bounce / complaint handling | None | SES SNS topics → Django webhook (Phase 0c) |

Dev-mode console backend is the explicit "you can verify what got
sent without provider plumbing" choice. Operator runs `runserver`,
clicks "Email signed copy," sees the rendered HTML in their
terminal. No accidental real sends from dev.

### Email shape

`POST /api/form-submissions/{id}/email/` triggers:

1. Look up the submission (tenant-scoped, must be `completed` —
   pending and voided rejected with 400).
2. Customer must have an email on file — reject 400 if blank.
3. Render the HTML template `forms/email/signed_copy.html` with
   context `{submission, customer, tenant, fill_url}`.
4. Render the plain-text fallback `forms/email/signed_copy.txt`
   (required for accessibility / non-HTML clients).
5. Send via the configured backend.
6. Write `AuditLog` entry: `action=UPDATE`, `resource_type='form_submission'`,
   metadata `{event: 'emailed_to_customer', recipient_email_domain,
   template_id, sent_by: <user.id>}`. **Recipient EMAIL ITSELF is
   stored in the body of the email, not the audit metadata** — the
   audit log shouldn't accumulate raw email addresses (which are
   themselves PHI when paired with treatment context). Domain only
   for the trail.

### Why operator-initiated, not auto-on-signing

- Auto-emailing PHI requires per-customer authorization. Most spas
  don't capture this granularly; building it adds an intake-form
  field + opt-in tracking + an unsubscribe surface for one feature.
- The "customer asked for a copy" workflow has a natural human
  consent step: the operator confirms the ask before clicking.
  Easier to defend in a compliance review than "we email everyone
  by default; here's our opt-out."
- Operationally: most clients don't ask for a copy. Sending all
  signed forms by default would be email-noise for the majority.

### Why HTML inline + link, not PDF attachment yet

- PDF generation needs WeasyPrint or a similar server-side render —
  meaningful infrastructure addition with its own footguns (font
  rendering, page breaks, embedded image handling).
- The HTML inline body answers the customer's actual ask: "what did
  I sign?" They can read it without opening attachments.
- The link to `/sign/[token]` lets them get the polished signed
  view if they want it — same URL pattern they've already used.
- PDF attachment lands as a follow-up when WeasyPrint is wired in
  (Phase 0c production, since prod-grade PDF wants a real font path
  + Docker layer).

### Why owner+manager gate

`MANAGE_STAFF` already gates `void` on submissions. Email send is
similarly an operator-action that touches PHI; same role tier
matches expectation. Front desk doesn't bother with consent emails
typically; if there's pressure to widen access, we can add a
narrower `EMAIL_PHI_TO_CUSTOMER` permission later.

### Audit log entry format (precise)

```python
record(
    action=AuditLog.Action.UPDATE,
    resource_type='form_submission',
    resource_id=submission.id,
    request=request,
    metadata={
        'event': 'emailed_to_customer',
        'template_id': submission.form_template_id,
        'template_name': submission.form_template.name,
        'recipient_email_domain': customer_email.split('@')[1].lower()
            if '@' in customer_email else 'unknown',
        # Note: full recipient address is in the EMAIL itself,
        # which is sent + delivered. The audit log keeps the
        # domain only — the SOC 2 trail answers "PHI was sent to
        # an external address" without itself becoming a PHI store.
    },
)
```

## Consequences

### Pros

- **Foundation for everything email-related.** Reminders (1F),
  booking confirmations (1I), password reset (1F polish),
  marketing (3B) all sit on the same `EMAIL_BACKEND` + template
  conventions.
- **Dev experience** — console backend means anyone can develop +
  test email features without provider setup or accidental sends.
- **Operator-controlled HIPAA disclosure** — the "did the customer
  ask for this" moment is a human click, not an automated rule.
- **Audit trail without PHI** — we know an email went out, who
  triggered it, and the recipient's domain. The full content lives
  in the submission row + the email itself, not the log.

### Cons

- **No real email actually goes out in dev** — operator can't
  verify deliverability without prod credentials. Acceptable for
  v1; SES sandbox in staging will close this gap.
- **Can't send PHI without operator action.** Some customers
  expect automatic delivery on signing; we punt with a manual
  step. Polish: per-customer email-PHI consent + auto-on-sign
  toggle.
- **Plain-text fallback is mandatory** — must be maintained
  alongside the HTML template; keeps the email accessibility
  story honest.
- **Bounces / complaints not handled in v1.** A bounced email goes
  silent. SES SNS webhooks land in Phase 0c; until then, "did the
  email actually arrive?" is on the operator to confirm with the
  customer.
- **Per-tenant from-address is Phase 0c.** v1 sends from the
  central `noreply@…` — fine for dev console; in prod this would
  be a deliverability + branding issue if we shipped today.

### Production lift (Phase 0c)

- AWS account confirmed under BAA.
- SES domain verification for `xn--lumcrm-5ua.com` (and per-tenant
  subdomains for branding).
- SES SNS topics for bounce + complaint webhooks → Django endpoint
  that flips a customer flag if they bounce hard.
- DKIM + SPF + DMARC records to satisfy major MTA reputation
  checks.
- Rate limiting at the Django layer to stay inside SES sending
  quotas.
- Per-tenant from-address routing (e.g. `acmespa.lume-crm.com`
  needs to be a verified SES sender).

## References

- [apps.forms README](../../backend/apps/forms/README.md)
- [ADR 0011 — Form submissions + tokenized fill](./0011-form-submissions-and-tokenized-fill.md)
- [ADR 0001 — Multi-tenancy strategy](./0001-multi-tenancy-strategy.md)
- HIPAA Privacy Rule §164.524(c)(2) — Right of access
- HHS guidance, Aug 2013 — "If a patient requests email" (encrypted-
  in-transit + customer assumes risk model)
- HIPAA Security Rule §164.312(b) — Audit controls
- [AWS HIPAA-Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- SOC 2 Trust Services Criteria CC 6.7 — Restriction of system access
- SOC 2 Trust Services Criteria CC 7.2 — System monitoring
