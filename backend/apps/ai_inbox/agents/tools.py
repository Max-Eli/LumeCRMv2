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
# Per-tool result cap (number of slots returned to the model).
_MAX_SLOTS_RETURNED = 6


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
                            'active_membership',
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
            'Return open appointment slots for a service in a date window. '
            'Only returns slots for providers who are ELIGIBLE for the service '
            "(based on the spa's service-category job-title eligibility rules) "
            "— a massage therapist won't be returned for an injectable. "
            'Date strings are ISO 8601 (YYYY-MM-DD). Returns at most 6 slots, '
            'each with a 1-based index. '
            'IMPORTANT: this call AUTOMATICALLY stages the returned slots '
            "as a pending booking proposal. The customer's digit reply "
            '(1-9) will auto-book the slot at that index. You do NOT need '
            'to call any other tool to make this work — just send a single '
            'SMS listing the slots using the EXACT indices and times '
            'returned, and end with "Reply 1, 2, or 3 to confirm." '
            'service_id MUST come from a find_service result — never guess.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'service_id': {'type': 'integer'},
                'provider_id': {'type': 'integer'},
                'date_from': {'type': 'string'},
                'date_to': {'type': 'string'},
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
        rows = (
            PurchasedPackage.objects
            .filter(tenant=tenant, customer=customer)
            .select_related('source_template')[:20]
        )
        out['active_packages'] = [
            {
                'name': (p.source_template.name if p.source_template else 'Package'),
                'remaining': getattr(p, 'remaining_sessions', None),
                'expires_at': p.expires_at.isoformat() if getattr(p, 'expires_at', None) else None,
            }
            for p in rows
        ]

    if 'active_membership' in requested:
        sub = (
            Subscription.objects
            .filter(tenant=tenant, customer=customer)
            .select_related('plan')
            .order_by('-id')
            .first()
        )
        out['active_membership'] = (
            {
                'plan': sub.plan.name if sub and sub.plan else None,
                'status': getattr(sub, 'status', None) if sub else None,
            }
            if sub else None
        )

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

    provider_id = tool_input.get('provider_id')
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
    while cur <= date_to and len(collected) < _MAX_SLOTS_RETURNED * 3:
        if len(providers) == 1:
            day_slots = [
                {
                    'start_iso': s.start.isoformat(),
                    'end_iso': s.end.isoformat(),
                    'provider_id': providers[0].id,
                }
                for s in compute_provider_slots(
                    provider=providers[0], service=service,
                    location=location, on_date=cur,
                )
                if s.available
            ]
        else:
            payloads = compute_any_provider_slots(
                eligible_providers=providers, service=service,
                location=location, on_date=cur,
            )
            day_slots = [
                {
                    'start_iso': p['start'],
                    'end_iso': p['end'],
                    'provider_id': p.get('provider_id'),
                }
                for p in payloads if p['available']
            ]
        for slot in day_slots:
            collected.append({
                **slot,
                'service_id': service.id,
                'location_id': location.id,
                'label': _human_label(slot['start_iso']),
            })
            if len(collected) >= _MAX_SLOTS_RETURNED:
                break
        if len(collected) >= _MAX_SLOTS_RETURNED:
            break
        cur += dt.timedelta(days=1)

    final = collected[:_MAX_SLOTS_RETURNED]

    # Auto-stamp pending_proposal so the digit fast-path works
    # WITHOUT requiring Claude to remember a second tool call.
    # The user's "1" / "2" / "3" reply maps to the SAME indices we
    # return here. Includes 24h TTL — long enough for the
    # customer to chew on it, short enough to avoid stale booking
    # races against staff edits to the calendar.
    if final:
        indexed = [
            {
                'index': i + 1,
                'start_iso': s['start_iso'],
                'end_iso': s['end_iso'],
                'provider_id': s.get('provider_id'),
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
    'check_availability': _tool_check_availability,
    'propose_slots': _tool_propose_slots,
    'confirm_booking': _tool_confirm_booking,
    'update_customer_profile': _tool_update_customer_profile,
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


def _human_label(start_iso: str) -> str:
    try:
        dt_obj = dt.datetime.fromisoformat(start_iso)
    except (TypeError, ValueError):
        return start_iso
    # E.g. "Tue Jun 3, 2:00pm"
    return dt_obj.strftime('%a %b %-d, %-I:%M%p').replace('AM', 'am').replace('PM', 'pm')
