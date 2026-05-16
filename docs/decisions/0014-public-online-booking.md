# ADR 0014 — Public online booking (Phase 1I)

## Status

Accepted (2026-05-04 — Phase 1I sessions 1–3 combined; written
post-ship per the discipline that compliance framing is explicit
per feature)

## Context

Every spa we sell to expects a public booking page — Boulevard,
Zenoti, Mindbody, even Square ship one. It's the dominant
acquisition channel: the spa shares one URL on Instagram bio, email
signature, ads, and the customer self-serves into the calendar. We
need this for the v1 sale.

The booking surface introduces problems the rest of the CRM
hasn't faced:

1. **Anonymous traffic touching tenant data.** No session, no
   user, no tenant cookie — the URL alone has to resolve a tenant,
   show their service catalog, and accept a booking that creates a
   `Customer` row. Requests have to be safely tenant-scoped without
   relying on `TenantMiddleware`'s subdomain or header
   resolution (those work for the staff CRM; cross-origin marketing
   pages don't carry them).
2. **Unauthenticated PHI collection.** Name + email + phone
   captured from a stranger create a HIPAA-relevant record. The
   booking event itself ties identity to a treatment intent (the
   service they picked). HIPAA's audit-trail obligation applies on
   first contact, not first login.
3. **Customer-controlled scheduling math.** Slots come from
   provider working hours minus existing bookings. A naive
   implementation would double-book the same provider at two sites
   (the cross-location guard that ADR 0009 didn't anticipate),
   silently treat schedule "09:00" as 09:00 server-tz UTC (the
   "5 AM EDT" bug we shipped and immediately reverted in session
   2), or expose far-future dates a tenant doesn't want to commit to.
4. **Post-submit access without an account.** Reschedule + cancel
   need to work from the confirmation email. The customer has no
   login. Some token has to act as the bearer credential.
5. **Operator control over the customer-facing surface.** Every spa
   has different opening hours, lead-time culture (a med-spa wants
   2-hour notice; a quick nail salon takes walk-ins), how far out
   they accept, and what they want their cancellation policy to
   say. The operator needs a real settings surface, not hard-coded
   defaults.

### HIPAA + SOC 2 framing

This is the first product surface that **collects PHI from a
stranger**. ADR 0011 covered tokenized fill of a form *that the
operator already issued*; here, the customer creates the record
ex nihilo. Specific obligations the design must address:

- **Audit log on every public action** (HIPAA §164.312(b)).
  No-auth doesn't mean no-trail; the audit must capture
  `user=None` plus IP + user-agent + which tenant + which
  resource. Operators answering a HIPAA request have to be able
  to reconstruct who did what.
- **No PHI in audit metadata** (data-minimization). Email + phone
  go on the `Customer` row, not the audit log. The audit log is
  itself a queryable surface with broader access; PHI-tied
  identifiers must not leak through it.
- **Minimum-necessary disclosure on the public surface** (HIPAA
  §164.502(b)) — public payloads omit anything beyond what the
  customer needs to book. We don't return employee email
  addresses, full last names, payroll status, or any internal
  notes. Provider display names show first + last initial.
- **Tokenized post-submit access** must hold up against
  enumeration + brute-force. 256-bit URL-safe tokens; tokens in
  the URL **path**, not query string (per ADR 0011's reasoning —
  Django doesn't log path segments by name in standard access
  logs).
- **Tenant isolation belt + suspenders** (HIPAA §164.312(a)(1)).
  Every cross-resource lookup re-validates against the URL slug's
  tenant. A booking submission can't reference a service from a
  different tenant — explicit `tenant=` filter on every FK
  resolution in the view.
- **Killswitch with no leak** (operator control + breach
  containment). When `online_booking_enabled=False`, the public
  endpoints return the same 404 they return for nonexistent
  slugs. A paused tenant doesn't show up to outsiders as "exists
  but disabled" — that would leak the customer list.

## Decision

**Build a dedicated `apps.booking` Django app with public
no-auth endpoints under `/api/booking/<slug>/`. Tenants are
resolved from the URL path (not subdomain or header). Every
endpoint records an audit log entry with `user=None`.
Appointments are created with `source='online'` and a 256-bit
`booking_token` that doubles as the manage-page bearer
credential. Schedule "HH:MM" strings interpret in the location's
timezone, not server-tz. The provider-conflict query unions
across all of a provider's locations to prevent
cross-site double-booking. Operators control the surface through
five Tenant fields edited at `/org/online-booking`.**

### Domain shape

```
Tenant (existing)
  ├── online_booking_enabled: bool      # killswitch (404 when off)
  ├── online_booking_lead_minutes: int  # min minutes before bookable
  ├── online_booking_window_days: int   # max days into future bookable
  ├── online_booking_welcome_message: text  # shown above catalog
  └── online_booking_cancellation_policy: text  # shown on details/manage

Appointment (existing)
  ├── source: str = 'online'        # provenance, used for filtering + UX
  └── booking_token: str = secrets.token_urlsafe(32)  # 256-bit; manage URL
```

No new models. The booking app's value is in the surface
(views, serializers, the availability calculator) and the
tenant-settings extensions, not new state.

### Why no models

Bookings are appointments. Customers are customers. Reusing the
existing tables means the staff calendar shows online bookings
alongside staff-created ones with one query (`?source=online`
filters when needed). Auto-creating an `Invoice` and auto-
assigning `FormTemplate`s on submit just works because the
existing post-save signals already handle that for any appointment
regardless of source.

### Path-based tenant resolution

`TenantMiddleware` resolves tenants from subdomain (production)
or `X-Tenant-Slug` header (dev). Both fail for the public booking
page in two real scenarios:

- A tenant shares `https://acmespa.xn--lumcrm-5ua.com/book/acmespa` —
  subdomain works, but a customer who lands on the marketing site
  at `https://promo.spa.com` and clicks "Book" doesn't carry the
  subdomain.
- A tenant embeds the booking link in their own
  `https://acmespa.com/book` — no subdomain at all.

Putting the slug in the URL path works in every scenario, is
shareable, and survives copy-paste through SMS / email / IG bio.
The booking views call `get_object_or_404(Tenant, slug=slug,
status=ACTIVE, online_booking_enabled=True)` directly. The
middleware's request.tenant is ignored on this surface.

### Tokenized manage flow

Same pattern as ADR 0011's form-fill tokens:

- `secrets.token_urlsafe(32)` (~256 bits of entropy).
- Token in URL **path** (`/book/manage/<token>/`), not query
  string. Django's default access log records paths but truncates
  query strings differently at various layers.
- No expiry today (a customer might reschedule months out;
  expiring would break that). Status flips replace expiry —
  a CANCELLED appointment renders "this booking was cancelled" on
  the manage page rather than the reschedule UI.
- Single-token-per-appointment. We don't rotate. Re-issuing the
  link would require a notification + a stale-link UX problem we
  don't need yet.

### Cross-location double-booking guard

ADR 0009 introduced multi-location with `MembershipLocation`
joining a `TenantMembership` to one or more `Location`s. A
provider can work at site A and site B; their schedule is
per-location.

The first availability calculator filtered existing appointments
by `location=location` — meaning an existing 10am appt at site A
didn't block the 10am slot at site B. One human, two places.
Caught immediately on smoke test (a provider was offerable
simultaneously at both sites).

Fix: the existing-appointments query unions across **all
locations the provider is assigned to**. The schedule still scopes
per-location (the provider may not be on shift at site B at all),
but conflict detection treats the provider as one resource.

```python
existing = Appointment.objects.filter(
    provider=provider,                 # NOT location=location
    status__in=OCCUPYING_STATUSES,
    start_time__lt=day_end,
    end_time__gt=day_start,
)
```

`status__in` excludes CANCELLED so cancelled bookings free their
slot at every site, not just the one that took them.

### Schedule semantics: location timezone

Schedule entries store `{"start": "09:00", "end": "17:00"}` —
strings are wall-clock times at the location. ADR 0010
established this; the v1 calculator violated it.

The bug:

```python
def _combine(date, hh_mm):
    naive = datetime.combine(date, time(h, m))
    return timezone.make_aware(naive)  # uses SERVER tz (UTC)
```

`make_aware` defaults to `USE_TZ=True` server tz, which is UTC.
"09:00" becomes 09:00 UTC = **5:00 AM EDT**. Bookings landed
before the staff calendar's 8 AM day-window and operators
couldn't see their own bookings. The customer-facing slot picker
also offered slots that the spa wasn't actually open for.

Fix: every HH:MM resolution goes through
`_combine(on_date, hh_mm, location.timezone)`:

```python
def _combine(on_date, hh_mm, tz):
    h, m = map(int, hh_mm.split(':'))
    return datetime(on_date.year, on_date.month, on_date.day,
                    h, m, tzinfo=tz)
```

The day-window for the appointments query is also constructed in
the location's tz (`datetime.combine(on_date, time.min, tzinfo=tz)`)
so the existing-appointments filter covers the right UTC range
when the server is in NY but the location is in LA.

### Show all candidate slots, not just available ones

Initial design: filter conflicting slots out of the response.
Customer sees `9:00, 9:15, 9:30, [GAP], 11:00…` with no context.

Better UX: return every working-hour slot with `available:
true|false`. The customer sees `9:00, 9:15, 9:30 (taken), 9:45
(taken), 10:00 (taken), 10:30…` — the gap is explained.
Match Boulevard / Zenoti convention.

Implementation: opt-in via `?include_unavailable=true` on the
slots endpoint. Default behavior (filter only-available)
preserved for backward-compat with anyone integrating
programmatically. The frontend always opts in.

Submit-time re-validation continues to use the default (filtered)
mode, so a stale UI submitting an `available: false` start_time
still loses cleanly with 409.

### Operator settings (5 fields on Tenant)

On `Tenant` rather than a separate `OnlineBookingSettings` model
because:

1. They're account-level (not per-location). Putting them on
   `Tenant` puts them next to the existing branding fields
   (`primary_color`, `logo_url`) that they conceptually belong
   with.
2. There are five of them. A separate model adds an extra query +
   a 1:1 relationship to manage with no benefit at this size.
3. The existing `TenantSettingsSerializer` + `/api/tenant/`
   endpoint exposes them with one diff each.

If the surface grows substantially (per-day overrides, blackout
dates, holiday hours), an `OnlineBookingSettings` model becomes
worth it. Today, the five booleans + ints + texts are fine on
Tenant.

The frontend settings page at `/org/online-booking` reads + writes
the same Tenant endpoint. Owner-only, gated by
`MANAGE_TENANT_SETTINGS`.

### Killswitch returns 404, not 503

`online_booking_enabled=False` causes `_resolve_active_tenant` to
404. We considered 503 ("service unavailable") to signal "exists
but paused" — but that leaks tenant existence. A stranger
probing slug guesses can distinguish "real spa, currently paused"
from "no such spa." 404 for both posts a unified front: the URL
either resolves or it doesn't. Operators don't lose anything;
their existing bookings are unaffected (manage links keep
working — they go through a different resolver that doesn't
gate on `online_booking_enabled`).

## Consequences

### What's covered today

- **Tenant resolution from URL slug**, not middleware. Robust
  across subdomain / cross-origin / embedded scenarios.
- **Audit log on every public endpoint** with `user=None`,
  `tenant=<resolved>`, IP + user-agent in metadata. Booking
  submit additionally records the customer_id (created or
  matched) but not their email/phone. Email-send audit captures
  recipient domain only (per ADR 0012).
- **256-bit booking tokens** for the manage flow.
- **Location-aware tz semantics** in the availability calculator.
  Dedicated regression test.
- **Cross-location double-booking guard.** Dedicated regression
  test.
- **Operator-controlled killswitch + lead time + window + welcome
  message + cancellation policy.** All five round-trip through
  the settings endpoint with backend validation (lead time
  capped at 7 days, window at 1–365 days).
- **Public payloads minimum-necessary.** First-name + last-
  initial for providers. No employee email, no payroll, no
  internal notes. Customers see the cancellation policy on
  details + manage pages so they can't claim later "I never
  saw it."
- **Race-safe submit.** Slot re-validation inside the
  transaction; 409 on stale UI; existing appointment unique
  constraints catch the rest.
- **Confirmation email** (HTML + text, brand-colored, manage
  link inline). Best-effort send; never fails the booking.

### What's deferred (Phase 0c production lift)

- **IP-based rate limiting** on the public POST `/book/`
  endpoint. The `PublicBookingPermission` class has the hook
  ready (it exists rather than using `AllowAny` directly so we
  can wire DRF's throttle classes in one place).
- **Captcha / abuse detection.** v1 ships without; the audit
  trail + the manual-review tool panel give operators visibility
  to spot patterns. Real captcha when load shows up.
- **Per-tenant from-domain** for confirmation email (BAA path
  via SES). Today everything sends from the central from-address;
  in production each tenant gets DKIM/SPF/DMARC verification
  per ADR 0012.
- **Self-serve reschedule** via the manage page. v1 has cancel
  only; reschedule = customer cancels and re-books. The
  reschedule UI needs a fresh availability fetch + conflict
  re-check; deliberately deferred.
- **Returning-customer verification code.** Today every email +
  phone combo silently creates or matches; a returning customer
  isn't asked to verify. Polish item: SMS code for matched
  customers before showing them anything stored on file.
- **Per-day blackout dates** (closed for inventory day, holiday).
  `weekly_hours` is purely recurring today.

### What's permanently out of scope

- **Customer accounts.** Public booking is intentionally
  account-less — that's the entire pitch versus competitors that
  force signup. The manage token is the only durable identifier
  the customer sees.
- **Payment-on-booking.** Phase 2A POS will land payments; in v1
  the booking commits a quoted price + creates an open invoice
  that the spa collects at the appointment. No deposits.

## See also

- [ADR 0001 — Multi-tenancy strategy](0001-multi-tenancy-strategy.md)
  for `TenantedModel` + `for_current_tenant()`. The booking
  views deliberately bypass `TenantMiddleware` for tenant
  resolution but every persisted row still inherits tenant
  scoping.
- [ADR 0004 — Audit logging](0004-audit-logging.md) for the
  shape of `AuditLog` entries. Every public booking action
  writes one with `user=None`.
- [ADR 0009 — Multi-location architecture](0009-multi-location-architecture.md)
  for `Location` + `MembershipLocation`. The cross-site
  double-booking guard layers on top of that model.
- [ADR 0010 — Per-provider scheduling](0010-per-provider-scheduling.md)
  for the `ProviderSchedule` model the calculator consumes.
  This ADR fixes the location-tz bug that violated 0010's
  intent.
- [ADR 0011 — Form submissions and tokenized fill](0011-form-submissions-and-tokenized-fill.md)
  for the tokenized-no-auth pattern. The booking
  manage flow follows the same playbook (256-bit, URL-path,
  audit-on-every-touch).
- [ADR 0012 — Email infrastructure](0012-email-infrastructure-and-signed-form-copy.md)
  for the email-send framing. Confirmation emails follow the same
  domain-only audit-logging discipline.
