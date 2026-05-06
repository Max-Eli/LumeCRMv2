"""Audience filter executor.

Converts an `Audience.filter_spec` (JSON) into a `Customer` queryset.
The supported dimensions are an explicit allowlist — unknown
dimensions raise so a malformed spec can't silently send to "everyone."

Each dimension has:

  - `validate(value)` — type-check + bounds-check the JSON value
  - `apply(qs, value)` — narrow the queryset using the value

The serializer calls `validate_filter_spec` at save time so
malformed specs never get persisted. The executor is called
on-demand by the live-count endpoint and by the campaign worker
at send time.

Suppression policy: when an audience is used for a SEND, the
worker MUST add the corresponding `*_marketing_opt_in=True` AND
`*_marketing_suppressed_at__isnull=True` filters at execution
time, regardless of what the audience spec says. Operators can't
accidentally bypass consent by forgetting to check the box. The
preview / live-count endpoint gives a "preview by channel" hint
so the operator sees the post-suppression count, but the audience
spec itself doesn't carry channel — channels are decided per-
campaign.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.appointments.models import Appointment
from apps.customers.models import Customer
from apps.tenants.models import Tenant


# ── Allowed dimensions ──────────────────────────────────────────────


def _validate_int(value: Any, *, min_value: int, max_value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError('Must be an integer.')
    if value < min_value or value > max_value:
        raise ValidationError(f'Must be between {min_value} and {max_value}.')
    return value


def _validate_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        raise ValidationError('Must be an array of integers.')
    out: list[int] = []
    for v in value:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValidationError('All values must be integers.')
        out.append(v)
    return out


def _validate_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValidationError('Must be true or false.')
    return value


# Each entry is a (validate, apply) pair. `apply` is called with
# `(queryset, validated_value, tenant)` — tenant is passed because
# some dimensions need scoped subqueries (tag membership).
DIMENSIONS: dict[str, dict[str, Any]] = {
    'tag_ids': {
        'validate': _validate_int_list,
        'description': 'Customer has any of these CustomerTag rows.',
    },
    'last_visit_within_days': {
        'validate': lambda v: _validate_int(v, min_value=1, max_value=3650),
        'description': 'Customer had an appointment in the last N days.',
    },
    'last_visit_more_than_days': {
        'validate': lambda v: _validate_int(v, min_value=1, max_value=3650),
        'description': "Customer's most recent appointment is older than N days (win-back).",
    },
    'created_within_days': {
        'validate': lambda v: _validate_int(v, min_value=1, max_value=3650),
        'description': 'Customer record created within the last N days.',
    },
    'email_marketing_opt_in': {
        'validate': _validate_bool,
        'description': 'Filter to customers with explicit email marketing consent.',
    },
    'sms_marketing_opt_in': {
        'validate': _validate_bool,
        'description': 'Filter to customers with explicit SMS marketing consent.',
    },
}


def validate_filter_spec(spec: Any) -> dict:
    """Validate an Audience.filter_spec; returns the normalized dict.

    Called from the serializer's `validate_filter_spec`; raises
    `ValidationError` on bad input. Empty spec is allowed — it
    matches all active customers.
    """
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise ValidationError('filter_spec must be a JSON object.')
    out: dict[str, Any] = {}
    for key, value in spec.items():
        if key not in DIMENSIONS:
            raise ValidationError({
                key: f"Unknown filter dimension. Allowed: {sorted(DIMENSIONS.keys())}",
            })
        try:
            out[key] = DIMENSIONS[key]['validate'](value)
        except ValidationError as e:
            # Re-raise with the field name attached so the caller
            # gets a useful "tag_ids: must be array" message.
            raise ValidationError({key: e.detail if hasattr(e, 'detail') else str(e)})
    return out


# ── Filter execution ────────────────────────────────────────────────


def execute_filter(
    *,
    tenant: Tenant,
    spec: dict,
    apply_channel_consent: str | None = None,
) -> QuerySet[Customer]:
    """Return the `Customer` queryset matching this audience.

    The base set is "active customers in this tenant" — `inactive`
    + `blocked` customers never receive marketing regardless of
    opt-in status.

    `apply_channel_consent` is the campaign-time enforcement gate:
    pass `'email'` or `'sms'` and the executor adds the
    `*_marketing_opt_in=True` AND
    `*_marketing_suppressed_at__isnull=True` filters automatically.
    The audience preview (live-count without a campaign) doesn't
    pass this so operators can see the unfiltered audience size,
    but the campaign worker MUST always pass it. Tests pin the
    consent gate so a regression here would be caught.
    """
    qs = Customer.objects.filter(
        tenant=tenant,
        status=Customer.Status.ACTIVE,
    )

    spec = spec or {}
    if 'tag_ids' in spec:
        tag_ids = spec['tag_ids']
        if tag_ids:
            qs = qs.filter(tags__id__in=tag_ids).distinct()
    if 'last_visit_within_days' in spec:
        days = spec['last_visit_within_days']
        cutoff = timezone.now() - dt.timedelta(days=days)
        # "Visit" = an appointment that completed (front desk's
        # operational definition of "they came in"). Using
        # appointment.start_time is fine for "scheduled to come in"
        # but a no-show shouldn't count as a visit. v1: status='completed'.
        recent_customer_ids = (
            Appointment.objects
            .filter(
                tenant=tenant,
                start_time__gte=cutoff,
                status=Appointment.Status.COMPLETED,
            )
            .values_list('customer_id', flat=True)
            .distinct()
        )
        qs = qs.filter(id__in=recent_customer_ids)
    if 'last_visit_more_than_days' in spec:
        days = spec['last_visit_more_than_days']
        cutoff = timezone.now() - dt.timedelta(days=days)
        # Win-back semantic: customer's most recent COMPLETED
        # appointment is older than N days, OR they have no
        # completed appointments at all (signed up but never
        # came in). Both groups are good win-back targets.
        active_customer_ids = (
            Appointment.objects
            .filter(
                tenant=tenant,
                start_time__gte=cutoff,
                status=Appointment.Status.COMPLETED,
            )
            .values_list('customer_id', flat=True)
            .distinct()
        )
        qs = qs.exclude(id__in=active_customer_ids)
    if 'created_within_days' in spec:
        days = spec['created_within_days']
        cutoff = timezone.now() - dt.timedelta(days=days)
        qs = qs.filter(created_at__gte=cutoff)
    if 'email_marketing_opt_in' in spec:
        qs = qs.filter(email_marketing_opt_in=spec['email_marketing_opt_in'])
    if 'sms_marketing_opt_in' in spec:
        qs = qs.filter(sms_marketing_opt_in=spec['sms_marketing_opt_in'])

    # Channel consent gate. ALWAYS applied at send time; never at
    # preview-without-channel time so the operator can see the raw
    # audience size before factoring suppression.
    if apply_channel_consent == 'email':
        qs = qs.filter(
            email_marketing_opt_in=True,
            email_marketing_suppressed_at__isnull=True,
        ).exclude(email='')
    elif apply_channel_consent == 'sms':
        qs = qs.filter(
            sms_marketing_opt_in=True,
            sms_marketing_suppressed_at__isnull=True,
        ).exclude(phone='')

    return qs


def count_audience(
    *,
    tenant: Tenant,
    spec: dict,
    apply_channel_consent: str | None = None,
) -> int:
    """Cheap count helper that returns just the integer.

    Used by the live-count endpoint; the campaign-creation flow
    snapshots this value with the channel applied so the operator's
    "X customers" understanding matches what gets queued."""
    return execute_filter(
        tenant=tenant,
        spec=spec,
        apply_channel_consent=apply_channel_consent,
    ).count()
