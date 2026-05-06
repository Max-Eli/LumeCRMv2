from django.apps import AppConfig


class MarketingConfig(AppConfig):
    """Email + SMS marketing campaigns (Phase 1L).

    Distinct from `apps.notifications` (Phase 1F transactional
    reminders) because marketing has fundamentally different consent
    semantics: TCPA + CAN-SPAM require explicit opt-in per channel,
    survival of opt-out across re-imports, and per-message audit.

    Session 1 (this commit) ships the data model, Audience CRUD with
    live-count, and the Marketing nav landing. Templates, Campaigns,
    and the actual send wiring (AWS SES + Twilio HIPAA-eligibility)
    land in subsequent sessions per ADR 0016 § "Consequences."

    See [ADR 0016 — Email + SMS marketing](../../../docs/decisions/0016-email-and-sms-marketing.md).
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.marketing'
    label = 'marketing'
