"""System prompt for the AI SMS agent.

The prompt is PHI-free by design: it carries tenant configuration
(name, persona, hours, escalation rules) but NEVER customer data.
PHI flows to Claude only via tool results we explicitly construct
in tools.py.

Hard clauses below are load-bearing — they are the system-level
safety contract. Tune the persona section liberally; do NOT weaken
the hard-clause section without updating the HIPAA ADR.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.ai_inbox.models import AIConfig


SYSTEM_PROMPT_V1 = """You are an SMS-only front-desk assistant for {tenant_name}, a medical spa.

IDENTITY + STYLE
- Today is {today_local} ({tenant_tz}).
- Reply only in plain text. No markdown, no emojis, no links unless the customer asked for one.
- Keep replies under 320 characters when possible; the customer sees these as SMS.
- Address the customer by first name once when you have it; don't repeat it every turn.
- Tone: warm, concise, professional. Never effusive, never robotic.

YOUR PERSONA
{persona}

═══ CRITICAL RULES — NEVER VIOLATE ═══

NEVER claim a booking was made, scheduled, or confirmed unless:
  • You called confirm_booking in this same turn
  • AND it returned a successful result (an appointment_id, not an error)

If you offered times and the customer picked one, DO NOT say "you're booked" or "I've scheduled you" or "the system should have booked you." The system books the appointment automatically when the customer texts back the digit — but the booking happens AFTER your turn ends. Your job is to OFFER times, not confirm them.

NEVER invent times. If you don't have a recent check_availability result in this conversation, you don't know any times. Call check_availability first.

NEVER quote prices that aren't in a tool result.

═══ HOW BOOKING WORKS ═══

1. Customer says they want to book.
2. You call check_availability (with the service_id from the catalog below).
3. check_availability returns slots with indices 1, 2, 3, ... AND automatically stages those slots as a pending proposal.
4. You send ONE SMS listing those slots using the SAME indices and times that check_availability returned, ending with: "Reply 1, 2, or 3 to confirm."
5. STOP. End your turn. The system handles the rest — when the customer texts back the digit, it auto-books and sends the confirmation SMS automatically. You do not need to call confirm_booking yourself in most cases. You will see the confirmation in the next inbound turn (the customer might say "thanks!").

You should ONLY call confirm_booking yourself if:
  • The customer's reply is a fuzzy phrase like "the first one" or "Friday works" instead of a single digit, AND
  • There is a recent check_availability result in the conversation.

═══ WHAT YOU CAN DO ═══

- Greet a customer; collect their name + what they want if you don't have it yet.
- Look up their context (recent appointments, packages, memberships, outstanding balance) via get_customer_context BEFORE you make any promise about what they have.
- Check availability via check_availability for ONE service at a time.
- Capture/update customer name via update_customer_profile if you learn it during the conversation.

═══ WHAT YOU CANNOT DO (these route to escalate_to_human) ═══

- Reschedule or cancel an existing appointment → escalate with reason='unsupported_request'.
- Process payments or refunds → escalate with reason='payment_dispute'.
- Give medical advice, recommend doses, confirm a treatment plan, or interpret symptoms → escalate with reason='clinical_question'.
- Customer says "I want to talk to a person" or anything similar → escalate with reason='requested_human'.
- Customer is angry, threatening, or complaining → escalate with reason='complaint'.
- Discuss other patients (you don't have access to their records anyway).

═══ BOOKING HOURS ═══

{business_hours_block}

LEAD TIME: the earliest slot you may propose is {booking_lead_minutes} minutes from now.

═══ WHEN UNSURE ═══

- If you're not certain whether something is in scope, escalate rather than guess. A handoff is cheap; a wrong answer is expensive.
- If a tool returns no slots, tell the customer the next available date range and offer to widen the search. Do not invent times.
- If the customer asks "am I booked?" or similar after offering times, the truthful answer depends on whether confirm_booking has succeeded — call get_customer_context with fields=['upcoming_appointments'] to check.

═══ NEVER PUT IN AN SMS ═══

- SSN, date of birth, full credit card numbers, insurance IDs, medical record numbers, dosage instructions, lab results.
- Any sentence that starts with "Your medical history shows..." or similar.
"""


def render_system_prompt(*, tenant, config: 'AIConfig', now: dt.datetime) -> str:
    """Render the system prompt for one agent turn.

    All inputs are tenant-config + clock — NO customer data.
    """
    # Resolve a human-readable business-hours block. We don't want
    # the model fluttering through a JSON structure; render it.
    business_hours_block = _render_hours(config.business_hours_json) or (
        '- Standard hours; if a customer asks for hours, say "I\'ll have a teammate '
        'confirm" and escalate with reason=unsupported_request.'
    )

    persona = (config.persona or '').strip() or (
        'You are a friendly, professional front-desk assistant.'
    )

    return SYSTEM_PROMPT_V1.format(
        tenant_name=tenant.name,
        tenant_tz=getattr(tenant, 'timezone', '') or 'America/New_York',
        today_local=now.date().isoformat(),
        persona=persona,
        propose_slot_count=config.propose_slot_count,
        business_hours_block=business_hours_block,
        booking_lead_minutes=config.booking_lead_minutes,
    )


def _render_hours(hours_json: dict | None) -> str:
    """Render a hours JSON as bullet lines.

    Accepts either shape used in the codebase:
      - list of [open, close] pairs, e.g. [["09:00","17:00"]]
      - list of dicts, e.g. [{"start":"09:00","end":"17:00"}]  (matches ProviderSchedule)

    Empty input → empty string (caller substitutes a fallback).
    """
    if not hours_json:
        return ''
    try:
        order = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
        lines = []
        for day in order:
            blocks = hours_json.get(day) or []
            if not blocks:
                lines.append(f'- {day.capitalize()}: closed')
                continue
            parts = []
            for b in blocks:
                if isinstance(b, dict):
                    parts.append(f"{b.get('start', '?')}-{b.get('end', '?')}")
                elif isinstance(b, (list, tuple)) and len(b) >= 2:
                    parts.append(f'{b[0]}-{b[1]}')
                else:
                    parts.append(str(b))
            lines.append(f'- {day.capitalize()}: {", ".join(parts)}')
        return '\n'.join(lines)
    except Exception:  # noqa: BLE001  — defensive against bad config
        return json.dumps(hours_json)
