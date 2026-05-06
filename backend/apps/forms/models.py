"""Form models — templates (Session 1) + submissions (Session 2).

`FormTemplate` is the reusable definition; `FormSubmission` is the
per-customer materialization that the client actually fills.

Templates come in two flavors:

  - **intake**: general first-visit questionnaire. Auto-assigned to a
    customer's FIRST appointment ever, never re-asked.
  - **consent**: per-service consent. Mapped to one or more `Service`
    rows via `ServiceFormAssignment`; auto-assigned when those
    services are booked. Default re-sign rule is `per_visit` (CYA
    for clinical work — operators can relax to `once` per template).

Each `FormSubmission` snapshots the template's schema at the moment
of assignment, so post-assignment edits to the template don't change
what the client sees on a pending submission OR what was signed on a
completed one. The fill page renders from the snapshot, never from
the live template.

Hard delete is intentionally not exposed on either model. Submissions
FK into templates with `PROTECT`; templates can be soft-deactivated
(`is_active=False`) which stops auto-assignment but leaves history
intact. See ADR 0008 (Forms data model) and ADR 0011 (submissions +
tokenized fill flow).
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


def _generate_submission_token() -> str:
    """High-entropy URL-safe token for the public fill link.

    `secrets.token_urlsafe(32)` produces ~256 bits of entropy
    (~43 chars) — far more than enough that brute-forcing a token
    space of all currently-pending submissions is infeasible. The
    URL-safe alphabet means we can drop it directly into a path
    segment without escaping.
    """
    return secrets.token_urlsafe(32)


class FormTemplate(TenantedModel):
    """A reusable form template — intake or consent."""

    class FormType(models.TextChoices):
        INTAKE = 'intake', 'Intake'
        CONSENT = 'consent', 'Consent'

    class Recurrence(models.TextChoices):
        # Sign once per customer ever — typical for intake forms +
        # for consent forms the spa has decided are stable enough not
        # to re-prompt every visit.
        ONCE = 'once', 'Once per customer'
        # Sign every visit that triggers the form. Safest CYA default
        # for clinical consent — every Botox visit gets a fresh
        # consent on file. Some state regs require this.
        PER_VISIT = 'per_visit', 'Every visit'

    name = models.CharField(
        max_length=200,
        help_text='Operator-facing label, e.g. "New client intake" or "Botox consent v3".',
    )
    description = models.TextField(
        blank=True,
        help_text='Internal notes about when to use this form. Not shown to clients.',
    )
    form_type = models.CharField(max_length=20, choices=FormType.choices)
    recurrence = models.CharField(
        max_length=20,
        choices=Recurrence.choices,
        default=Recurrence.PER_VISIT,
        help_text=(
            'How often a customer must (re)sign. "Once" = sign once forever '
            '(typical for intake). "Every visit" = sign each appointment that '
            'triggers the form (typical for clinical consent).'
        ),
    )
    schema = models.JSONField(
        default=dict,
        help_text=(
            'Field definitions: {"fields": [{"id": "...", "type": "short_text", '
            '"label": "...", "required": true, ...}]}. Shape validated by the '
            'serializer.'
        ),
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text=(
            'Auto-incremented when the schema changes. Submissions (Session 2) '
            'snapshot the version they were signed against so historical '
            'records stay legible after the template evolves.'
        ),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            'Inactive templates stop auto-assigning to new appointments. Existing '
            'pending + completed submissions are unaffected.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['form_type', 'name']
        indexes = [
            models.Index(fields=['tenant', 'form_type', 'is_active']),
        ]

    def __str__(self):
        return f'{self.name} (v{self.version})'


class ServiceFormAssignment(TenantedModel):
    """Maps a `consent` FormTemplate to a `Service`.

    When an appointment is created with a service that has any active
    `consent` form assignments, those forms get auto-attached as
    pending submissions (Session 2 work). Intake forms aren't
    represented here — their auto-assignment is "first appointment
    ever per customer," not service-driven.

    The `unique_together` guard keeps each (form, service) pairing
    singular — no duplicate assignments. Soft-delete handled at the
    template level: deactivating a template stops its assignments
    from triggering even though the rows survive.
    """

    form_template = models.ForeignKey(
        FormTemplate,
        on_delete=models.CASCADE,
        related_name='service_assignments',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.CASCADE,
        related_name='form_assignments',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('form_template', 'service')]
        ordering = ['form_template', 'service']

    def __str__(self):
        return f'{self.form_template.name} → {self.service.name}'


class FormSubmission(TenantedModel):
    """Per-customer materialization of a `FormTemplate` to be signed.

    Created by the auto-assignment service (`forms.services.assign_forms_for_appointment`)
    when an appointment triggers an intake or consent rule. The
    `schema_snapshot` is captured at assignment time so the template
    can evolve afterward without changing what's already in flight or
    signed — see ADR 0011 for the rationale.

    Status lifecycle:

        pending  ──► completed  (client signed via tokenized link)
            │
            ▼
        voided  (operator marked invalid; signature not required)

    Voided submissions are kept (audit trail) and can be re-issued by
    creating a new submission against the same template — re-issue
    happens via the API, not by mutating the voided row.

    PHI considerations:

      - `answers` and `signature_data` ARE PHI (medical history,
        consent responses). Detail endpoint gates these behind
        `VIEW_CLIENT_PHI`-style minimum-necessary access (Session 3
        work; for now, owner+manager+the customer's assigned provider
        can read).
      - List endpoints return STATUS only — front desk can see "Sarah
        has 2 pending forms" without seeing the answers.
      - Audit log entry on every detail read so the access trail is
        complete (HIPAA §164.312(b)).

    Token security:

      - 256 bits of entropy via `secrets.token_urlsafe(32)`.
      - Single-use for SUBMISSION (pending → completed transitions
        once; subsequent POSTs reject). Read remains open after
        signing for the operator-facing "view this signed form" flow.
      - No expiry in v1. Polish item: invalidate when the related
        appointment is cancelled or far past.
      - URL path placement (not query string) — Django doesn't log
        path segments by name, so the token doesn't leak into stock
        access logs. `/api/forms/sign/<token>/` is the public route.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending signature'
        COMPLETED = 'completed', 'Completed'
        VOIDED = 'voided', 'Voided'

    form_template = models.ForeignKey(
        FormTemplate,
        on_delete=models.PROTECT,
        related_name='submissions',
        help_text='Template this submission was generated from. PROTECT — submissions outlive template retirement.',
    )
    template_version_at_assignment = models.PositiveIntegerField(
        help_text='Snapshot of `FormTemplate.version` at assignment time, for audit + display.',
    )
    schema_snapshot = models.JSONField(
        help_text=(
            "Snapshot of the template's `schema` at assignment time. The fill "
            'page renders from this, never from the live template — protects '
            "in-flight pending submissions from template edits, and protects "
            "signed submissions from being re-rendered as a different shape."
        ),
    )

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='form_submissions',
    )
    appointment = models.ForeignKey(
        'appointments.Appointment',
        on_delete=models.PROTECT,
        related_name='form_submissions',
        null=True,
        blank=True,
        help_text=(
            'Appointment that triggered this submission. Null for intake forms '
            "(those are per-customer, not per-appointment — but the trigger is "
            "still the customer's first appointment ever)."
        ),
    )

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=_generate_submission_token,
        help_text=(
            'High-entropy public token (~256 bits via secrets.token_urlsafe). '
            'Bearer credential for the public fill page — anyone with the URL '
            'can fill the form. Generated server-side on submission create.'
        ),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    answers = models.JSONField(
        default=dict,
        help_text=(
            'Filled answers keyed by field id from the schema snapshot. '
            'PHI — gated behind VIEW_CLIENT_PHI on the detail endpoint.'
        ),
    )
    signature_data = models.TextField(
        blank=True,
        help_text=(
            'Base64-encoded PNG of the client\'s canvas signature. PHI. Empty '
            'until status transitions to completed.'
        ),
    )

    # Audit trail captured at signing — the WHO + WHEN + FROM-WHERE of
    # the consent. SOC 2 CC 7.2 + HIPAA §164.312(b) coverage.
    signed_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(
        null=True, blank=True,
        help_text='IP address that submitted the signature. Captured for audit.',
    )
    user_agent = models.TextField(
        blank=True,
        help_text='Browser user-agent string at time of signing. Captured for audit.',
    )

    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='voided_form_submissions',
    )
    voided_reason = models.TextField(
        blank=True,
        help_text='Operator-supplied reason for voiding. Required at the API level.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'customer', 'status']),
            models.Index(fields=['tenant', 'appointment', 'status']),
        ]

    def __str__(self):
        return f'{self.form_template.name} for {self.customer.full_name} ({self.status})'
