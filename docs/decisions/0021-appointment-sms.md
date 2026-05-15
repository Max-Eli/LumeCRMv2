# ADR 0021 — Appointment SMS (confirmation + reminder)

## Status

Accepted (2026-05-15).

## Context

Yesterday we wired Twilio for the marketing-campaign path (ADR-implied work in `c156847` / `7e9521c`). That gave us a working SDK + shared toll-free number + status-callback webhook. The user then asked for the obvious next thing every spa CRM ships: **confirm the appointment by SMS the moment it's booked, and remind the customer 24h before**.

Spas live and die by no-show rate. SMS reminders cut no-shows roughly in half versus email-only; this is documented industry-wide. Boulevard, Mindbody, Fresha, Square Appointments — all of them send confirmation + reminder SMS by default.

## Decision

### 1. Separate from the marketing SMS path

Marketing SMS (`apps.marketing.sender._dispatch_one`) uses:
- `Customer.sms_marketing_opt_in` (the promotional channel consent)
- TCPA quiet-hours window (9pm–8am block in recipient's tz)
- Per-send unsubscribe token in the body
- `MarketingSendLog` row per send

Transactional appointment SMS uses **none of those**:
- `Customer.sms_opt_in` is the consent flag (collected at booking — TCPA's TPO exception covers transactional)
- No quiet-hours block: TCPA explicitly exempts appointment reminders (47 CFR 64.1200(a)(3)(iv) the "healthcare exception")
- No unsubscribe token: customers can't opt out of their own appointment confirmations (they cancel the appointment if they don't want it)
- No `MarketingSendLog`: this isn't marketing data; the send is recorded on the `Appointment` row + an `AuditLog` entry

Keeping the paths separate avoids three classes of bugs:

1. **Quiet hours suppressing a booking confirmation.** A customer books at 9:30pm; we should confirm immediately, not silently delay until 8am.
2. **Marketing-suppression killing a transactional message.** A customer who unsubscribed from campaigns still gets their appointment reminders.
3. **Cross-track audit noise.** Operators looking at "send log" for a campaign see only campaign sends; appointment SMS lives on the Appointment row where it belongs.

The two paths share **one thing**: the low-level Twilio API call. Both use the same `TWILIO_*` env vars + the same shared toll-free `TWILIO_FROM_NUMBER`. They differ above that thin shim.

### 2. Module layout

- **`apps.appointments.sms`** — new module owning the transactional SMS surface. Exports:
  - `send_sms(to, body)` — thin Twilio wrapper, returns SID. Returns `''` (and logs) when Twilio isn't configured so dev runs end-to-end without TWILIO_* set.
  - `send_confirmation_sms(appointment)` / `send_reminder_sms(appointment)` — consent-checked, idempotent, audit-logged.
  - `render_confirmation_body(appointment)` / `render_reminder_body(appointment)` — short bodies optimized for one Twilio segment (≤160 GSM-7 chars).
- **`apps.appointments.signals`** — new module hosting the `post_save` handler that fires `send_confirmation_sms` on appointment-create. Wired via `AppConfig.ready()`.
- **`apps.appointments.management.commands.send_appointment_reminders`** — cron-invoked command that finds appointments in the 23-25h window and calls `send_reminder_sms` per row.

### 3. Idempotency

Two new fields on `Appointment`:

- `confirmation_sms_sent_at` (DateTimeField, nullable) + `confirmation_sms_provider_id` (CharField, Twilio Message SID).
- `reminder_sms_sent_at` + `reminder_sms_provider_id`.

Both functions check `*_sent_at IS NULL` before doing anything. The row update happens **after** the successful Twilio call, so a Twilio outage doesn't burn the idempotency slot — a retry next cron run will succeed. The reminder management command's queryset filter (`reminder_sms_sent_at__isnull=True`) is the durable idempotency boundary; the signal handler relies on the row being a brand-new insert (`created=True`).

### 4. Error handling

Twilio errors are caught in the **signal handler** and swallowed. The reasoning:

A confirmation SMS failing because Twilio is having a bad day shouldn't cascade into the appointment booking itself failing — the booking is already committed to the DB by the time the signal fires, and rolling it back over a transient Twilio issue would mean the operator's "Book appointment" action appears to succeed and then disappears. Far worse UX than "SMS didn't go out, operator can resend manually."

The reminder command catches per-row + keeps iterating, so one stuck send doesn't take down a whole nightly batch.

All errors land in `AuditLog` (resource_type=`appointment_sms`, metadata.outcome=`skipped`/`stub_no_provider`/`sent`) so the operator can see what happened.

### 5. Reminder scheduling

For v1 the reminder window is hardcoded at 24h. The management command takes `--window-hours` + `--slop-hours` flags so a follow-up can iterate without code changes; the underlying queryset filter does the same math regardless of window.

The command itself doesn't schedule — it's designed to be invoked by an external scheduler. The expected production setup is an **EventBridge scheduled rule** firing every 30 minutes that does an `ECS RunTask` against the existing `lume-prod-backend` task family with the command override. That's ~30 lines of Terraform; it's the obvious next step but deliberately not in this commit to keep the scope focused.

Until the schedule is wired in prod, the operator (or an ad-hoc cron) can invoke the command manually:

```bash
aws ecs run-task --cluster lume-prod-cluster --task-definition lume-prod-backend \
  --launch-type FARGATE --network-configuration ... \
  --overrides '{"containerOverrides":[{"name":"backend","command":["python","manage.py","send_appointment_reminders"]}]}'
```

### 6. Body content

Hardcoded for v1:

```
Confirmation: Hi {first_name}, your appointment at {tenant_name} is confirmed for {Mon, May 15 at 2:00 PM}. Reply STOP to opt out.

Reminder:     Hi {first_name}, reminder: your appointment at {tenant_name} is tomorrow ({Mon, May 15 at 2:00 PM}). Reply STOP to opt out.
```

Both fit comfortably in a single Twilio segment (≤160 GSM-7 chars at typical name/spa lengths). Tenant-customizable templates land in Phase 1H polish ("Notification templates" item that previously blocked on Twilio — now unblocked but not yet built).

`Reply STOP to opt out.` is platform-handled by Twilio (STOP is a magic word; Twilio auto-suppresses the number). We don't need to parse inbound messages to honor it.

## Consequences

### Positive

- Closes 4 of the 5 originally-open items in Phase 1F.
- Same `send_sms()` low-level helper means a future appointment-cancelled SMS, no-show follow-up SMS, etc. plug into the same path with the same idempotency + consent posture.
- 10 new tests cover both flows + the four real failure modes (no consent, no phone, already-sent, Twilio outage).

### Negative

- No retry logic on Twilio failures. If the signal handler catches a `SMSDispatchError`, the confirmation just doesn't go out — there's no follow-up attempt. Acceptable for v1: Twilio's own retries cover transient network issues; persistent failures (bad number, opted-out recipient) shouldn't be retried anyway.
- No DLQ for the reminder command. If the ECS task crashes mid-batch, the rows that already had `reminder_sms_sent_at` stamped don't re-send (correct), but the rows that hadn't been processed yet wait for the next cron run (also correct, given the ±1h slop window). The 30-min cron cadence means the worst-case skip is 30 minutes — acceptable for a reminder that's 24h out anyway.
- Body content is in English, ASCII-only, doesn't internationalize. Spas in non-US-English markets get hardcoded English copy. Not a v1 blocker; tenant-customizable templates will fix this.

### Risks accepted

- **HIPAA**: Twilio BAA covers the surface. Body unavoidably carries PHI (customer first name + appointment time + spa identity). All within the TPO exception per 45 CFR 164.506. We do not include service name in the body — that's where the surface gets closer to clinical-relationship disclosure, and dropping it is cheap insurance.
- **Carrier filtering**: shared-number sender reputation means one tenant's high opt-out rate could affect another tenant's deliverability. Mitigated by the per-message body identifying the spa (so recipients recognize and don't mark as spam), plus the standard SMS deliverability hygiene (STOP-handling, opt-in audit trail, no marketing-promo-language in transactional messages). Per-tenant TFN/10DLC for reputation isolation is platform-admin-phase work.
- **No retry on the SIGNAL path means no SMS for that booking forever** if Twilio fails at exactly that moment. A "Resend confirmation" UI button on the appointment detail page is the obvious user-facing recovery; tracking as a polish follow-up.

## Implementation references

- New module: [apps/appointments/sms.py](../../backend/apps/appointments/sms.py)
- Signal: [apps/appointments/signals.py](../../backend/apps/appointments/signals.py)
- Management command: [apps/appointments/management/commands/send_appointment_reminders.py](../../backend/apps/appointments/management/commands/send_appointment_reminders.py)
- Migration: [apps/appointments/migrations/0006_appointment_confirmation_sms_provider_id_and_more.py](../../backend/apps/appointments/migrations/0006_appointment_confirmation_sms_provider_id_and_more.py)
- Tests: [apps/appointments/tests.py](../../backend/apps/appointments/tests.py) — `AppointmentConfirmationSMSTests` (5 tests) + `AppointmentReminderSMSTests` (5 tests)
- Marketing-side Twilio plumbing (foundation): commits `c156847` + `7e9521c`
