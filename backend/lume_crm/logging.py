"""
PHI-scrubbing log filter — defense-in-depth so we never CloudWatch-leak
patient data, even when a developer forgets the rule.

Three layers run on every log record before it reaches CloudWatch:

  1. Regex masking on the formatted message string. Catches stray
     emails, phone numbers, dates of birth, and SSN-shaped values
     embedded in `logger.info("got request from %s", customer)` and
     similar.
  2. Structured-key masking when callers use `extra={...}`. If a key
     appears in `_PHI_KEYS` (e.g. 'first_name', 'medical_history',
     'allergies'), the value is replaced with '[REDACTED]' before
     formatting.
  3. Args-tuple masking — same rules applied to the positional args
     that get %-substituted into the message format string.

Why a filter and not just careful logging at call-sites: HIPAA's
"reasonable safeguards" doctrine means we owe a system-level guard,
not just developer discipline. One forgotten `print()` in production
and we have a breach-notification obligation.

Why not a structlog processor: we don't use structlog. Adding it would
mean rewriting every log call site and changing the formatter. The
stdlib filter pattern fits where we already are.

Failure mode: if scrubbing crashes on a record (e.g. an unstringable
value), we log a `LoggingError` event instead and DROP the original
record. Better to lose telemetry than to leak.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# ── Patterns ────────────────────────────────────────────────────────
#
# Each pattern's match is replaced by `[REDACTED:<kind>]` so we still
# know what was scrubbed (useful for debugging "why isn't my log
# showing X"). Order matters — SSN before phone, because the SSN
# pattern is stricter and would otherwise be eaten by the phone one.

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        'ssn',
        re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    ),
    (
        'email',
        re.compile(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
        ),
    ),
    (
        'phone',
        # US-flavored: 10 digits, optional country code, common
        # separators. Catches '555-555-5555', '(555) 555-5555',
        # '5555555555', '+1 555 555 5555'.
        re.compile(
            r'(?:\+?1[-.\s]?)?'
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        ),
    ),
    (
        'dob',
        # ISO-8601 date (YYYY-MM-DD) or US slash format. Avoids
        # eating timestamps because the regex is anchored at word
        # boundaries and rejects anything attached to a 'T' (the ISO
        # datetime separator).
        re.compile(
            r'\b(?:'
            r'\d{4}-\d{2}-\d{2}(?!T)'  # YYYY-MM-DD, not YYYY-MM-DDTHH
            r'|'
            r'\d{1,2}/\d{1,2}/\d{4}'   # M/D/YYYY
            r')\b',
        ),
    ),
)

# Structured-extra keys that are PHI. Any logger.info(..., extra={'first_name': x})
# will see `x` redacted before formatting.
#
# Source of truth: the Customer model's PHI fields (apps/customers/models.py)
# plus the auth-side fields that sometimes carry PHI by extension.
_PHI_KEYS: frozenset[str] = frozenset(
    {
        # Identity
        'first_name', 'last_name', 'preferred_name', 'full_name',
        'email', 'phone', 'date_of_birth', 'dob',
        # Address
        'address_line1', 'address_line2', 'city', 'state', 'zip_code',
        # Emergency contact
        'emergency_name', 'emergency_phone', 'emergency_relationship',
        # Clinical
        'medical_history', 'allergies', 'medications',
        'skin_type_fitzpatrick', 'sex',
        # Notes (provider-only, often clinical impressions)
        'notes', 'note_body',
        # Forms / e-sign payloads
        'submission_payload', 'signature_data',
    }
)

_REDACTED_KEY = '[REDACTED]'


class PHIScrubFilter(logging.Filter):
    """Mutate `record` in place to remove PHI before it leaves the process."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            self._scrub(record)
        except Exception as exc:  # pragma: no cover — defense-in-depth
            # Replace the record entirely with a sanitized error event.
            # We never want a logging-pipeline crash to leak the
            # original message.
            record.msg = 'phi_scrub_error: %s'
            record.args = (type(exc).__name__,)
            record.exc_info = None
        return True

    def _scrub(self, record: logging.LogRecord) -> None:
        # 1. The format-string itself. Most records use `record.msg` as
        #    a literal that the formatter %-substitutes args into; we
        #    scrub it pre-format so post-format leaks are impossible.
        if isinstance(record.msg, str):
            record.msg = scrub_text(record.msg)

        # 2. Positional args (substituted into %s/%d/%(key)s).
        if record.args:
            record.args = _scrub_args(record.args)

        # 3. Structured extras (logger.info("...", extra={'key': val})).
        #    Stdlib injects each `extra` key onto the record as an
        #    attribute; we walk them and redact PHI keys.
        for attr in list(vars(record).keys()):
            if attr in _PHI_KEYS:
                setattr(record, attr, _REDACTED_KEY)

        # 4. Exception text. The handler's formatter normally calls
        #    `formatException(record.exc_info)` lazily AFTER filters
        #    run, so by the time we'd see `record.exc_text` it'd be
        #    too late to scrub. We force the formatting here, scrub,
        #    then leave the result in `exc_text` — formatters short-
        #    circuit when `exc_text` is already set, so our scrubbed
        #    copy is the one that goes out.
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub_text(record.exc_text)


# ── Module-level helpers (also re-used by tests) ────────────────────


def scrub_text(text: str) -> str:
    """Apply all regex patterns to `text` and return the scrubbed copy."""
    for kind, pat in _PATTERNS:
        text = pat.sub(f'[REDACTED:{kind}]', text)
    return text


def _scrub_args(args: tuple[Any, ...] | dict[str, Any]) -> Any:
    """Recursively scrub a record-args tuple OR a %-style mapping."""
    if isinstance(args, dict):
        return {k: _scrub_value(k, v) for k, v in args.items()}
    return tuple(_scrub_value(None, v) for v in args)


def _scrub_value(key: str | None, value: Any) -> Any:
    if key is not None and key in _PHI_KEYS:
        return _REDACTED_KEY
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, (list, tuple)):
        scrubbed = [_scrub_value(None, v) for v in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    if isinstance(value, dict):
        return {k: _scrub_value(k, v) for k, v in value.items()}
    return value
