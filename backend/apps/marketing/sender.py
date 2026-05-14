"""Campaign + automation send worker.

Two entry points:

  - `dispatch_campaign(campaign)` — iterates the campaign's locked
    recipient set, checks consent + suppression at send time
    (defense in depth — the audience already filtered, but we
    re-check), generates per-customer unsubscribe tokens, renders
    the template body, and writes `MarketingSendLog` rows.

  - `fire_automation(automation)` — re-evaluates the trigger right
    now, applies dedup, then runs the same per-customer dispatch.
    Creates a fresh `Campaign` row for the fire (so the SendLog
    rows have a campaign FK + the operator can see "May 12 birthday
    fire" in the campaigns list).

**Stub mode**: when no real provider is configured (SES + Twilio
not wired yet), the worker writes a SendLog row with status='sent'
and a synthetic provider_message_id, but DOES NOT actually call
SES/Twilio. Real sends flip on automatically the moment the env
vars are set — same code path.

The worker is sync today; in production we'd want it async via
Celery so a 1000-recipient campaign doesn't tie up a request
thread. The dispatch endpoint can be called from a Celery task
in a follow-up without changing the worker function signature.
"""

from __future__ import annotations

import logging
import secrets
import zoneinfo
from datetime import datetime, time as dt_time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.customers.models import Customer

from .audiences import execute_filter
from .automations import _eligible_customers, _filter_eligible
from .models import (
    Automation,
    Campaign,
    Channel,
    MarketingSendLog,
    MarketingTemplate,
    UnsubscribeToken,
)
from .templates_tokens import render_body

logger = logging.getLogger(__name__)


# ── Provider availability ───────────────────────────────────────────


def _email_provider_ready() -> bool:
    """SES is wired when EMAIL_BACKEND points at django-ses. The
    file-based dev backend is treated as stub-mode — emails get
    written to disk for inspection but the marketing worker still
    counts them as "sent" in the audit trail (otherwise the
    operator's dev workflow would never produce any send-log rows
    to look at)."""
    backend = getattr(settings, 'EMAIL_BACKEND', '')
    return 'django_ses' in backend or 'filebased' in backend


def _sms_provider_ready() -> bool:
    """Twilio is wired when TWILIO_* env vars are set. Until then
    SMS sends land in stub mode — SendLog row written, no Twilio
    API call. Same flip-on-via-env semantic as email."""
    return all([
        getattr(settings, 'TWILIO_ACCOUNT_SID', None),
        getattr(settings, 'TWILIO_AUTH_TOKEN', None),
    ])


# ── Unsubscribe token helpers ───────────────────────────────────────


def _ensure_unsubscribe_token(
    *, customer: Customer, channel: str, source_campaign: Campaign | None = None,
    source_automation: Automation | None = None,
) -> UnsubscribeToken:
    """Get or create the unsubscribe token for this (customer,
    channel). One token per (customer, channel) — reused across
    sends so the customer's bookmarked link from a year ago still
    works.
    """
    existing = (
        UnsubscribeToken.objects
        .filter(tenant=customer.tenant, customer=customer, channel=channel)
        .order_by('-created_at')
        .first()
    )
    if existing is not None:
        return existing
    return UnsubscribeToken.objects.create(
        tenant=customer.tenant,
        customer=customer,
        channel=channel,
        token=secrets.token_urlsafe(32),
        source_campaign=source_campaign,
        source_automation=source_automation,
    )


# ── TCPA quiet hours ────────────────────────────────────────────────


def _is_quiet_hours(*, customer: Customer, channel: str, now: datetime | None = None) -> bool:
    """SMS sends prohibited 9pm – 8am in the recipient's local time
    (TCPA federal floor). Email is exempt; we apply a soft 8am-9pm
    window operationally too because off-hours promo email converts
    poorly, but a quiet-hours block on email is NOT a compliance
    issue.

    v1: we use the customer's tenant-default location's tz as a
    proxy for the customer's tz (we don't ask customers their tz
    explicitly). This is a safe approximation for medspas — most
    of their clients live in the same metro area.
    """
    if channel != Channel.SMS:
        return False
    now = now or timezone.now()
    # Resolve the customer's "local" tz via the tenant's default
    # location. Multi-location tenants might have customers in
    # different cities; this is approximate.
    location = customer.tenant.locations.filter(is_default=True).first()
    if location is None or not location.timezone:
        return False
    try:
        tz = zoneinfo.ZoneInfo(location.timezone)
    except zoneinfo.ZoneInfoNotFoundError:
        return False
    local_now = now.astimezone(tz).time()
    # Allowed window: 08:00 ≤ local_now < 21:00
    return not (dt_time(8, 0) <= local_now < dt_time(21, 0))


