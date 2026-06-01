"""Tool implementations + JSONSchema schemas for the SMS agent.

Each tool:
    - has a JSONSchema definition the model sees (TOOL_SCHEMAS list)
    - has a Python implementation invoked by the agent loop (TOOL_FUNCS dict)
    - writes one AIToolCall row per invocation, scrubbed
    - returns a small JSON-serializable result the agent feeds back to Claude

ALL state changes are scoped to the tenant + customer on the
AIConversation. PHI exclusion list is enforced in
get_customer_context — chart notes, treatment records, intake
answers, medical history, insurance, payment-method details NEVER
flow through.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from django.db import models
from typing import TYPE_CHECKING, Any, Callable

from django.utils import timezone as djtz

from apps.ai_inbox.models import (
    AIConfig,
    AIConversation,
    AIToolCall,
    EscalationAlert,
)
from apps.ai_inbox.services.scrub import scrub_for_log

if TYPE_CHECKING:
    from apps.customers.models import Customer
    from apps.messaging.models import Message
    from apps.tenants.models import Tenant


logger = logging.getLogger(__name__)


# Range used when the model doesn't specify a date range.
_DEFAULT_AVAILABILITY_HORIZON_DAYS = 14
# Per-tool result cap (number of slots returned to the model). When
# the agent provides a time-of-day window (time_from/time_to), we
# raise the cap so we don't accidentally truncate inside the window —
# otherwise the agent could erroneously tell the customer "no
# openings at 2pm" because we cut off at slot 6 in the early morning.
_MAX_SLOTS_RETURNED = 8
_MAX_SLOTS_RETURNED_WITH_WINDOW = 12


def _provider_display_name(membership) -> str:
    """Short, customer-facing name for a provider so the agent can say
    "2pm with Sarah" instead of an opaque id. First name when we have
    it, then "First L.", then the email local-part as a last resort."""
    user = getattr(membership, 'user', None)
    if user is None:
        return 'a provider'
    first = (getattr(user, 'first_name', '') or '').strip()
    last = (getattr(user, 'last_name', '') or '').strip()
    if first and last:
        return f'{first} {last[0]}.'
    if first:
        return first
    email = getattr(user, 'email', '') or ''
    return email.split('@')[0] or 'a provider'


# ── Tool schemas (Anthropic / Bedrock Messages-API format) ───────


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        'name': 'get_customer_context',
        'description': (
            "Read the customer's appointment history, packages, memberships, "
            'outstanding balance, and gift-card balance. Use BEFORE making any '
            'promise about what the customer has. Each field in `fields` is '
            'returned only if requested. Never returns chart notes, medical '
            'history, intake form answers, insurance, or payment methods — '
            'those are out of scope for SMS.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'fields': {
                    'type': 'array',
                    'items': {
                        'type': 'string',
                        'enum': [
                            'recent_appointments',
                            'upcoming_appointments',
                            'active_packages',
                            'active_memberships',
                            'outstanding_balance_cents',
                            'gift_card_balance_cents',
                        ],
                    },
                },
            },
            'required': ['fields'],
        },
    },
    {
        'name': 'find_service',
        'description': (
            "Search the spa's service catalog for services matching the "
            "customer's request. Returns up to 10 matching services with "
            'id, name, category, duration, and price. ALWAYS call this '
            'BEFORE check_availability to discover the real service_id '
            '— NEVER guess a service_id. If the customer says "injectables" '
            'or "consultation" or "facial", call find_service with that '
            'query first.\n\n'
            'Returned shape: {matches: [{id, name, category, duration_minutes, price_cents}, ...]}\n\n'
            'If 0 matches → ask the customer to clarify what they want.\n'
            'If multiple matches → list 2-4 options to the customer and ask which.\n'
            'If 1 match → proceed to check_availability with that service_id.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'Free-text search term, e.g. "injectable", "facial", "consultation".',
                },
            },
            'required': ['query'],
        },
    },
    {
        'name': 'check_availability',
        'description': (
            'Return open appointment slots for a service in a date '
            'AND optional time-of-day window. Only returns slots for '
            'providers ELIGIBLE for the service — a massage therapist '
            "won't be returned for an injectable. Date strings are "
            'ISO 8601 (YYYY-MM-DD). Time strings are 24h HH:MM in the '
            "spa's local timezone.\n\n"
            'IF the customer mentions a time preference ("around 2pm", '
            '"morning", "evening", "between 1 and 3"), YOU MUST pass '
            'time_from/time_to so you only get slots in their window. '
            'Otherwise this tool returns the first 8 slots starting '
            'from date_from chronologically — which for a 9am-8pm day '
            'will be the early morning ones, and you\'ll mistakenly '
            'tell the customer no afternoon openings exist when they '
            'do.\n\n'
            'Returns up to 8 slots (12 if a time window is passed), '
            'each with a 1-based index. Automatically stages the '
            "returned slots as a pending booking proposal. The customer's "
            'digit reply (1-9) auto-books the slot at that index. '
            'service_id MUST come from a find_service result — never guess.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'service_id': {'type': 'integer'},
                'provider_id': {'type': 'integer'},
                'date_from': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'date_to': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'time_from': {
                    'type': 'string',
                    'description': '24h HH:MM lower bound on the slot start time (inclusive). E.g. "13:00" for 1pm.',
                },
                'time_to': {
                    'type': 'string',
                    'description': '24h HH:MM upper bound on the slot start time (exclusive). E.g. "15:00" for 3pm.',
                },
                'location_id': {'type': 'integer'},
                'appointment_id': {
                    'type': 'integer',
                    'description': (
                        'ONLY when rescheduling: the id of the existing '
                        'appointment being moved (from upcoming_appointments). '
                        'Pass it so the slots are staged as a RESCHEDULE — the '
                        "customer's digit reply then moves that appointment "
                        'instead of booking a new one. Defaults the provider '
                        'to the appointment\'s current technician unless you '
                        'also pass provider_id.'
                    ),
                },
            },
            'required': ['service_id'],
        },
    },
    {
        'name': 'list_providers',
        'description': (
            'List the technicians/providers who can perform a service, so '
            'you can offer the customer a choice or honor a request for a '
            'specific person. ALWAYS call this (after find_service) when the '
            'customer names a technician ("can I see Sarah?") OR proactively '
            'offer a choice when there is more than one option. To book with '
            'a chosen technician, pass that person\'s id as provider_id to '
            'check_availability.\n\n'
            'Returns: {providers: [{id, name}, ...]} — already filtered to '
            'those eligible for THIS service. If only one provider comes '
            "back, there's no real choice — just proceed. If zero, the "
            'service has no bookable provider; offer to have someone follow '
            'up (escalate).'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'service_id': {'type': 'integer'},
                'location_id': {'type': 'integer'},
            },
            'required': ['service_id'],
        },
    },
    {
        'name': 'confirm_booking',
        'description': (
            'Stage 2 of 2-step booking. Books the slot at the given index '
            'from the pending proposal. Usually the system fast-paths this '
            "directly from a digit reply — you only need to call it if the "
            "customer's reply is fuzzy (\"the first one\")."
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'slot_index': {'type': 'integer', 'minimum': 1, 'maximum': 9},
            },
            'required': ['slot_index'],
        },
    },
    {
        'name': 'reschedule_appointment',
        'description': (
            'Move an EXISTING upcoming appointment to a new time (and, if '
            'the customer asks for a different technician, a new provider). '
            'Do NOT book a second appointment for a reschedule — that '
            'double-books the customer.\n\n'
            'Flow:\n'
            '1. Call get_customer_context(fields=["upcoming_appointments"]) '
            'to get the appointment and its id. If there are several, ask '
            'which one.\n'
            '2. Call check_availability for the SAME service and pass '
            'appointment_id=<that id> (this stages the slots as a '
            "RESCHEDULE so the customer's digit reply moves the existing "
            'appointment, not a new booking). Add provider_id if they '
            'want a different tech, plus any time window.\n'
            '3. The digit reply usually completes the move automatically. '
            "Only call reschedule_appointment yourself if the customer's "
            'choice is fuzzy ("the first one"). After a reschedule '
            'succeeds, confirm the NEW date/time back to the customer — '
            'unlike a new booking, no separate confirmation text is sent.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'appointment_id': {'type': 'integer'},
                'slot_index': {'type': 'integer', 'minimum': 1, 'maximum': 9},
            },
            'required': ['appointment_id', 'slot_index'],
        },
    },
    {
        'name': 'update_customer_profile',
        'description': (
            "Update the customer's first name, last name, or email when you "
            'learn it during the conversation. Cannot touch phone, status, '
            'opt-in flags, marketing fields, or medical fields.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'first_name': {'type': 'string', 'maxLength': 60},
                'last_name': {'type': 'string', 'maxLength': 60},
                'email': {'type': 'string', 'maxLength': 200},
            },
        },
    },
    {
        'name': 'escalate_to_human',
        'description': (
            'Stop the AI conversation and route to staff. Use when the customer '
            'asks for a person, asks anything clinical, asks about payments / '
            'refunds, is upset, or anything outside booking. After this you '
            'should send one short SMS ("a teammate will text you shortly") '
            'and stop.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'reason': {
                    'type': 'string',
                    'enum': [
                        'requested_human',
                        'clinical_question',
                        'payment_dispute',
                        'complaint',
                        'unsupported_request',
                    ],
                },
                'summary': {'type': 'string', 'maxLength': 500},
            },
            'required': ['reason'],
        },
    },
]


# Instagram-only tool: capture a new lead's contact info. Write-only
# (no PHI read), so it's HIPAA-safe over a non-BAA channel. The Meta
# webhook auto-creates a social-guest Customer with only the IG
# display name; this fleshes it out (name + phone + email) and
# promotes it to a real Instagram-sourced lead.
_CAPTURE_LEAD_SCHEMA: dict[str, Any] = {
    'name': 'capture_lead_info',
    'description': (
        'Record a NEW customer\'s contact details when they tell you '
        "they're not an existing client. Collects name, phone, and "
        'email and creates them as a customer marked as Instagram-'
        'sourced. Use this once the person has shared their info '
        '(ideally before or right as you book). Write-only — it does '
        'NOT and cannot read any existing account data. Always try to '
        'get at least a first name + a phone number so the spa can '
        'reach them.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'first_name': {'type': 'string', 'maxLength': 60},
            'last_name': {'type': 'string', 'maxLength': 60},
            'phone': {'type': 'string', 'maxLength': 32},
            'email': {'type': 'string', 'maxLength': 200},
        },
        'required': ['first_name'],
    },
}

# Instagram tool set = the full set MINUS get_customer_context (the
# PHI read tool — Meta is NOT BAA-covered, so the agent must have no
# mechanism to read PHI; the safety is structural, not just
# prompt-level, see ADR 0033) MINUS reschedule_appointment (it relies
# on reading the customer's existing appointments, which is PHI we
# can't surface over Instagram) PLUS the capture_lead_info write tool.
_INSTAGRAM_EXCLUDED_TOOLS = {'get_customer_context', 'reschedule_appointment'}
TOOL_SCHEMAS_INSTAGRAM: list[dict[str, Any]] = [
    schema for schema in TOOL_SCHEMAS
    if schema['name'] not in _INSTAGRAM_EXCLUDED_TOOLS
] + [_CAPTURE_LEAD_SCHEMA]


# ── Dispatcher ───────────────────────────────────────────────────


def dispatch_tool(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    tenant: 'Tenant',
    customer: 'Customer',
    conversation: AIConversation,
    triggered_by_message: 'Message',
    model_used: str,
) -> dict[str, Any]:
    """Run one tool. Wraps execution in timing + audit-row write + error capture.

    Returns the tool's result dict on success, or
    ``{'error': '...'}`` on failure (so the agent loop can feed it
    back to Claude rather than crashing the turn).
    """
    impl = TOOL_FUNCS.get(tool_name)
    if impl is None:
        result = {'error': f'unknown_tool:{tool_name}'}
        _record_tool_call(
            tenant=tenant, conversation=conversation,
            triggered_by_message=triggered_by_message,
            tool_name=tool_name, tool_input=tool_input,
            output=result, success=False,
            error_message=result['error'], latency_ms=0,
            model_used=model_used,
        )
        return result

    started = time.perf_counter()
    try:
        result = impl(
            tool_input=tool_input,
            tenant=tenant,
            customer=customer,
            conversation=conversation,
        )
        success = True
        error_message = ''
    except Exception as exc:  # noqa: BLE001  — agent loop boundary
        logger.exception(
            'ai_inbox.tool_failed tenant=%s tool=%s', tenant.slug, tool_name,
        )
        result = {'error': f'tool_exception:{type(exc).__name__}'}
        success = False
        error_message = str(exc)[:480]
    latency_ms = int((time.perf_counter() - started) * 1000)

    _record_tool_call(
        tenant=tenant, conversation=conversation,
        triggered_by_message=triggered_by_message,
        tool_name=tool_name, tool_input=tool_input,
        output=result, success=success,
        error_message=error_message, latency_ms=latency_ms,
        model_used=model_used,
    )
    return result


def _record_tool_call(
    *,
    tenant: 'Tenant',
    conversation: AIConversation,
    triggered_by_message: 'Message',
    tool_name: str,
    tool_input: dict,
    output: dict,
    success: bool,
    error_message: str,
    latency_ms: int,
    model_used: str,
) -> None:
    AIToolCall.objects.create(
        tenant=tenant,
        conversation=conversation,
        triggered_by_message=triggered_by_message,
        tool_name=tool_name,
        input_json=scrub_for_log(tool_input),
        output_json=scrub_for_log(output),
        success=success,
        error_message=error_message,
        latency_ms=latency_ms,
        model_used=model_used,
    )


# ── Tool implementations ────────────────────────────────────────


def _tool_get_customer_context(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    from apps.appointments.models import Appointment
    from apps.invoices.models import Invoice
    from apps.memberships.models import Subscription
    from apps.packages.models import PurchasedPackage

    requested = set(tool_input.get('fields') or [])
    out: dict[str, Any] = {}

    if 'recent_appointments' in requested:
        rows = (
            Appointment.objects
            .filter(tenant=tenant, customer=customer, start_time__lt=djtz.now())
            .select_related('service', 'provider__user')
            .order_by('-start_time')[:12]
        )
        out['recent_appointments'] = [
            {
                'date': r.start_time.date().isoformat(),
                'service': r.service.name if r.service else None,
                'provider_first_name': (
                    r.provider.user.first_name if r.provider and r.provider.user else None
                ),
                'status': r.status,
            }
            for r in rows
        ]

    if 'upcoming_appointments' in requested:
        rows = (
            Appointment.objects
            .filter(tenant=tenant, customer=customer, start_time__gte=djtz.now())
            .select_related('service', 'provider__user')
            .order_by('start_time')[:12]
        )
        out['upcoming_appointments'] = [
            {
                # `id` is required to reschedule a specific appointment —
                # the agent passes it to reschedule_appointment.
                'id': r.id,
                'date': r.start_time.date().isoformat(),
                'time_local': r.start_time.strftime('%H:%M'),
                'service': r.service.name if r.service else None,
                'provider_first_name': (
                    r.provider.user.first_name if r.provider and r.provider.user else None
                ),
                'status': r.status,
            }
            for r in rows
        ]

    if 'active_packages' in requested:
        # Filter to packages the customer can ACTUALLY redeem against:
        # status=active, not expired, and at least one credit left.
        # The "active" terminology here means redeemable, which is what
        # the customer means when they ask "what packages do I have?"
        now = djtz.now()
        candidates = (
            PurchasedPackage.objects
            .filter(tenant=tenant, customer=customer, status='active')
            .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
            .prefetch_related('items')
            .order_by('expires_at')
        )
        packages = []
        for pkg in candidates:
            items = [
                {
                    'service_name': item.service_name,
                    'remaining': item.quantity_remaining,
                    'purchased': item.quantity_purchased,
                }
                for item in pkg.items.all()
                if item.quantity_remaining > 0
            ]
            if not items:
                # Package has no credits left across any line item — not
                # useful to surface even though status=active.
                continue
            packages.append({
                'package_id': pkg.id,
                'package_name': (
                    pkg.source_template.name if pkg.source_template_id else 'Package'
                ),
                'total_credits_remaining': pkg.total_credits_remaining,
                'expires_at': (
                    pkg.expires_at.isoformat() if pkg.expires_at else None
                ),
                'items': items,
            })
        out['active_packages'] = packages

    if 'active_membership' in requested:
        # Active memberships only — status=active AND inside the
        # current billing period. A "cancelled" or "expired" sub still
        # exists in the DB but the customer can't redeem against it,
        # so don't surface it as something they "have".
        now = djtz.now()
        candidates = (
            Subscription.objects
            .filter(tenant=tenant, customer=customer, status='active')
            .select_related('plan')
            .prefetch_related('items__service', 'items__category')
            .order_by('-id')
        )
        memberships = []
        for sub in candidates:
            in_period = (
                sub.current_period_starts_at is not None
                and sub.current_period_ends_at is not None
                and sub.current_period_starts_at <= now <= sub.current_period_ends_at
            ) if hasattr(sub, 'current_period_starts_at') else bool(
                sub.current_period_ends_at and sub.current_period_ends_at > now
            )
            items = []
            for item in sub.items.all():
                target = (
                    item.service.name if item.service_id else
                    f'Any {item.category.name}' if item.category_id else
                    'Membership credit'
                )
                items.append({
                    'covers': target,
                    'remaining_this_cycle': item.quantity_remaining,
                    'per_cycle': item.quantity_per_cycle,
                })
            memberships.append({
                'plan_name': sub.plan.name if sub.plan else None,
                'in_current_period': in_period,
                'next_renewal_at': (
                    sub.current_period_ends_at.isoformat()
                    if sub.current_period_ends_at else None
                ),
                'total_credits_remaining_this_cycle': sub.total_credits_remaining,
                'items': items,
            })
        # Keep the response shape stable: even with multiple memberships,
        # return as a list. For one-membership tenants this is just [{...}].
        out['active_memberships'] = memberships

    if 'outstanding_balance_cents' in requested:
        invoices = Invoice.objects.filter(
            tenant=tenant, customer=customer,
        ).exclude(status='paid')
        out['outstanding_balance_cents'] = sum(
            (i.total_cents or 0) - (i.amount_paid_cents or 0)
            for i in invoices
        )

    if 'gift_card_balance_cents' in requested:
        from apps.giftcards.models import GiftCard
        cards = GiftCard.objects.filter(
            tenant=tenant, issued_to_customer=customer,
        )
        out['gift_card_balance_cents'] = sum(c.balance_cents or 0 for c in cards)

    return out


def _tool_find_service(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    """Fuzzy match a query against the tenant's bookable service catalog.

    Strategy:
        - Case-insensitive substring match on Service.name OR
          ServiceCategory.name. Both because the customer might say
          "injectable" (category) or "Juvederm" (service).
        - Filter by is_bookable_online=True so we don't surface services
          the spa hasn't made public.
        - Return top 10 (sort by name) so Claude can ask the customer
          to pick if multiple match.
    """
    from apps.services.models import Service

    query = (tool_input.get('query') or '').strip()
    if not query:
        return {'error': 'empty_query', 'matches': []}

    matches = (
        Service.objects
        .filter(tenant=tenant, is_bookable_online=True)
        .filter(
            models.Q(name__icontains=query) |
            models.Q(category__name__icontains=query)
        )
        .select_related('category')
        .order_by('name')[:10]
    )

    rows = [
        {
            'id': s.id,
            'name': s.name,
            'category': s.category.name if s.category else None,
            'duration_minutes': s.duration_minutes,
            'price_cents': s.price_cents,
        }
        for s in matches
    ]
    return {'matches': rows, 'query': query}


def _tool_check_availability(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    from apps.booking.availability import (
        compute_any_provider_slots,
        compute_provider_slots,
    )
    from apps.booking.views import _eligible_providers
    from apps.services.models import Service
    from apps.tenants.models import Location, TenantMembership

    service_id = tool_input.get('service_id')
    service = Service.objects.filter(
        tenant=tenant, id=service_id, is_bookable_online=True,
    ).select_related('category').first()
    if service is None:
        return {'error': 'service_not_found_or_not_bookable_online'}

    # Resolve location — fall back to the first tenant location if unset.
    location_id = tool_input.get('location_id')
    if location_id:
        location = Location.objects.filter(tenant=tenant, id=location_id).first()
    else:
        location = Location.objects.filter(tenant=tenant).order_by('id').first()
    if location is None:
        return {'error': 'no_location'}

    # Date window.
    today = djtz.localdate()
    date_from = _parse_date(tool_input.get('date_from')) or today
    date_to = _parse_date(tool_input.get('date_to')) or (
        date_from + dt.timedelta(days=_DEFAULT_AVAILABILITY_HORIZON_DAYS)
    )
    if date_to < date_from:
        date_to = date_from

    # Time-of-day window (optional). Customers often say "around 2pm"
    # or "morning" — without this filter the agent would get back the
    # first 8 chronological slots of the day (e.g. 9-10:15am) and
    # erroneously report no openings at 2pm even though they exist.
    time_from = _parse_time(tool_input.get('time_from'))
    time_to = _parse_time(tool_input.get('time_to'))
    has_time_window = time_from is not None or time_to is not None
    cap = _MAX_SLOTS_RETURNED_WITH_WINDOW if has_time_window else _MAX_SLOTS_RETURNED

    # Resolve the location's timezone for the time-of-day comparison.
    # All slot datetimes returned by compute_*_slots are TZ-aware in
    # the location's local timezone.
    import zoneinfo
    try:
        location_tz = zoneinfo.ZoneInfo(location.timezone or 'America/New_York')
    except zoneinfo.ZoneInfoNotFoundError:
        location_tz = zoneinfo.ZoneInfo('America/New_York')

    # Reschedule mode — the agent passes the existing appointment's id so
    # these slots move it instead of booking a new one. We exclude that
    # appointment from its own conflict set (so a small shift near its
    # current time isn't blocked) and default the provider to whoever is
    # currently booked unless the customer asked for someone else.
    reschedule_appt = None
    exclude_appointment_id = None
    appointment_id = tool_input.get('appointment_id')
    if appointment_id:
        from apps.appointments.models import Appointment
        reschedule_appt = (
            Appointment.objects
            .filter(tenant=tenant, customer=customer, id=appointment_id)
            .first()
        )
        if reschedule_appt is None:
            return {'error': 'appointment_not_found'}
        exclude_appointment_id = reschedule_appt.id

    provider_id = tool_input.get('provider_id')
    if not provider_id and reschedule_appt is not None:
        # Keep the same technician on a reschedule by default.
        provider_id = reschedule_appt.provider_id
    if provider_id:
        # Caller asked for a specific provider — verify the provider is
        # actually eligible for THIS service (not just generally bookable).
        eligible = _eligible_providers(
            tenant=tenant, service=service, location=location,
        )
        provider = next((p for p in eligible if p.id == int(provider_id)), None)
        if provider is None:
            return {'error': 'provider_not_eligible_for_service'}
        providers = [provider]
    else:
        # Reuse the existing public-booking eligibility logic — only
        # surface providers whose job-title category matches the
        # service. A massage therapist won't appear for an injectable.
        providers = _eligible_providers(
            tenant=tenant, service=service, location=location,
        )
        if not providers:
            return {'error': 'no_eligible_providers_for_service'}

    collected: list[dict] = []
    cur = date_from
    # Inner safety cap so a tenant with very sparse schedules doesn't
    # spin the day-loop forever; quadruple the result cap is plenty.
    inner_cap = cap * 4
    while cur <= date_to and len(collected) < inner_cap:
        if len(providers) == 1:
            day_slots = [
                {
                    'start_iso': s.start.isoformat(),
                    'end_iso': s.end.isoformat(),
                    'provider_id': providers[0].id,
                    '_start_dt': s.start,
                }
                for s in compute_provider_slots(
                    provider=providers[0], service=service,
                    location=location, on_date=cur,
                    exclude_appointment_id=exclude_appointment_id,
                )
                if s.available
            ]
        else:
            payloads = compute_any_provider_slots(
                eligible_providers=providers, service=service,
                location=location, on_date=cur,
            )
            day_slots = []
            for p in payloads:
                if not p['available']:
                    continue
                try:
                    parsed = dt.datetime.fromisoformat(p['start'])
                except (TypeError, ValueError):
                    parsed = None
                day_slots.append({
                    'start_iso': p['start'],
                    'end_iso': p['end'],
                    'provider_id': p.get('provider_id'),
                    '_start_dt': parsed,
                })

        for slot in day_slots:
            # Apply time-of-day filter if the caller passed one.
            if has_time_window and slot['_start_dt'] is not None:
                local_start = slot['_start_dt'].astimezone(location_tz)
                local_time = local_start.time()
                if time_from is not None and local_time < time_from:
                    continue
                if time_to is not None and local_time >= time_to:
                    continue
            collected.append({
                'start_iso': slot['start_iso'],
                'end_iso': slot['end_iso'],
                'provider_id': slot.get('provider_id'),
                'service_id': service.id,
                'location_id': location.id,
                'label': _human_label(slot['start_iso']),
            })
            if len(collected) >= cap:
                break
        if len(collected) >= cap:
            break
        cur += dt.timedelta(days=1)

    final = collected[:cap]

    # Auto-stamp pending_proposal so the digit fast-path works
    # WITHOUT requiring Claude to remember a second tool call.
    # The user's "1" / "2" / "3" reply maps to the SAME indices we
    # return here. Includes 24h TTL — long enough for the
    # customer to chew on it, short enough to avoid stale booking
    # races against staff edits to the calendar.
    if final:
        # Map provider id → display name so the agent can say "with
        # Sarah" and the customer can pick a person they recognise.
        provider_names = {p.id: _provider_display_name(p) for p in providers}
        indexed = [
            {
                'index': i + 1,
                'start_iso': s['start_iso'],
                'end_iso': s['end_iso'],
                'provider_id': s.get('provider_id'),
                'provider_name': provider_names.get(s.get('provider_id')),
                'service_id': s['service_id'],
                'location_id': s['location_id'],
                'label': s['label'],
            }
            for i, s in enumerate(final)
        ]
        conversation.pending_proposal = {
            'service_id': service.id,
            'location_id': location.id,
            'provider_id': final[0].get('provider_id'),
            # Set on a reschedule so the digit fast-path MOVES this
            # appointment instead of booking a new one (the bug that
            # double-booked customers). Absent for normal bookings.
            'reschedule_appointment_id': (
                reschedule_appt.id if reschedule_appt is not None else None
            ),
            'proposed_at': djtz.now().isoformat(),
            'slots': indexed,
        }
        conversation.pending_proposal_expires_at = djtz.now() + dt.timedelta(hours=24)
        conversation.save(update_fields=[
            'pending_proposal', 'pending_proposal_expires_at', 'updated_at',
        ])
        # Return indexed slots so Claude sees the same indices the
        # user will type. Avoids any "Claude renumbers in the SMS"
        # foot-gun.
        return {'slots': indexed}

    return {'slots': []}


def _tool_propose_slots(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    indices = tool_input.get('slot_indices') or []
    if not indices:
        return {'error': 'no_slot_indices'}

    # Pull the most recent check_availability result for this conversation.
    last_check = (
        AIToolCall.objects
        .filter(conversation=conversation, tool_name='check_availability', success=True)
        .order_by('-created_at')
        .first()
    )
    if last_check is None:
        return {'error': 'no_recent_availability_check'}
    available_slots = (last_check.output_json or {}).get('slots') or []
    if not available_slots:
        return {'error': 'last_check_returned_no_slots'}

    chosen = []
    for one_based in indices:
        idx = int(one_based) - 1
        if 0 <= idx < len(available_slots):
            s = available_slots[idx]
            chosen.append({
                'index': len(chosen) + 1,  # renumber 1..N for the customer
                'start_iso': s['start_iso'],
                'end_iso': s['end_iso'],
                'provider_id': s.get('provider_id'),
                'service_id': s['service_id'],
                'location_id': s['location_id'],
                'label': s['label'],
            })

    if not chosen:
        return {'error': 'no_valid_indices'}

    proposal = {
        'service_id': chosen[0]['service_id'],
        'location_id': chosen[0]['location_id'],
        'provider_id': chosen[0].get('provider_id'),
        'proposed_at': djtz.now().isoformat(),
        'slots': chosen,
    }
    conversation.pending_proposal = proposal
    conversation.pending_proposal_expires_at = djtz.now() + dt.timedelta(hours=24)
    conversation.save(update_fields=[
        'pending_proposal', 'pending_proposal_expires_at', 'updated_at',
    ])
    return {'proposed': chosen}


def _tool_confirm_booking(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    return run_confirm_booking(
        slot_index=int(tool_input.get('slot_index', 0)),
        tenant=tenant, customer=customer, conversation=conversation,
    )


def run_confirm_booking(
    *,
    slot_index: int,
    tenant: 'Tenant',
    customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    """Public-style confirm-booking entrypoint.

    Also used by the digit-fast-path in the agent loop — that path
    skips Claude entirely and calls this directly.
    """
    proposal = conversation.pending_proposal or {}
    expires_at = conversation.pending_proposal_expires_at
    if not proposal or expires_at is None or expires_at < djtz.now():
        return {'error': 'no_active_proposal'}

    slots = proposal.get('slots') or []
    chosen = next((s for s in slots if s.get('index') == slot_index), None)
    if chosen is None:
        return {'error': 'slot_index_out_of_range'}

    from apps.booking.services_ai import book_appointment_for_ai
    from apps.services.models import Service
    from apps.tenants.models import Location, TenantMembership

    service = Service.objects.filter(tenant=tenant, id=chosen['service_id']).first()
    location = Location.objects.filter(tenant=tenant, id=chosen['location_id']).first()
    provider_id = chosen.get('provider_id')
    if provider_id is None or service is None or location is None:
        return {'error': 'proposal_resolution_failed'}
    provider = TenantMembership.objects.filter(
        tenant=tenant, id=provider_id, is_bookable=True, is_active=True,
    ).first()
    if provider is None:
        return {'error': 'provider_no_longer_bookable'}

    start_iso = chosen['start_iso']
    end_iso = chosen['end_iso']
    start = dt.datetime.fromisoformat(start_iso)
    end = dt.datetime.fromisoformat(end_iso)

    try:
        appointment = book_appointment_for_ai(
            tenant=tenant, customer=customer, service=service,
            provider=provider, location=location,
            start_time=start, end_time=end,
            channel=getattr(conversation, 'channel', 'sms'),
        )
    except Exception as exc:  # noqa: BLE001
        return {'error': f'booking_failed:{type(exc).__name__}', 'detail': str(exc)[:200]}

    conversation.pending_proposal = None
    conversation.pending_proposal_expires_at = None
    conversation.save(update_fields=[
        'pending_proposal', 'pending_proposal_expires_at', 'updated_at',
    ])

    return {
        'appointment_id': appointment.id,
        'starts_at': start.isoformat(),
        'service': service.name,
        'human_label': _human_label(start_iso),
    }


def _tool_list_providers(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    """Eligible technicians for a service, so the agent can offer a
    choice or honor a requested person. Reuses the public-booking
    eligibility logic (bookable + assigned to location + job-title
    matches the service category)."""
    from apps.booking.views import _eligible_providers
    from apps.services.models import Service
    from apps.tenants.models import Location

    service = Service.objects.filter(
        tenant=tenant, id=tool_input.get('service_id'), is_bookable_online=True,
    ).select_related('category').first()
    if service is None:
        return {'error': 'service_not_found_or_not_bookable_online'}

    location_id = tool_input.get('location_id')
    if location_id:
        location = Location.objects.filter(tenant=tenant, id=location_id).first()
    else:
        location = Location.objects.filter(tenant=tenant).order_by('id').first()
    if location is None:
        return {'error': 'no_location'}

    providers = _eligible_providers(tenant=tenant, service=service, location=location)
    return {
        'providers': [
            {'id': p.id, 'name': _provider_display_name(p)}
            for p in providers
        ],
    }


def _tool_reschedule_appointment(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    return run_reschedule(
        appointment_id=int(tool_input.get('appointment_id', 0)),
        slot_index=int(tool_input.get('slot_index', 0)),
        tenant=tenant, customer=customer, conversation=conversation,
    )


def run_reschedule(
    *,
    appointment_id: int,
    slot_index: int,
    tenant: 'Tenant',
    customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    """Move an existing upcoming appointment to a slot from the pending
    proposal. Mirrors run_confirm_booking but UPDATES the appointment
    instead of creating one — so a reschedule never double-books. Service
    stays the same; the time (and the technician, if the chosen slot uses
    a different one) moves. The new time is re-validated against the live
    slot calculator with this appointment excluded from its own conflict
    set. Also used directly by the digit fast-path."""
    from django.db import transaction

    from apps.appointments.models import Appointment
    from apps.audit.models import AuditLog
    from apps.audit.services import record
    from apps.booking.availability import compute_provider_slots
    from apps.tenants.models import Location, TenantMembership

    proposal = conversation.pending_proposal or {}
    expires_at = conversation.pending_proposal_expires_at
    if not proposal or expires_at is None or expires_at < djtz.now():
        return {'error': 'no_active_proposal'}
    slots = proposal.get('slots') or []
    chosen = next((s for s in slots if s.get('index') == slot_index), None)
    if chosen is None:
        return {'error': 'slot_index_out_of_range'}

    with transaction.atomic():
        try:
            appt = (
                Appointment.objects
                .select_for_update(of=('self',))
                .select_related('service', 'provider', 'location')
                .get(pk=appointment_id, tenant=tenant, customer=customer)
            )
        except Appointment.DoesNotExist:
            return {'error': 'appointment_not_found'}

        if appt.start_time <= djtz.now():
            return {'error': 'appointment_in_past'}
        if appt.status not in (
            Appointment.Status.BOOKED, Appointment.Status.CONFIRMED,
        ):
            return {'error': f'appointment_not_reschedulable:{appt.status}'}

        # A reschedule keeps the same service — changing service is a new
        # booking, not a move.
        if int(chosen.get('service_id') or 0) != appt.service_id:
            return {'error': 'service_mismatch'}

        location = (
            Location.objects.filter(tenant=tenant, id=chosen.get('location_id')).first()
            or appt.location
        )
        provider_id = chosen.get('provider_id')
        provider = (
            TenantMembership.objects.filter(
                tenant=tenant, id=provider_id, is_bookable=True, is_active=True,
            ).first()
            if provider_id else None
        )
        if provider is None:
            return {'error': 'provider_no_longer_bookable'}

        try:
            new_start = dt.datetime.fromisoformat(chosen['start_iso'])
            new_end = dt.datetime.fromisoformat(chosen['end_iso'])
        except (KeyError, TypeError, ValueError):
            return {'error': 'proposal_resolution_failed'}

        # Re-validate against the live calculator, excluding this
        # appointment so its own current slot doesn't block the move.
        available = compute_provider_slots(
            provider=provider, service=appt.service, location=location,
            on_date=djtz.localtime(new_start).date(),
            exclude_appointment_id=appt.id,
        )
        if not any(s.start == new_start and s.available for s in available):
            return {'error': 'slot_no_longer_available'}

        previous_start = appt.start_time
        update_fields = ['start_time', 'end_time', 'updated_at']
        appt.start_time = new_start
        appt.end_time = new_end
        if provider.id != appt.provider_id:
            appt.provider = provider
            update_fields.insert(0, 'provider')
        appt.save(update_fields=update_fields)

    conversation.pending_proposal = None
    conversation.pending_proposal_expires_at = None
    conversation.save(update_fields=[
        'pending_proposal', 'pending_proposal_expires_at', 'updated_at',
    ])

    try:
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appt.id,
            tenant=tenant,
            metadata={
                'event': 'ai_reschedule',
                'channel': getattr(conversation, 'channel', 'sms'),
                'customer_id': customer.id,
                'from_start': previous_start.isoformat(),
                'to_start': new_start.isoformat(),
                'provider_id': appt.provider_id,
            },
        )
    except Exception:  # noqa: BLE001 — audit must never break the turn
        logger.exception('ai_inbox.reschedule_audit_failed tenant=%s', tenant.slug)

    return {
        'appointment_id': appt.id,
        'starts_at': new_start.isoformat(),
        'service': appt.service.name,
        'human_label': _human_label(chosen['start_iso']),
        'rescheduled': True,
    }


def _tool_update_customer_profile(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    allowed = ('first_name', 'last_name', 'email')
    updates = {k: v for k, v in tool_input.items() if k in allowed and v}
    if not updates:
        return {'updated': []}
    for k, v in updates.items():
        setattr(customer, k, v[:200].strip())
    customer.save(update_fields=list(updates.keys()) + ['updated_at'])
    return {'updated': list(updates.keys())}


def _tool_capture_lead_info(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    """Instagram-only: record a new lead's contact info + promote the
    social guest to a confirmed Instagram-sourced customer.

    Write-only — never reads existing account data. acquisition_source
    is immutable after create and was already set to INSTAGRAM by the
    Meta webhook when the social guest was auto-created, so we leave it
    alone. We flip is_social_guest → False (the person has now given
    real contact info, so they belong in the main customer list).
    """
    from apps.customers.models import Customer as CustomerModel

    fields = []
    fn = (tool_input.get('first_name') or '').strip()
    ln = (tool_input.get('last_name') or '').strip()
    phone = (tool_input.get('phone') or '').strip()
    email = (tool_input.get('email') or '').strip()

    if fn:
        customer.first_name = fn[:100]
        fields.append('first_name')
    if ln:
        customer.last_name = ln[:100]
        fields.append('last_name')
    if phone and not (customer.phone or '').strip():
        # Only fill phone if we don't already have one — never
        # overwrite a real number with something typed in a DM.
        customer.phone = phone[:20]
        fields.append('phone')
    if email and not (customer.email or '').strip():
        customer.email = email[:200]
        fields.append('email')

    # Promote the social guest now that they've shared real info.
    if getattr(customer, 'is_social_guest', False):
        customer.is_social_guest = False
        fields.append('is_social_guest')

    if not fields:
        return {'captured': []}

    customer.save(update_fields=fields + ['updated_at'])
    return {
        'captured': fields,
        'acquisition_source': getattr(customer, 'acquisition_source', None),
    }


def _tool_escalate_to_human(
    *,
    tool_input: dict, tenant: 'Tenant', customer: 'Customer',
    conversation: AIConversation,
) -> dict:
    reason = tool_input.get('reason') or 'requested_human'
    summary = (tool_input.get('summary') or '')[:480]

    now = djtz.now()
    alert = EscalationAlert.objects.create(
        tenant=tenant, conversation=conversation, customer=customer,
        reason=reason, reason_detail=summary,
    )
    conversation.status = AIConversation.Status.ESCALATED
    conversation.escalated_at = now
    conversation.escalation_reason = reason
    conversation.save(update_fields=[
        'status', 'escalated_at', 'escalation_reason', 'updated_at',
    ])

    return {
        'escalated': True,
        'alert_id': alert.id,
        'reason': reason,
    }


TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    'get_customer_context': _tool_get_customer_context,
    'find_service': _tool_find_service,
    'list_providers': _tool_list_providers,
    'check_availability': _tool_check_availability,
    'propose_slots': _tool_propose_slots,
    'confirm_booking': _tool_confirm_booking,
    'reschedule_appointment': _tool_reschedule_appointment,
    'update_customer_profile': _tool_update_customer_profile,
    'capture_lead_info': _tool_capture_lead_info,
    'escalate_to_human': _tool_escalate_to_human,
}


# ── helpers ──────────────────────────────────────────────────────


def _parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def _parse_time(s: str | None) -> dt.time | None:
    """Parse a 24h HH:MM (or HH:MM:SS) time string from the agent.

    Returns None for invalid / empty input so the time-window filter
    silently no-ops rather than rejecting the whole tool call.
    """
    if not s:
        return None
    try:
        # Accept both '13:00' and '13:00:00'
        return dt.time.fromisoformat(s[:8])
    except (TypeError, ValueError):
        return None


def _human_label(start_iso: str) -> str:
    try:
        dt_obj = dt.datetime.fromisoformat(start_iso)
    except (TypeError, ValueError):
        return start_iso
    # E.g. "Tue Jun 3, 2:00pm"
    return dt_obj.strftime('%a %b %-d, %-I:%M%p').replace('AM', 'am').replace('PM', 'pm')
