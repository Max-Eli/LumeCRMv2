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


# ── Treatment record templates + submissions (Phase 4A Session 3) ─────


class TreatmentRecordTemplate(TenantedModel):
    """Schema-driven form a provider fills out per appointment to
    document what was actually delivered.

    Distinct from `apps.forms.FormTemplate`:
      - FormTemplate: customer-completed (intake + consent),
        triggered before / at the visit.
      - TreatmentRecordTemplate: provider-completed (chart-grade
        record of what happened), triggered at or after the visit.

    The schema shape mirrors FormTemplate.schema so the field
    builder + render logic can share the same field-type vocabulary,
    plus medical-specific extras: `number` (units used, dosages,
    side counts) and the existing types (short_text, long_text,
    choice_*, date, signature).

    `version` increments on every schema-changing save so submitted
    records can pin the version they were signed against — same
    "what did the form look like when this was filled out" guarantee
    that FormTemplate gives.

    Tenant-scoped. Per-service assignment via
    `ServiceTreatmentTemplateAssignment`. Read for clinical staff,
    write for catalog managers (MANAGE_SERVICES).
    """

    name = models.CharField(
        max_length=200,
        help_text=(
            'Operator-facing label, e.g. "Botox treatment record" '
            'or "HydraFacial treatment record".'
        ),
    )
    description = models.TextField(
        blank=True,
        help_text='Internal notes about when to use this template.',
    )
    schema = models.JSONField(
        default=dict,
        help_text=(
            'Field definitions — same shape as FormTemplate.schema: '
            '{"fields": [{"id": "...", "type": "...", "label": "...", '
            '"required": true, ...}]}. Validated by the serializer.'
        ),
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text=(
            'Auto-incremented when `schema` changes. '
            'TreatmentRecord submissions snapshot the version they '
            'were signed against so historical records stay legible '
            'after the template evolves.'
        ),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            'Inactive templates stop appearing in the "create record" '
            'picker for new appointments. Existing records are unaffected.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['tenant', 'is_active', 'name']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='trt_template_unique_tenant_name',
            ),
        ]

    def __str__(self):
        return f'{self.name} (v{self.version})'


class ServiceTreatmentTemplateAssignment(TenantedModel):
    """Maps a `TreatmentRecordTemplate` to a `Service`.

    When a provider opens an appointment to record what they did,
    the templates assigned to that appointment's service are surfaced
    first. Multiple assignments per service are allowed — a single
    appointment can have both a "Botox treatment record" and a
    "Photo documentation" template attached.

    Soft-delete via the template's `is_active=False` — assignment
    rows survive but stop surfacing.
    """

    template = models.ForeignKey(
        TreatmentRecordTemplate,
        on_delete=models.CASCADE,
        related_name='service_assignments',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.CASCADE,
        related_name='treatment_template_assignments',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'service'],
                name='trt_template_assignment_unique',
            ),
        ]

    def __str__(self):
        return f'{self.template.name} → {self.service.name}'


class TreatmentRecord(TenantedModel):
    """A signed treatment record — the structured equivalent of a
    `ChartNote`, filled out per appointment by the provider.

    Lifecycle is identical to ChartNote:

        pending edit  ─►  locked  ─►  optional addendum chain
        (≤60 min)         (forever)   (each addendum is a separate row)
                              │
                              ▼
                           voided
                           (owner/manager only, requires reason)

    Why a separate model from ChartNote (vs. a single "Note" model
    with optional structured fields):

      - PHI posture is identical, but the data shape is different
        (free-form text vs. structured answers keyed by field id).
      - Different lifecycle for the schema (template versions,
        snapshots) doesn't fit cleanly on ChartNote.
      - Reads for compliance reporting can hit just the structured
        records (e.g. "show me every Botox unit dosed last quarter")
        without scanning free-form text.

    The two share UI conventions (read-only viewer with addenda
    threading, void styling) but separate API + model paths.
    """

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='treatment_records',
    )
    appointment = models.ForeignKey(
        'appointments.Appointment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='treatment_records',
        help_text=(
            'The appointment this record documents. SET_NULL on '
            "appointment delete because clinical records outlive the "
            'operational reason they were written.'
        ),
    )

    template = models.ForeignKey(
        TreatmentRecordTemplate,
        on_delete=models.PROTECT,
        related_name='records',
        help_text=(
            'PROTECT — templates with submitted records cannot be '
            "deleted; deactivate (is_active=False) to retire."
        ),
    )
    template_version_at_signing = models.PositiveIntegerField(
        help_text=(
            'Snapshot of `template.version` at signing time. The '
            'reader uses this + `schema_snapshot` to render the '
            'record as it was at the moment of signing, regardless '
            'of subsequent template changes.'
        ),
    )
    schema_snapshot = models.JSONField(
        default=dict,
        help_text=(
            "Frozen copy of the template's schema at signing time. "
            'Lets the read-back render labels + field types even '
            'after the template has been edited or deactivated.'
        ),
    )
    answers = models.JSONField(
        default=dict,
        help_text=(
            "PHI. Provider's responses keyed by field id. Shape "
            'validated against `schema_snapshot` by the serializer.'
        ),
    )

    author = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.PROTECT,
        related_name='treatment_records_authored',
    )
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

    # Addendum chain — same shape as ChartNote.parent_note. An
    # addendum points at the original locked record; the original's
    # parent_note is null. Only one level of nesting.
    parent_record = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='addenda',
        help_text=(
            'When set, this row is an addendum to another (locked) '
            'record. Top-level records have parent_record=NULL. Only '
            'one level of nesting allowed.'
        ),
    )

    # Void state — same posture as ChartNote.
    is_voided = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            'True when an owner/manager has invalidated this record. '
            'Voided records are excluded from clinical reads by '
            'default and rendered struck-through; the row survives.'
        ),
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='voided_treatment_records',
    )
    voided_reason = models.CharField(
        max_length=500,
        blank=True,
        default='',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-signed_at']
        indexes = [
            # Customer profile — Treatment Records tab loads in
            # signed_at desc per customer.
            models.Index(fields=['tenant', 'customer', '-signed_at']),
            # Author audit / compliance.
            models.Index(fields=['tenant', 'author', '-signed_at']),
            # Per-appointment lookup (provider opens a record from
            # the appointment popover).
            models.Index(fields=['tenant', 'appointment', '-signed_at']),
            # Addendum threading.
            models.Index(fields=['tenant', 'parent_record', 'signed_at']),
        ]

    def __str__(self):
        when = timezone.localtime(self.signed_at).strftime('%Y-%m-%d %H:%M')
        return f'{self.customer.full_name} · {self.template.name} · {when}'

    # Reuse ChartNote's edit-window concept — same constant.
    @property
    def edit_window_ends_at(self) -> dt.datetime:
        return self.signed_at + dt.timedelta(minutes=EDIT_WINDOW_MINUTES)

    @property
    def is_locked(self) -> bool:
        return timezone.now() >= self.edit_window_ends_at

    def can_be_edited_by(self, membership) -> bool:
        if self.is_locked:
            return False
        if membership is None:
            return False
        return membership.pk == self.author_id
