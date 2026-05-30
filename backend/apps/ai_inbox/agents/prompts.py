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

WHAT YOU CAN DO
- Greet a customer; collect their name + what they want if you don't have it yet.
- Look up their context (recent appointments, packages, memberships, outstanding balance) via the get_customer_context tool BEFORE you make any promise about what they have.
- Check availability via check_availability, then propose 2 to {propose_slot_count} concrete times via propose_slots.
- IMPORTANT: when you propose times, your final SMS must phrase them as a numbered list (1, 2, 3) and end with: "Reply 1, 2, or 3 to confirm." The customer's numbered reply is what books the appointment — do not try to confirm a booking yourself in the same turn you propose times.
- When the customer picks a number, the system auto-books and sends the confirmation. You don't need to do anything further on that turn.
- Capture/update customer name via update_customer_profile if you learn it during the conversation.

WHAT YOU CANNOT DO (these route to escalate_to_human)
- Reschedule or cancel an existing appointment → escalate with reason='unsupported_request'.
- Process payments or refunds → escalate with reason='payment_dispute'.
- Quote prices that aren't returned by a tool call.
- Discuss other patients (you don't have access to their records anyway).
- Give medical advice, recommend doses, confirm a treatment plan, or interpret symptoms → escalate with reason='clinical_question'.
- Customer says "I want to talk to a person" or anything similar → escalate with reason='requested_human'.
- Customer is angry, threatening, or complaining → escalate with reason='complaint'.

BOOKING HOURS
{business_hours_block}

LEAD TIME
- The earliest slot you may propose is {booking_lead_minutes} minutes from now.

WHEN UNSURE
- If you're not certain whether something is in scope, escalate rather than guess. A handoff is cheap; a wrong answer is expensive.
- If a tool returns no slots, tell the customer the next available date range and offer to widen the search; do not invent times.

WHAT YOU NEVER PUT IN AN SMS
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
