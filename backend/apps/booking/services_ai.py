"""AI-agent-flavored booking helper.

The public booking flow (`submit_booking`) takes raw form input —
first_name / last_name / email / phone — and calls
`find_or_create_customer` to materialize the row. The AI agent
already knows the customer (from the AIConversation.customer FK),
so this helper takes the pre-resolved Customer directly.

It also skips the marketing-consent capture path — the SMS
exchange isn't a TCPA consent surface, so the existing booking
form's checkboxes don't apply here.

Lives in a separate module from `submit_booking` to keep the
public-form flow untouched; do NOT call into this from the public
endpoint or you'll skip consent logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.booking.services import generate_booking_token

if TYPE_CHECKING:
    import datetime as dt

    from apps.customers.models import Customer
    from apps.services.models import Service
    from apps.tenants.models import Location, Tenant, TenantMembership


logger = logging.getLogger(__name__)


def book_appointment_for_ai(
    *,
    tenant: 'Tenant',
    customer: 'Customer',
    service: 'Service',
    provider: 'TenantMembership',
    location: 'Location',
    start_time: 'dt.datetime',
    end_time: 'dt.datetime',
) -> Appointment:
    """Create the appointment for an AI-driven booking.

    Caller (tools.run_confirm_booking) is responsible for:
      - re-validating that the slot is still open (race window
        between propose_slots and the customer's digit reply).
        Today we rely on the standard appointment-uniqueness
        constraints to catch races at INSERT time.
      - clearing the AIConversation.pending_proposal on success.

    Source string is 'sms_ai' so reporting can split AI-driven
    bookings from operator-typed ones and from public-form
    bookings. `created_by` is null (no authenticated User in this
    flow) — the actor is the AI agent, surfaced via the audit log
    metadata below.
    """
    appointment = Appointment.objects.create(
        tenant=tenant,
        customer=customer,
        provider=provider,
        service=service,
        location=location,
        start_time=start_time,
        end_time=end_time,
        status=Appointment.Status.BOOKED,
        source='sms_ai',
        booking_token=generate_booking_token(),
        quoted_price_cents=service.price_cents,
    )

    # Audit-log the creation so it shows up on the appointment's
    # /logs page. user is None (no authenticated operator); the
    # AI-agent attribution lives in the metadata so the logs page
    # can render "Booked via AI agent" instead of an empty actor.
    record(
        action=AuditLog.Action.CREATE,
        resource_type='appointment',
        resource_id=appointment.id,
        tenant=tenant,
        user=None,
        metadata={
            'created_by': 'AI agent',
            'source': 'sms_ai',
            'customer_id': customer.id,
            'service_id': service.id,
            'service_name': service.name,
            'provider_id': provider.id,
            'location_id': location.id,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'customer_phone_last4': (customer.phone or '')[-4:],
        },
    )

    logger.info(
        'ai_inbox.booked tenant=%s appointment_id=%s customer_id=%s service_id=%s',
        tenant.slug, appointment.id, customer.id, service.id,
    )
    return appointment
