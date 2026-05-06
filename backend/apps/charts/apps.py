from django.apps import AppConfig


class ChartsConfig(AppConfig):
    """Clinical chart notes — provider-only treatment records.

    First product surface that distinguishes clinical access from
    general-staff access. Front desk + bookkeeper + marketing CANNOT
    read chart notes even though they're authenticated in the same
    tenant. The gate is `VIEW_CHART` (provider role + owner/manager
    by default).

    Phase 4A session 1 ships only the notes thread. Treatment records
    (per-appointment, with dose/lot/site), templates (SOAP / CC-HPI-
    ROS), addenda, voiding, photos, and co-signing are all later
    sessions of the same phase.

    See [ADR 0015 — Clinical chart notes](../../../docs/decisions/0015-clinical-chart-notes.md)
    for the full design rationale, HIPAA + SOC 2 framing, and
    intentionally-deferred items.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.charts'
    label = 'charts'
