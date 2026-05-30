"""PHI / PII redaction for audit-log payloads + outbound safety scan.

Two consumers:

  - ``scrub_for_log(obj)`` — walks dicts/lists/strings and replaces
    high-risk PII patterns with REDACTED tokens before persisting
    to AuditLog or AIToolCall.input/output_json. The PHI of record
    stays on ``messaging.Message.body`` — these logs are intentionally
    PHI-free so they can be paged into ops dashboards without
    additional access control.

  - ``outbound_pii_check(text)`` — pre-send scan of an AI-authored
    SMS body. Detects sequences that look like SSN / DOB / payment
    card numbers. A positive match BLOCKS the send and escalates
    with ``reason='safety_outbound_blocked'``. False positives lean
    toward over-blocking (safer to escalate than to leak).

Regexes are intentionally conservative — they're not a substitute
for a proper DLP pipeline, but they catch the obvious cases. v2
could add a named-entity recognizer for higher precision.
"""

from __future__ import annotations

import re
from typing import Any

# US-format SSN, with or without dashes
_SSN_RE = re.compile(r'\b\d{3}[- ]?\d{2}[- ]?\d{4}\b')

# Credit-card-like: 13-19 digit run, optionally space/dash separated
_CARD_RE = re.compile(r'\b(?:\d[ -]?){13,19}\b')

# Phone-number-like (US): (xxx) xxx-xxxx / xxx-xxx-xxxx / 10 digits
_PHONE_RE = re.compile(r'\b(?:\+?1[- .]?)?\(?\d{3}\)?[- .]?\d{3}[- .]?\d{4}\b')

# Email
_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')

# DOB-ish: 4 digit year + 2 + 2, or M/D/YYYY, or M-D-YYYY
_DOB_RE = re.compile(
    r'\b(?:'
    r'(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}'
    r'|'
    r'(?:19|20)\d{2}[/-](?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])'
    r')\b'
)


def scrub_for_log(obj: Any) -> Any:
    """Walk a JSON-shaped object and return a scrubbed copy.

    Strings are regex-redacted; dicts + lists recursed. Other types
    (ints, bools, None) returned as-is. Safe to call on any value
    we'd serialize to JSONField.
    """
    if isinstance(obj, str):
        return _scrub_string(obj)
    if isinstance(obj, dict):
        return {k: scrub_for_log(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_for_log(v) for v in obj]
    return obj


def _scrub_string(s: str) -> str:
    s = _SSN_RE.sub('[REDACTED:SSN]', s)
    s = _CARD_RE.sub('[REDACTED:CARD]', s)
    s = _DOB_RE.sub('[REDACTED:DOB]', s)
    s = _EMAIL_RE.sub('[REDACTED:EMAIL]', s)
    s = _PHONE_RE.sub('[REDACTED:PHONE]', s)
    return s


def outbound_pii_check(body: str) -> str | None:
    """Return a short reason string if the body looks unsafe to send; None if safe.

    The AI should never produce SSN / DOB / card numbers in an SMS;
    if one slips out (prompt injection, model error), this check
    blocks the send and the agent escalates. The phone/email regexes
    are intentionally NOT applied here — those are valid in an SMS
    (e.g. "your provider's email is ...").
    """
    if _SSN_RE.search(body):
        return 'ssn_detected'
    if _CARD_RE.search(body):
        return 'card_detected'
    if _DOB_RE.search(body):
        return 'dob_detected'
    return None
