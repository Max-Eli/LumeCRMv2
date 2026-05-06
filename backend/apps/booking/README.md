# apps.booking

Public-facing online booking surface — no auth required. Customers
land on `/book/<tenant-slug>`, browse the spa's services, see
real-time availability, pick a slot, fill in name/email/phone,
and submit a booking. The submit creates an `Appointment`
(`source='online'`) plus a `Customer` row (matched by phone+email
or freshly created) and emails a confirmation with a tokenized
manage link.

This is the first surface that **collects PHI from a stranger** —
identity tied to a treatment intent. The HIPAA + SOC 2 framing
is explicit throughout.

## What's in here

- **[apps.py](apps.py)** — `BookingConfig`. No models of its own;
  the app's value is in views + the availability calculator.
- **[availability.py](availability.py)** — `compute_provider_slots()`
  + `compute_any_provider_slots()` and the `Slot` dataclass. Walks
  `ProviderSchedule.weekly_hours`, generates 15-min increments,
  drops slots that conflict with existing appointments OR sit
  inside the lead-time buffer. The load-bearing **timezone
  discipline** lives here: schedule "09:00" means 09:00 in the
  *location's* timezone, NOT server-tz UTC. Cross-location
  double-booking guard: existing-appointments query unions across
  every location the provider is assigned to.
- **[services.py](services.py)** — `submit_booking()` (orchestrates
  customer matching + appointment creation in one transaction),
  `find_or_create_customer()` (silent match by phone → email; never
  reveals whether a record existed), `generate_booking_token()`
  (256-bit URL-safe), `send_booking_confirmation()` (best-effort
  HTML + text email; never fails the booking).
- **[serializers.py](serializers.py)** — payloads for every public
  endpoint. `TenantInfoSerializer` (branding + locations + welcome
  + policy), `BookableServiceSerializer` (no internal fields like
  buffer_minutes), `EligibleProviderSerializer` (first + last
  initial; no email), `AvailableSlotSerializer` (with `available`
  flag), `SubmitBookingInputSerializer` (validates the POST body),
  `BookingConfirmationSerializer` + `ManageBookingSerializer`
  (post-submit + manage views; embed tenant branding so manage page
  themes itself without a second fetch).
- **[permissions.py](permissions.py)** — `PublicBookingPermission`
  (allow-any with a hook for future IP-based rate limiting).
  Centralized so when rate limiting lands, every booking endpoint
  inherits it from one place.
- **[views.py](views.py)** — seven endpoints (info / services /
  providers / slots / book / manage / cancel) all using
  `PublicBookingViewMixin` to disable session auth + CSRF (no
  session to ride; the booking_token is the boundary on manage).
- **[urls.py](urls.py)** — mounted under `/api/booking/`.
- **[templates/booking/email/](templates/booking/email/)** — HTML +
  plain-text confirmation email templates. The HTML uses the
  tenant's `primary_color` for the manage button background.
- **[tests.py](tests.py)** — 41 tests covering tenant scoping,
  cross-tenant isolation, eligibility filtering (job-title +
  location + bookable + active), location-tz schedule semantics
  (regression for the "5 AM EDT" bug), cross-location double-
  booking guard, slot conflict detection, lead-time + window
  caps, killswitch returning 404, customer matching rules,
  confirmation email shape (recipient + body), audit-domain-only
  logging, manage-by-token GET + cancel, double-booking 409, and
  `include_unavailable=true` returning Taken slots correctly.

See:

- [ADR 0014 — Public online booking](../../../docs/decisions/0014-public-online-booking.md)
  for the design (no-auth tenant resolution, tokenized manage,
  cross-location double-booking guard, location-tz schedule
  semantics, killswitch returning 404 with no leak).
- [ADR 0011 — Form submissions and tokenized fill](../../../docs/decisions/0011-form-submissions-and-tokenized-fill.md)
  for the tokenized-no-auth pattern this app reuses on the manage
  flow.
