"""Audit + state-tracking models for vendor data migrations.

`ImportRun` is the row that captures every migration attempt — when
it ran, which vendor, which tenant, what mode (dry-run vs commit),
how many rows of each entity flowed through, what errors landed
where. Operators consult these rows after a run to know what
happened; reconciliation reports are built from them.

PHI posture: the row contains COUNTS + per-entity error summaries
but never the raw imported data. Customer names + appointment notes
stay in the actual `Customer` / `Appointment` rows with the standard
PHI controls.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


class ImportRun(TenantedModel):
    """One execution of a vendor importer against a tenant.

    Lifecycle:

        running  ─►  succeeded
            │
            ▼
        failed   (terminal — fix + re-run)

    `mode` distinguishes dry-runs (validation only — nothing written
    to the DB) from commit runs (writes flow). Dry-run runs MUST
    happen before commit runs for any given tenant + vendor pair, by
    convention enforced in the management command. The DB doesn't
    enforce this because operators sometimes need to re-commit after
    a partial failure.
    """

    class Vendor(models.TextChoices):
        ZENOTI = 'zenoti', 'Zenoti'
        VAGARO = 'vagaro', 'Vagaro'
        MINDBODY = 'mindbody', 'Mindbody'
        BOULEVARD = 'boulevard', 'Boulevard'

    class Mode(models.TextChoices):
        DRY_RUN = 'dry_run', 'Dry-run (no writes)'
        COMMIT = 'commit', 'Commit (writes)'

    class Status(models.TextChoices):
        RUNNING = 'running', 'Running'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    vendor = models.CharField(max_length=20, choices=Vendor.choices, db_index=True)
    mode = models.CharField(max_length=10, choices=Mode.choices)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True,
    )

    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        help_text='Staff member or platform admin who kicked off the run.',
    )

    # Per-entity counts. Keyed by entity name (`customers`, `memberships`,
    # `packages`, `appointments`); each value is `{fetched, mapped,
    # created, updated, skipped, errors}`. Lets the reconciliation report
    # render without re-querying anything.
    counts = models.JSONField(default=dict, blank=True)

    # Per-row error log — `[{entity, external_id, reason}, …]`. Truncated
    # to the most recent N errors per entity to keep the payload bounded.
    errors = models.JSONField(default=list, blank=True)

    # Free-form notes the operator wants to capture (e.g. "rerun after
    # cleaning up duplicate emails in Zenoti").
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ('-started_at',)
        indexes = [
            models.Index(fields=['tenant', 'vendor', '-started_at']),
        ]

    def __str__(self):
        return f'{self.vendor}/{self.mode} for {self.tenant.slug} ({self.status})'
