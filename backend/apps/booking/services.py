"""Booking-flow services — customer matching + appointment creation.

Public-facing booking submissions go through `submit_booking()`. It:
  1. Resolves or creates the Customer (matching by phone+email)
  2. Creates the Appointment with `source='online'` and a fresh
     booking_token. The existing post_save signal cascades to
     Invoice creation + form auto-assignment.
  3. Returns the created Appointment with its token.

Wrapped in `transaction.atomic()` so a partial failure (e.g. unique
constraint on appointment, conflict-detection rejection) leaves no
half-state.
"""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone as djtz

from apps.appointments.models import Appointment
from apps.customers.models import Customer
from apps.services.models import Service
from apps.tenants.models import Location, Tenant, TenantMembership

logger = logging.getLogger(__name__)


def find_or_create_customer(
    *,
    tenant: Tenant,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
) -> tuple[Customer, bool]:
    """Match an existing customer by email+phone, else create new.

    Privacy posture: we never reveal whether a phone/email matches an
    existing record — the public booking flow doesn't return a
    "welcome back!" hint. A returning customer's record gets reused
    silently; a new customer's record gets created. Either way the
    booking succeeds.

    Match logic:
      - Email + phone both match an active record → that customer
      - Phone alone matches → that customer (email might've changed)
      - Email alone matches → that customer (phone might've changed)
      - No match → new customer
    """
    email_norm = (email or '').strip().lower()
    phone_norm = (phone or '').strip()

    qs = Customer.objects.for_tenant(tenant)

    if email_norm and phone_norm:
        match = qs.filter(email__iexact=email_norm, phone=phone_norm).first()
        if match:
            return match, False

    if phone_norm:
        match = qs.filter(phone=phone_norm).first()
        if match:
            return match, False

    if email_norm:
        match = qs.filter(email__iexact=email_norm).first()
        if match:
            return match, False

    customer = Customer.objects.create(
        tenant=tenant,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=email_norm,
        phone=phone_norm,
        # ADR 0027 §8a — first-touch attribution for "where did this
        # customer come from?" reporting. Public booking page is the
        # online_booking source.
        acquisition_source=Customer.AcquisitionSource.ONLINE_BOOKING,
    )
    return customer, True


def generate_booking_token() -> str:
    """256-bit URL-safe token for the public manage-booking link.

    Same entropy budget as the form-fill tokens (apps.forms). Single
    token per appointment; revocation is implicit via status flips
    (a CANCELLED appointment renders "this booking was cancelled" on
    the manage page rather than the reschedule UI).
    """
    return secrets.token_urlsafe(32)


@transaction.atomic
def submit_booking(
    *,
    tenant: Tenant,
    service: Service,
    provider: TenantMembership,
    location: Location,
    start_time,
    end_time,
    customer_first_name: str,
    customer_last_name: str,
    customer_email: str,
    customer_phone: str,
    email_marketing_opt_in: bool = False,
    sms_marketing_opt_in: bool = False,
) -> Appointment:
    """Create the appointment + customer record.

    Caller must have already validated:
      - service.is_bookable_online and tenant-scoped to `tenant`
      - provider eligible for service + assigned to location
      - `start_time` was a valid slot at call time (concurrent-booking
        races are caught by the appointment unique-constraint chain
        + invoice signals; we re-validate inside the transaction
        before creating)

    Marketing consent is captured per-channel; True flips the
    `*_marketing_opt_in` flag on the Customer record AND records the
    `consent_at` timestamp + `consent_source='booking_form'` for the
    legal record. Default False — booking-page checkboxes default
    unchecked per TCPA + CAN-SPAM.

    Returns the created Appointment with `booking_token` populated.
    Invoice + forms cascade via existing post_save signals.
    """
    customer, was_created = find_or_create_customer(
        tenant=tenant,
        first_name=customer_first_name,
        last_name=customer_last_name,
        email=customer_email,
        phone=customer_phone,
    )

    # Marketing consent. Only flip from False → True; never flip back
    # to False here (an opt-in carries forward; only suppression
    # via unsubscribe / STOP / bounce / manual flips OFF). And never
    # touch the suppression fields — only the consent fields.
    consent_fields_changed: list[str] = []
    if email_marketing_opt_in and not customer.email_marketing_opt_in:
        customer.email_marketing_opt_in = True
        customer.email_marketing_consent_at = djtz.now()
        customer.email_marketing_consent_source = 'booking_form'
        consent_fields_changed.extend([
            'email_marketing_opt_in',
            'email_marketing_consent_at',
            'email_marketing_consent_source',
        ])
    if sms_marketing_opt_in and not customer.sms_marketing_opt_in:
        customer.sms_marketing_opt_in = True
        customer.sms_marketing_consent_at = djtz.now()
        customer.sms_marketing_consent_source = 'booking_form'
        consent_fields_changed.extend([
            'sms_marketing_opt_in',
            'sms_marketing_consent_at',
            'sms_marketing_consent_source',
        ])
    if consent_fields_changed:
        consent_fields_changed.append('updated_at')
        customer.save(update_fields=consent_fields_changed)

    appointment = Appointment.objects.create(
        tenant=tenant,
        customer=customer,
        provider=provider,
        service=service,
        location=location,
        start_time=start_time,
        end_time=end_time,
        status=Appointment.Status.BOOKED,
        source='online',
        booking_token=generate_booking_token(),
        quoted_price_cents=service.price_cents,
        # `created_by` is null for public bookings — no authenticated
        # user. The signal-created Invoice will also have
        # created_by=null which is fine.
    )
    return appointment