- [ADR 0012 — Email infrastructure](../../../docs/decisions/0012-email-infrastructure-and-signed-form-copy.md)
  for the confirmation-email send pattern (BAA path via SES,
  domain-only audit logging).

## Mental model

```
PUBLIC SURFACE (no auth)
  GET   /api/booking/<slug>/info/                   # branding + locations
  GET   /api/booking/<slug>/services/               # bookable services
  GET   /api/booking/<slug>/providers/              # eligible at a location
  GET   /api/booking/<slug>/slots/                  # availability
  POST  /api/booking/<slug>/book/                   # submit a booking
  GET   /api/booking/manage/<token>/                # lookup by token
  POST  /api/booking/manage/<token>/cancel/         # customer cancel

OPERATOR SETTINGS (owner-only, gated by MANAGE_TENANT_SETTINGS)
  GET/PATCH /api/tenant/                            # five new fields:
                                                    #   online_booking_enabled
                                                    #   online_booking_lead_minutes
                                                    #   online_booking_window_days
                                                    #   online_booking_welcome_message
                                                    #   online_booking_cancellation_policy

DATA CREATED ON SUBMIT
  Customer       (or matched silently — no "welcome back" leak)
  Appointment    (source='online', booking_token=<256-bit>)
   ↓ post_save signals
  Invoice        (open, awaiting collection at the appointment)
  FormSubmission(s) (per ADR 0011 service-mapping rules)
  AuditLog       (resource_type='appointment', user=None,
                  metadata={event:'online_booking_submitted', ...})
```

## HIPAA + SOC 2 considerations

This app collects PHI **from a stranger** — name, email, phone
tied to a treatment intent. The audit-trail and minimum-necessary
disclosures apply on first contact, not first login.

### What's covered today

- **Audit log on every public action.** Every endpoint records a
  `record(action=..., user=None, tenant=resolved_tenant,
  request=request)` entry. IP + user-agent come from the request
  (truncated to 500 chars, captured per `apps.audit.services`).
  Submit-time + manage-time audit log additionally captures
  resource IDs (appointment, customer) so a HIPAA breach
  reconstruction can trace any record back to the public-flow
  event that created or modified it. HIPAA §164.312(b).
- **No PHI in audit metadata.** Email + phone go on the `Customer`
  row, not the audit log. The confirmation-email audit captures
  `recipient_email_domain` only (`example.com`, not the full
  address) — same posture as `email_signed_copy` per ADR 0012.
  Audit-log surfaces have broader query access than the row-level
  PHI tables; PHI must not leak through.
- **Tenant isolation, belt + suspenders.** The view resolves the
  tenant from the URL slug, then re-validates every FK
  (`Service`, `Location`, provider `TenantMembership`) against
  that tenant. A booking submission referencing a service from
  a different tenant returns 400 with a generic message — we
  don't disclose whether the cross-tenant resource exists. HIPAA
  §164.312(a)(1).
- **Minimum-necessary public payloads.** No employee email, no
  payroll, no internal notes, no full last names (first + last
  initial only). The customer sees the cancellation policy on
  the details + manage pages so they can't claim later that
  they didn't see it. HIPAA §164.502(b).
- **Killswitch returns 404, not 503.** When
  `online_booking_enabled=False`, public endpoints return the
  same 404 nonexistent slugs return. A paused tenant doesn't show
  up to outsiders as "exists but disabled" — that would leak the
  customer list. Existing bookings (with their manage tokens)
  keep working through the manage endpoint, which uses a
  different resolver that doesn't gate on the killswitch.
- **256-bit manage tokens.** `secrets.token_urlsafe(32)`, stored
  in `Appointment.booking_token`. Token in URL **path** —
  `/book/manage/<token>/` — not query string, not fragment.
  Django's default access logs handle path segments better and
  the path placement matches the ADR 0011 form-fill pattern. No
  expiry today (a customer might reschedule months out); status
  flips replace expiry semantically.