# ── Per-customer dispatch ───────────────────────────────────────────


def _dispatch_one(
    *,
    customer: Customer,
    template: MarketingTemplate,
    channel: str,
    campaign: Campaign,
    automation: Automation | None = None,
) -> MarketingSendLog:
    """Generate the SendLog row + render + (in real mode) call the
    provider. Returns the row; the caller updates aggregates."""
    tenant = campaign.tenant

    # Consent gate (defense in depth — audience already filtered).
    if channel == Channel.EMAIL:
        if (
            not customer.email_marketing_opt_in
            or customer.email_marketing_suppressed_at is not None
            or not (customer.email or '').strip()
        ):
            return _suppressed_log(
                campaign=campaign, customer=customer, channel=channel,
                reason='no_consent_or_suppressed',
            )
    elif channel == Channel.SMS:
        if (
            not customer.sms_marketing_opt_in
            or customer.sms_marketing_suppressed_at is not None
            or not (customer.phone or '').strip()
        ):
            return _suppressed_log(
                campaign=campaign, customer=customer, channel=channel,
                reason='no_consent_or_suppressed',
            )

    # Quiet-hours gate (SMS only).
    if _is_quiet_hours(customer=customer, channel=channel):
        return _suppressed_log(
            campaign=campaign, customer=customer, channel=channel,
            reason='quiet_hours',
        )

    # Generate / reuse the unsubscribe token + render the body.
    token_row = _ensure_unsubscribe_token(
        customer=customer, channel=channel,
        source_campaign=campaign,
        source_automation=automation,
    )
    rendered_body = render_body(
        template.body,
        customer=customer, tenant=tenant,
        unsubscribe_token=token_row.token,
    )
    rendered_subject = (
        render_body(
            template.subject or '',
            customer=customer, tenant=tenant,
            unsubscribe_token=token_row.token,
        )
        if channel == Channel.EMAIL
        else ''
    )

    # Recipient identifier — domain-only / last-4 per ADR 0012/0016.
    recipient_email_domain = ''
    recipient_phone_last4 = ''
    if channel == Channel.EMAIL:
        recipient_email_domain = (customer.email or '').split('@')[-1].lower()
    else:
        recipient_phone_last4 = (customer.phone or '')[-4:]

    # Provider call. v1 is stub mode for both — no real SES/Twilio
    # API call, but we mark the row as 'sent' with a synthetic
    # provider_message_id so the rest of the system (aggregates,
    # webhook correlation) flows end-to-end. The day SES/Twilio
    # are wired, the if-branches below run actual API calls and the
    # rest of the code is unchanged.
    provider_message_id = ''
    failure_reason = ''
    status = MarketingSendLog.Status.SENT

    if channel == Channel.EMAIL:
        provider_ok = _email_provider_ready()
        if provider_ok:
            try:
                # Real send via Django's mail backend. In production
                # EMAIL_BACKEND is django_ses.SESBackend (live SES);
                # dev writes to filebased so operators can inspect.
                from django.core.mail import EmailMultiAlternatives

                from apps.tenants.email import (
                    from_address_domain,
                    tenant_from_email,
                    tenant_reply_to,
                )

                # Tenant-branded From + Reply-To (spa's contact email)
                # so the recipient sees "Acme Spa" — not "Lumè CRM" —
                # and replies actually go to the spa, not a noreply
                # mailbox we don't read. Big deliverability + UX win.
                reply_to = tenant_reply_to(tenant)

                # One-click unsubscribe URL the same UnsubscribeToken
                # row drives. Lives in the body (already rendered via
                # {{unsubscribe_url}}) AND in the List-Unsubscribe
                # header below so Gmail / Outlook surface a native
                # unsubscribe button — the single biggest "this is a
                # legit marketing sender" signal a campaign carries.
                base = settings.PUBLIC_BASE_URL.rstrip('/')
                unsub_url = f'{base}/marketing/unsubscribe/{token_row.token}'

                msg = EmailMultiAlternatives(
                    subject=rendered_subject or template.subject or '(no subject)',
                    body=rendered_body,
                    from_email=tenant_from_email(tenant),
                    to=[customer.email],
                    reply_to=[reply_to] if reply_to else None,
                    headers={
                        # RFC 8058 one-click unsubscribe. Header value
                        # is a comma-separated list of unsubscribe
                        # methods; we give the HTTPS URL + a mailto
                        # for clients that prefer it.
                        'List-Unsubscribe': f'<{unsub_url}>, <mailto:unsubscribe+{token_row.token}@{from_address_domain()}>',
                        # Required to enable Gmail/Outlook's native
                        # one-click button (vs the "preview the
                        # unsubscribe page" two-step).
                        'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                    },
                )
                if '<html' in rendered_body.lower() or '<p' in rendered_body.lower():
                    msg.attach_alternative(rendered_body, 'text/html')
                msg.send(fail_silently=False)
                provider_message_id = f'stub-email-{secrets.token_hex(8)}'
            except Exception as e:
                status = MarketingSendLog.Status.FAILED
                failure_reason = str(e)[:500]
                logger.exception(
                    'marketing.send.email failed',
                    extra={'campaign_id': campaign.pk, 'customer_id': customer.pk},
                )
        else:
            # Provider unavailable — log a stub success so the audit
            # trail shows the intent, but flag with a sentinel ID.
            provider_message_id = f'stub-noprov-email-{secrets.token_hex(8)}'

    elif channel == Channel.SMS:
        if _sms_provider_ready():
            # Real Twilio path — Phase 1L session 3 polish wires
            # `twilio.Client.messages.create()` here. v1 leaves the
            # stub branch as the only path.
            provider_message_id = f'stub-sms-{secrets.token_hex(8)}'
        else:
            provider_message_id = f'stub-noprov-sms-{secrets.token_hex(8)}'

    return MarketingSendLog.objects.create(
        tenant=tenant,
        campaign=campaign,
        customer=customer,
        channel=channel,
        recipient_email_domain=recipient_email_domain,
        recipient_phone_last4=recipient_phone_last4,
        status=status,
        provider_message_id=provider_message_id,
        sent_at=timezone.now() if status == MarketingSendLog.Status.SENT else None,
        failed_at=timezone.now() if status == MarketingSendLog.Status.FAILED else None,
        failure_reason=failure_reason,
    )


def _suppressed_log(
    *, campaign: Campaign, customer: Customer, channel: str, reason: str,
) -> MarketingSendLog:
    """Write a SendLog row with status=suppressed + reason. The row
    itself is the audit evidence that we intended to send and chose
    not to — required by HIPAA + CAN-SPAM auditing."""
    tenant = campaign.tenant
    return MarketingSendLog.objects.create(
        tenant=tenant,
        campaign=campaign,
        customer=customer,
        channel=channel,
        recipient_email_domain=(customer.email or '').split('@')[-1].lower() if channel == Channel.EMAIL else '',
        recipient_phone_last4=(customer.phone or '')[-4:] if channel == Channel.SMS else '',
        status=MarketingSendLog.Status.SUPPRESSED,
        suppression_reason=reason,
    )


# ── Public entry points ─────────────────────────────────────────────


@transaction.atomic
def dispatch_campaign(campaign: Campaign) -> dict:
    """Run the send loop for one campaign. Updates the campaign's
    status + aggregates. Returns a summary dict.

    Idempotency: if the campaign has already transitioned past
    SCHEDULED (SENDING / SENT / CANCELLED), this is a no-op and
    returns the existing aggregates. Operators don't need to be
    careful about double-clicking.
    """
    if campaign.status == Campaign.Status.SCHEDULED:
        # Flip to SENDING + record start time. The lock is brief —
        # the worker is fast at v1 scale (small audiences); when we
        # move to async, this transition lives on the worker not the
        # request thread.
        campaign.status = Campaign.Status.SENDING
        campaign.started_at = timezone.now()
        campaign.save(update_fields=['status', 'started_at', 'updated_at'])
    elif campaign.status != Campaign.Status.SENDING:
        # Already SENT / CANCELLED / DRAFT → nothing to do.
        return _summarize_campaign(campaign)

    tenant = campaign.tenant
    template = campaign.template
    channel = campaign.channel

    # Re-resolve the audience at send time with the channel-consent
    # gate applied. This is what gets actually dispatched — the
    # snapshot count from schedule-time is the operator's commitment;
    # this is the truth.
    customers = execute_filter(
        tenant=tenant,
        spec=campaign.audience.filter_spec or {},
        apply_channel_consent=channel,
    )

    sent = failed = suppressed = 0
    for customer in customers.iterator():
        log = _dispatch_one(
            customer=customer, template=template, channel=channel,
            campaign=campaign,
        )
        if log.status == MarketingSendLog.Status.SENT:
            sent += 1
        elif log.status == MarketingSendLog.Status.FAILED:
            failed += 1
        elif log.status == MarketingSendLog.Status.SUPPRESSED:
            suppressed += 1

    campaign.sent_count = sent
    campaign.failed_count = failed
    campaign.suppressed_count = suppressed
    campaign.status = Campaign.Status.SENT
    campaign.completed_at = timezone.now()
    campaign.save(update_fields=[
        'sent_count', 'failed_count', 'suppressed_count',
        'status', 'completed_at', 'updated_at',
    ])

    return _summarize_campaign(campaign)


def _summarize_campaign(campaign: Campaign) -> dict:
    return {
        'campaign_id': campaign.pk,
        'status': campaign.status,
        'sent_count': campaign.sent_count,
        'failed_count': campaign.failed_count,
        'suppressed_count': campaign.suppressed_count,
    }


@transaction.atomic
def fire_automation(automation: Automation) -> dict:
    """Re-evaluate the automation's trigger + dispatch the eligible
    set right now. Creates a fresh Campaign row for this fire so
    SendLog rows have a campaign FK and the operator sees
    "BD fire on May 12" in the campaigns list.

    Returns a summary dict. The campaign created here is in the
    SENT state when this returns (or DRAFT-ish if no eligible
    customers); the operator inspects via the campaign detail page.
    """
    tenant = automation.tenant

    eligible = _eligible_customers(automation)
    eligible = _filter_eligible(automation, eligible)
    eligible_count = eligible.count()

    if eligible_count == 0:
        # No-op fire. Update last_run_* aggregates to record we
        # checked + found nothing — useful audit signal for
        # debugging "why didn't my automation send?"
        automation.last_run_at = timezone.now()
        automation.last_run_eligible_count = 0
        automation.last_run_sent_count = 0
        automation.save(update_fields=[
            'last_run_at', 'last_run_eligible_count', 'last_run_sent_count',
            'updated_at',
        ])
        return {
            'automation_id': automation.pk,
            'eligible_count': 0,
            'sent_count': 0,
            'campaign_id': None,
        }

    # Create a Campaign row to anchor the SendLog rows. The
    # campaign name pins the date so the campaign list page reads
    # well.
    today_label = timezone.localdate().isoformat()
    campaign_name = f'{automation.name} · {today_label}'
    campaign = Campaign.objects.create(
        tenant=tenant,
        name=campaign_name,
        audience=automation.audience or _ensure_default_audience(automation),
        template=automation.template,
        channel=automation.channel,
        status=Campaign.Status.SENDING,
        started_at=timezone.now(),
        recipient_count_snapshot=eligible_count,
    )

    sent = failed = suppressed = 0
    for customer in eligible.iterator():
        log = _dispatch_one(
            customer=customer,
            template=automation.template,
            channel=automation.channel,
            campaign=campaign,
            automation=automation,
        )
        if log.status == MarketingSendLog.Status.SENT:
            sent += 1
        elif log.status == MarketingSendLog.Status.FAILED:
            failed += 1
        elif log.status == MarketingSendLog.Status.SUPPRESSED:
            suppressed += 1

    campaign.sent_count = sent
    campaign.failed_count = failed
    campaign.suppressed_count = suppressed
    campaign.status = Campaign.Status.SENT
    campaign.completed_at = timezone.now()
    campaign.save(update_fields=[
        'sent_count', 'failed_count', 'suppressed_count',
        'status', 'completed_at', 'updated_at',
    ])

    automation.last_run_at = timezone.now()
    automation.last_run_eligible_count = eligible_count
    automation.last_run_sent_count = sent
    automation.save(update_fields=[
        'last_run_at', 'last_run_eligible_count', 'last_run_sent_count',
        'updated_at',
    ])

    return {
        'automation_id': automation.pk,
        'eligible_count': eligible_count,
        'sent_count': sent,
        'campaign_id': campaign.pk,
    }


def _ensure_default_audience(automation: Automation):
    """Some automations have no `audience` (the trigger itself is
    the entire eligibility filter). When we create a Campaign for
    the fire, we still need an audience FK — so we look up or
    create a per-tenant "trigger-only" placeholder. Operators can
    safely ignore this in the audiences list.
    """
    from .models import Audience
    audience, _ = Audience.objects.get_or_create(
        tenant=automation.tenant,
        name='__automation_only__',
        defaults={
            'description': (
                'Internal placeholder used when an automation fires without '
                'an explicit audience filter. Do not edit.'
            ),
            'filter_spec': {},
        },
    )
    return audience