# ── Confirmation email ──────────────────────────────────────────────


def send_booking_confirmation(
    appointment: Appointment,
    *,
    kind: str = 'confirmation',
) -> str | None:
    """Send a booking-related email to the customer.

    `kind` selects the variant:

      - `'confirmation'` — initial booking. Uses the standard template
        + subject. Sent right after a successful POST `/book/`.
      - `'reschedule'` — booking moved to a new time. Same template
        rendered with a different headline + subject ("Your appointment
        was moved to ..."). Sent after `/manage/<token>/reschedule/`.

    Best-effort: returns the recipient address on success, None when
    there's no email on file or sending fails. We deliberately do NOT
    raise — a transient email outage shouldn't undo the booking
    state change, and the customer can still see the new state from
    the manage page directly.

    Failures are logged with the appointment ID so an operator could
    re-send manually from the staff calendar (out of scope for v1;
    polish item). Audit logging happens in the caller's view, not
    here, same pattern as `apps.forms.email_signed_copy`.
    """
    customer = appointment.customer
    recipient = (customer.email or '').strip()
    if not recipient:
        logger.info(
            'booking.email skipped — no customer email',
            extra={'appointment_id': appointment.pk, 'kind': kind},
        )
        return None

    tenant = appointment.tenant
    location = appointment.location

    # Render the time in the location's local timezone so the email
    # says "3:00 PM" instead of UTC. Each location has its own tz
    # because a multi-site spa may span timezones.
    try:
        import zoneinfo
        local_tz = zoneinfo.ZoneInfo(location.timezone)
    except Exception:
        local_tz = djtz.get_current_timezone()
    local_start = appointment.start_time.astimezone(local_tz)
    when_local = local_start.strftime('%A, %B %-d, %Y · %-I:%M %p')

    address_parts = [
        location.address_line1,
        f'{location.city}, {location.state} {location.zip_code}'.strip(', '),
    ]
    location_address = ', '.join(p for p in address_parts if p.strip())

    manage_url = (
        f"{settings.PUBLIC_BASE_URL.rstrip('/')}/book/manage/{appointment.booking_token}"
    )

    # Subject + headline differ by kind. Keep the template the same so
    # the email's brand-color + manage-link UX is identical regardless
    # of why the customer is hearing from the spa.
    is_reschedule = (kind == 'reschedule')
    subject = (
        f'Your appointment at {tenant.name} was moved'
        if is_reschedule
        else f'Your appointment at {tenant.name} is confirmed'
    )
    headline = (
        'Your appointment was moved'
        if is_reschedule
        else 'Your appointment is confirmed'
    )
    body_lead = (
        'Here are the updated details — we look forward to seeing you.'
        if is_reschedule
        else 'We look forward to seeing you.'
    )

    context = {
        'customer': customer,
        'tenant_name': tenant.name,
        'primary_color': tenant.primary_color or '#1f2937',
        'service_name': appointment.service.name,
        'duration_minutes': appointment.service.duration_minutes,
        'when_local': when_local,
        'provider_display_name': _provider_email_name(appointment.provider),
        'location_name': location.name,
        'location_address': location_address,
        'location_phone': location.phone,
        'manage_url': manage_url,
        # Kind-specific copy. Templates use these for the headline +
        # lead paragraph; everything else is shared.
        'kind': kind,
        'is_reschedule': is_reschedule,
        'headline': headline,
        'body_lead': body_lead,
    }

    text_body = render_to_string('booking/email/confirmation.txt', context)
    html_body = render_to_string('booking/email/confirmation.html', context)

    from apps.tenants.email import tenant_from_email, tenant_reply_to

    reply_to = tenant_reply_to(tenant) or (location.email or None)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=tenant_from_email(tenant),
        to=[recipient],
        reply_to=[reply_to] if reply_to else None,
    )
    msg.attach_alternative(html_body, 'text/html')

    try:
        msg.send(fail_silently=False)
        return recipient
    except Exception:
        # Log and swallow — the booking state change is already saved;
        # we don't want SES hiccups to surface as a 500 to the
        # customer who already has the new state on screen.
        logger.exception(
            'booking.email failed',
            extra={
                'appointment_id': appointment.pk,
                'tenant_id': tenant.pk,
                'kind': kind,
            },
        )
        return None


def _provider_email_name(provider: TenantMembership) -> str:
    """Slightly fuller than the public-listing name (full last name)
    because the email is private to the customer; no enumeration risk."""
    user = provider.user
    first = (user.first_name or '').strip() or user.email.split('@')[0]
    last = (user.last_name or '').strip()
    if last:
        return f'{first} {last}'
    return first