- **Race-safe submit.** Slot re-validation runs inside the
  POST handler against `compute_provider_slots(...,
  include_unavailable=False)` — meaning a stale UI submitting an
  unavailable slot loses cleanly with 409. The unique-constraint
  chain on `Appointment` + the post-save signal cascade catch
  any race that slips past the re-validation.
- **Provider eligibility enforced at every level.** The slots
  endpoint, providers endpoint, and submit-booking endpoint
  each call `_eligible_providers(tenant, service, location)`
  which checks bookable + active + location-assigned + job-title-
  in-category-eligibility. Defense in depth: the frontend filters
  the choices, but the backend wouldn't accept a request that
  bypassed it.
- **No "welcome back" leak.** `find_or_create_customer()` matches
  silently on email+phone → phone alone → email alone. A
  returning customer's record is reused; a new customer's record
  is created. The response is identical either way. Privacy
  posture: the public flow doesn't reveal whether someone is on
  file at this spa.
- **Schedule resolves in the location's timezone**, not server-tz.
  Regression test in place. The "5 AM EDT" bug shipped briefly
  in session 1 and was caught immediately when bookings landed
  before the staff calendar's day-window. ADR 0014 covers the
  reasoning.
- **Cross-location double-booking guard.** A provider who works
  at site A and site B can't be booked at both at 10 AM. The
  conflict query unions the provider's existing appointments
  across all their locations, with `status__in` excluding
  CANCELLED. Regression test in place.
- **Email send is best-effort.** A failed SES / SMTP send doesn't
  fail the booking — the customer still gets the confirmation
  page with the manage link in the JSON body. Failures log via
  `logger.exception` for operator visibility; the appointment is
  already saved.

### What's deferred (Phase 0c production lift)

- **IP-based rate limiting** on POST `/book/`. The
  `PublicBookingPermission` class has the hook ready; v1 ships
  without throttling because the manual-review tool panel on the
  calendar lets operators spot patterns. Real DRF throttle
  classes when public load shows up.
- **Captcha / abuse detection.** Same reasoning as rate limiting.
- **Per-tenant from-domain** for the confirmation email
  (DKIM/SPF/DMARC). Today everything sends from the central
  `DEFAULT_FROM_EMAIL`; in production each tenant verifies its
  own domain via SES per ADR 0012.
- **Returning-customer verification.** Today email+phone combos
  silently match. Polish: SMS code for matched customers before
  showing them anything stored on file.
- **Self-serve reschedule** via the manage page. v1 has cancel
  only; reschedule = cancel and re-book. The full reschedule UI
  needs another availability fetch + conflict re-check;
  deliberately deferred.
- **Per-day blackout dates** (closed for inventory day,
  holidays). `weekly_hours` is purely recurring today.
- **Token expiry** — v1 tokens live forever (until a status flip).
  Polish: invalidate tokens for appointments more than N days
  past their start_time.

### What's deferred (broader CRM lift)

- **Encryption at rest.** PHI on `Customer` rows relies on
  Postgres TDE in production (Phase 0c).
- **Audit-log immutability** via DB triggers — already in §4.5
  polish backlog from ADR 0004.

## Building on this

When adding new public-surface fields:

1. Update the relevant serializer; double-check it's
   minimum-necessary (don't accidentally expose internal flags).
2. Add an audit log entry if the new field carries PHI or
   identity context.
3. Re-validate against the URL slug's tenant in the view (don't
   trust client input).
4. Add a frontend test for the field's presence — the
   public-surface API contract is the customer-facing surface,
   so changes need explicit tests.

When extending the operator settings (new `online_booking_*`
field on `Tenant`):

1. Add the field with a sensible default in a new migration.
2. Expose it via `TenantSettingsSerializer` (existing endpoint).
3. If it gates the public surface, wire it into
   `_resolve_active_tenant` or the relevant view branch.
4. Add it to the `/org/online-booking` settings page with
   inline help text.
5. Surface it on the public payload only if the customer needs
   to see it.
