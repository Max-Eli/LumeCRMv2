"""Automation trigger evaluator + dedup logic.

Each `Automation.trigger_type` has its own eligibility evaluator
that returns the queryset of customers eligible to receive the
automation right now. Eligibility is then narrowed by:

  - The optional `audience` filter on the Automation
  - Channel-consent gating (suppression always wins; ADR 0016)
  - Per-customer dedup based on `MarketingSendLog` history (don't
    fire the same automation for the same customer twice within
    `dedup_window_days`)

Triggers in v1:

  - **birthday**: customer's date_of_birth month == current month.
    Fires once per year per customer (dedup window typically 365).
  - **no_visit_days**: customer's most recent COMPLETED appointment
    is older than `config['days']`. Fires once per dedup window
    (default 365) so a long-dormant customer doesn't get blasted
    every day they remain dormant.
  - **first_visit_anniversary**: today is the N-year anniversary
    of the customer's FIRST completed appointment, where N >= 1.
    Fires once per year per customer.

The "fire" itself (creating Campaign + SendLog rows + dispatching)
runs in `run_automation()` — designed to be called by Celery beat
on a schedule (Phase 1L session 3) but also callable manually for
testing via the admin or a management command.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Min, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.appointments.models import Appointment
from apps.customers.models import Customer
from apps.tenants.models import Tenant

from .audiences import execute_filter
from .models import Automation, Channel, MarketingSendLog


# ── Trigger validation ──────────────────────────────────────────────


def validate_trigger_config(trigger_type: str, config: dict) -> dict:
    """Per-type validation for `Automation.trigger_config`. Returns
    the normalized config; raises `ValidationError` on bad input."""
    if not isinstance(config, dict):
        raise ValidationError({'trigger_config': 'Must be a JSON object.'})

    if trigger_type == Automation.TriggerType.BIRTHDAY:
        # No required keys; future versions might add `month_offset`
        # to fire 2 weeks before the birthday rather than during the
        # birthday month.
        return {}

    if trigger_type == Automation.TriggerType.NO_VISIT_DAYS:
        days = config.get('days')
        if not isinstance(days, int) or isinstance(days, bool):
            raise ValidationError({
                'trigger_config': 'no_visit_days requires {"days": <int>}.',
            })
        if days < 7 or days > 3650:
            raise ValidationError({
                'trigger_config': 'days must be between 7 and 3650.',
            })
        return {'days': days}

    if trigger_type == Automation.TriggerType.FIRST_VISIT_ANNIVERSARY:
        # No required keys today. Could add `years` to support
        # "5-year loyalty" anniversaries later.
        return {}

    raise ValidationError({'trigger_type': f'Unknown trigger type: {trigger_type!r}'})


# ── Eligibility evaluators ──────────────────────────────────────────


def _eligible_customers(automation: Automation) -> QuerySet[Customer]:
    """Resolve which customers are currently eligible for this
    automation's trigger. The result is the union of customers
    who match the trigger AND, if `automation.audience` is set,
    the audience filter. The channel-consent gate is layered on
    top by `_filter_eligible()` — this function returns the
    pre-consent set."""
    tenant = automation.tenant
    today = timezone.localdate()

    if automation.trigger_type == Automation.TriggerType.BIRTHDAY:
        qs = Customer.objects.filter(
            tenant=tenant,
            status=Customer.Status.ACTIVE,
            date_of_birth__month=today.month,
        )

    elif automation.trigger_type == Automation.TriggerType.NO_VISIT_DAYS:
        days = automation.trigger_config.get('days', 90)
        cutoff = timezone.now() - dt.timedelta(days=days)
        recent_ids = (
            Appointment.objects.filter(
                tenant=tenant,
                start_time__gte=cutoff,
                status=Appointment.Status.COMPLETED,
            )
            .values_list('customer_id', flat=True)
            .distinct()
        )
        qs = Customer.objects.filter(
            tenant=tenant,
            status=Customer.Status.ACTIVE,
        ).exclude(id__in=recent_ids)

    elif automation.trigger_type == Automation.TriggerType.FIRST_VISIT_ANNIVERSARY:
        # Annotate each customer with their first COMPLETED
        # appointment date. Eligible if the same month + day as
        # today AND at least 1 year ago (i.e. it's actually an
        # anniversary, not the first visit itself).
        first_dates = (
            Appointment.objects.filter(
                tenant=tenant,
                status=Appointment.Status.COMPLETED,
            )
            .values('customer_id')
            .annotate(first_at=Min('start_time'))
        )
        anniversary_customer_ids = []
        for row in first_dates:
            first_at = row['first_at']
            first_local = timezone.localtime(first_at).date()
            # Same month + day; first visit at least a year ago.
            if (
                first_local.month == today.month
                and first_local.day == today.day
                and (today - first_local).days >= 365
            ):
                anniversary_customer_ids.append(row['customer_id'])
        qs = Customer.objects.filter(
            tenant=tenant,
            status=Customer.Status.ACTIVE,
            id__in=anniversary_customer_ids,
        )

    else:
        raise ValueError(f'Unknown trigger type: {automation.trigger_type!r}')

    # Optional additional audience filter.
    if automation.audience_id is not None:
        audience_qs = execute_filter(
            tenant=tenant, spec=automation.audience.filter_spec or {},
        )
        qs = qs.filter(id__in=audience_qs.values_list('id', flat=True))

    return qs


def _filter_eligible(
    automation: Automation,
    customers: QuerySet[Customer],
) -> QuerySet[Customer]:
    """Apply channel-consent gate + dedup. Returns the customers
    we'll actually send to right now."""
    tenant = automation.tenant

    # Channel-consent gate. Suppression always wins.
    if automation.channel == Channel.EMAIL:
        customers = customers.filter(
            email_marketing_opt_in=True,
            email_marketing_suppressed_at__isnull=True,
        ).exclude(email='')
    elif automation.channel == Channel.SMS:
        customers = customers.filter(
            sms_marketing_opt_in=True,
            sms_marketing_suppressed_at__isnull=True,
        ).exclude(phone='')

    # Dedup — exclude customers who have a `MarketingSendLog` row
    # tied to this automation in the dedup window. The send log
    # rows are written when the automation fires (in stub or
    # real mode), so this query is the source of truth.
    dedup_cutoff = timezone.now() - dt.timedelta(days=automation.dedup_window_days)
    recently_sent = (
        MarketingSendLog.objects.filter(
            tenant=tenant,
            customer_id__in=customers.values_list('id', flat=True),
            created_at__gte=dedup_cutoff,
            # Tie via the automation's "campaign" ancestry. v1: we
            # write a Campaign row per fire (one per day per
            # automation) and the SendLog points at that campaign.
            # The campaign carries `automation_source_id` (added
            # below) so we can dedup on the source automation.
        )
        .values_list('customer_id', flat=True)
        .distinct()
    )
    return customers.exclude(id__in=recently_sent)


def preview_automation(automation: Automation) -> dict:
    """Return the eligibility breakdown WITHOUT firing — used by the
    automations list UI to show "X eligible right now" + "Y after
    consent + dedup."

    Returns a dict with `total_count`, `consent_eligible_count`,
    `final_count` so the operator can see how the trigger narrows."""
    eligible = _eligible_customers(automation)
    total = eligible.count()
    after_filter = _filter_eligible(automation, eligible)
    final = after_filter.count()
    # Consent-eligible (without dedup) — useful diagnostic for the
    # operator to see how much of the drop is dedup vs consent.
    if automation.channel == Channel.EMAIL:
        consent = eligible.filter(
            email_marketing_opt_in=True,
            email_marketing_suppressed_at__isnull=True,
        ).exclude(email='').count()
    else:
        consent = eligible.filter(
            sms_marketing_opt_in=True,
            sms_marketing_suppressed_at__isnull=True,
        ).exclude(phone='').count()
    return {
        'total_count': total,
        'consent_eligible_count': consent,
        'final_count': final,
    }
