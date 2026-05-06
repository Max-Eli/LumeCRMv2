"""Clinical chart notes — Phase 4A sessions 1 + 2.

A `ChartNote` is a per-customer, provider-signed record of what
was observed or administered. It's PHI in the strongest sense —
treatment history tied to identity — and the access tier is
tighter than the rest of the customer profile (front desk doesn't
read).

Lifecycle:

    pending edit  ─►  locked  ─►  optional addendum chain
    (≤60 min)         (forever)   (each addendum is a separate row,
                          │        also with its own 60-min window)
                          ▼
                       voided
                       (owner/manager only, requires reason;
                        excluded from clinical reads but row
                        survives in audit trail)

The provider who signs a note can edit the body within 60 min
(typo correction during the visit). After that the row locks.
If they need to correct or expand a locked note, they sign an
**addendum** — a separate row with `parent_note` pointing at the
original. Addenda are the ordinary corrective workflow.

For records that should never have existed (wrong patient,
malicious entry, fundamental mistake), an owner/manager **voids**
the note with a reason. Voiding doesn't erase — the row remains
in the audit trail; clinical reads exclude it; the UI renders it
struck-through.

The `author_was_clinical` flag snapshots the author's clinical
status at signing time. A provider's job title can change later
(promoted from RN to NP, moved out of clinical roles); the
record's legal posture is what was true when it was signed, not
what's true now. This snapshot supports SOC 2 CC 7.3 change-
management coverage on PHI records.

See [ADR 0015 — Clinical chart notes](../../../docs/decisions/0015-clinical-chart-notes.md)
for the full design rationale, including the session 2 design at
the bottom for the addenda + voiding decisions.
"""

from __future__ import annotations

import datetime as dt

from django.db import models
from django.utils import timezone

from apps.tenants.abstract_models import TenantedModel

# Window during which the original author can edit the note body
# in place. After this expires, the API rejects edits and the
# only path forward is an addendum (Session 2).
EDIT_WINDOW_MINUTES = 60


class ChartNote(TenantedModel):
    """A signed clinical observation tied to a customer (and
    optionally an appointment). Append-only after the edit window
    expires.
    """

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='chart_notes',
    )
    # Optional appointment linkage. SET_NULL on delete: clinical
    # records outlive the operational reason they were written. A
    # deleted appointment shouldn't take its chart record with it.
    appointment = models.ForeignKey(
        'appointments.Appointment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chart_notes',
    )

    # PHI. Free-form text in v1; structured templates land in a
    # later session. Length is unbounded — providers occasionally
    # write very long notes (procedure walkthroughs).
    body = models.TextField()

    # The provider who signed the note. PROTECT because we never
    # want to lose authorship — a deleted membership leaves
    # historical chart records ownerless.
    author = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.PROTECT,
        related_name='chart_notes_authored',
    )
    # Snapshot of `author.job_title.is_clinical` at signing time.
    # See module docstring + ADR 0015 for the reasoning.
    author_was_clinical = models.BooleanField(
        default=False,
        help_text=(
            "Whether the author held a clinical job title at signing. "
            "Snapshot — does NOT update if the provider changes job "
            "title later. Used as the legal-status anchor on the record."
        ),
    )

    signed_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text='Set on creation; never updated.',
    )

    # ── Addendum chain ─────────────────────────────────────────────
    # Self-referential FK. Null for top-level notes. PROTECT on
    # delete because addenda are independently authored statements;
    # if the parent ever needed to be removed at the DB level (rare
    # — there's no DELETE endpoint), the addenda would have to be
    # cleaned up first. Orphaning them would lose the contextual
    # tie that makes them legible to a clinical reader.
    parent_note = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='addenda',
        help_text=(
            'When set, this row is an addendum to another (locked) '
            'note. Top-level notes have parent_note=NULL. Only one '
            'level of nesting allowed — addenda cannot have addenda.'
        ),
    )

    # ── Void state ─────────────────────────────────────────────────
    # See ADR 0015 § "Session 2 — Addenda and voiding". Voiding is
    # one-way; there is no "un-void" path. The row survives so the
    # audit trail and any pre-void clinical reads remain intact.
    is_voided = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            'True when an owner/manager has invalidated this note. '
            'Voided notes are excluded from clinical reads by default '
            'and rendered struck-through; the row survives.'
        ),
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='voided_chart_notes',
    )
    voided_reason = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text=(
            'Operator-authored justification for the void '
            '("wrong patient", "signed in error", etc.). Required '
            'when voiding.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-signed_at']
        indexes = [
            # Hot path: the customer-profile Notes tab loads the
            # thread by tenant + customer + signed_at desc.
            models.Index(fields=['tenant', 'customer', '-signed_at']),
            # Audit / compliance lookup: "show me everything author X
            # signed in the last quarter."
            models.Index(fields=['tenant', 'author', '-signed_at']),
            # Addendum threading: the UI groups addenda under the
            # parent client-side; a parent_note index keeps the
            # parent → addenda lookup cheap when we eventually add
            # a per-thread fetch.
            models.Index(fields=['tenant', 'parent_note', 'signed_at']),
        ]

    def __str__(self):  # pragma: no cover - admin convenience only
        when = timezone.localtime(self.signed_at).strftime('%Y-%m-%d %H:%M')
        return f'{self.customer.full_name} · {when} ({self.author.user.email})'

    # ── Edit-window helpers ─────────────────────────────────────────

    @property
    def edit_window_ends_at(self) -> dt.datetime:
        """Computed; not stored. The deadline after which the body
        is locked. Derived from `signed_at` so a constant change
        (e.g. raising the window from 60 min to 90 min) re-evaluates
        for every existing record without a migration."""
        return self.signed_at + dt.timedelta(minutes=EDIT_WINDOW_MINUTES)

    @property
    def is_locked(self) -> bool:
        """True when the typo-correction window has passed and the
        body is no longer editable through the API."""
        return timezone.now() >= self.edit_window_ends_at

    def can_be_edited_by(self, membership) -> bool:
        """Edit gate: must be the original author AND within the
        edit window. Permission to even attempt the edit (`SIGN_CHART`)
        is checked by the view's permission class — this is the
        post-permission ownership + window check."""
        if self.is_locked:
            return False
        if membership is None:
            return False
        return membership.pk == self.author_id
