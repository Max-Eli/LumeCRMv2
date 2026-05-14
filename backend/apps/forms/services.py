"""Service functions for the forms app.

Two responsibilities split here:

  1. **Auto-assignment** (`assign_forms_for_appointment`) — called
     from `AppointmentViewSet.perform_create` to materialize pending
     submissions per the rules in ADR 0011.
  2. **Operator-initiated email** (`email_signed_copy`) — sends a
     signed `FormSubmission` to the customer on demand. See ADR 0012
     for the design (operator-initiated, HTML inline + link, no PHI
     in audit metadata, dev console backend / prod SES).

Both keep their I/O at the edge — `assign_forms_for_appointment`
takes an `Appointment` and returns the created submissions;
`email_signed_copy` takes a `FormSubmission` + the operator's user
and returns the message-id-equivalent (or raises). Tests mock the
email backend via Django's `mail.outbox`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone as djtz

from apps.appointments.models import Appointment

from .models import FormSubmission, FormTemplate, ServiceFormAssignment

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from apps.tenants.models import Tenant


@transaction.atomic
def assign_forms_for_appointment(appointment: Appointment) -> list[FormSubmission]:
    """Create pending `FormSubmission`s for an appointment per ADR 0011 rules.

    Returns the newly-created submission rows (so the caller can
    surface them in the API response or log them). Idempotent in
    practice — if a submission already exists that satisfies a rule,
    we don't create a duplicate.

    Wraps everything in a single transaction so a failure half-way
    through doesn't leave a partial assignment state. The
    `transaction.atomic` decorator participates in the outer
    transaction the appointments view already opens, so this nests
    cleanly.
    """
    tenant = appointment.tenant
    customer = appointment.customer
    created: list[FormSubmission] = []

    # ── Intake forms ────────────────────────────────────────────────
    is_first_appointment = not (
        Appointment.objects
        .filter(tenant=tenant, customer=customer)
        .exclude(pk=appointment.pk)
        .exists()
    )
    if is_first_appointment:
        intake_templates = FormTemplate.objects.filter(
            tenant=tenant,
            form_type=FormTemplate.FormType.INTAKE,
            is_active=True,
        )
        for template in intake_templates:
            sub = _maybe_create_submission(
                tenant=tenant,
                template=template,
                customer=customer,
                # Intake is per-customer, not per-appointment — the
                # appointment is just the trigger. Setting it nullable
                # would let "rescheduling the trigger appointment"
                # leave the intake unmoored. We DO link it for
                # traceability ("which appointment triggered this
                # intake") but the customer relationship is what
                # matters for re-assignment rules.
                appointment=appointment,
                trigger='intake_first_appt',
            )
            if sub:
                created.append(sub)

    # ── Consent forms (per service) ─────────────────────────────────
    consent_assignments = (
        ServiceFormAssignment.objects
        .filter(
            tenant=tenant,
            service=appointment.service,
            form_template__is_active=True,
            form_template__form_type=FormTemplate.FormType.CONSENT,
        )
        .select_related('form_template')
    )
    for assignment in consent_assignments:
        sub = _maybe_create_submission(
            tenant=tenant,
            template=assignment.form_template,
            customer=customer,
            appointment=appointment,
            trigger='consent_per_service',
        )
        if sub:
            created.append(sub)

    return created


def _maybe_create_submission(
    *,
    tenant: 'Tenant',
    template: FormTemplate,
    customer,
    appointment: Appointment,
    trigger: str,
) -> FormSubmission | None:
    """Create a pending submission unless the recurrence rule says skip.

    Returns the new submission, or None if skipped (e.g. recurrence
    is `'once'` and a completed submission already exists for this
    customer).
    """
    # Recurrence='once' fence: skip if customer has already signed
    # a submission of THIS template. Voided submissions don't count
    # (they were invalidated; the customer effectively hasn't signed
    # this template yet).
    if template.recurrence == FormTemplate.Recurrence.ONCE:
        already_signed = FormSubmission.objects.filter(
            tenant=tenant,
            form_template=template,
            customer=customer,
            status=FormSubmission.Status.COMPLETED,
        ).exists()
        if already_signed:
            return None

    # Pending-duplicate guard: if a pending submission of this
    # template already exists for this customer, don't create a
    # second one. Handles the race condition where two appointments
    # are booked nearly simultaneously and both pass the
    # "is_first_appointment" check. Without this, the customer would
    # see "you have 2 pending intake forms" — confusing.
    if template.recurrence == FormTemplate.Recurrence.ONCE:
        already_pending = FormSubmission.objects.filter(
            tenant=tenant,
            form_template=template,
            customer=customer,
            status=FormSubmission.Status.PENDING,
        ).exists()
        if already_pending:
            return None

    return FormSubmission.objects.create(
        tenant=tenant,
        form_template=template,
        template_version_at_assignment=template.version,
        schema_snapshot=template.schema,
        customer=customer,
        appointment=appointment,
        # `token` defaults via the model's default callable.
        # `status` defaults to PENDING.
        # `answers` defaults to {}.
        # `signature_data` defaults to ''.
    )


# ── Email send: operator-initiated signed-copy delivery (ADR 0012) ──


class EmailSendError(Exception):
    """Raised when the email send setup is invalid (e.g. customer has
    no email on file, submission isn't signed). View layer catches
    this and converts to a 400.
    """


def email_signed_copy(
    submission: FormSubmission,
    *,
    sent_by: 'AbstractUser',
) -> str:
    """Render + send a copy of a signed `FormSubmission` to the
    customer's email on file. Operator-initiated only — caller
    enforces the permission gate.

    Raises `EmailSendError` for the legitimate "can't send" cases:
      - submission isn't completed (pending or voided)
      - customer has no email address

    Returns the recipient email address as a sanity-check value the
    view can echo to the operator ("Sent to pat@example.com"). The
    actual delivery confirmation comes from SES bounce/complaint
    webhooks in production (Phase 0c); v1 trusts the SMTP / SES API
    response.

    Audit logging is the caller's responsibility — this function
    just sends. We keep audit decisions in the view to keep the
    "what was logged" + "who triggered it" reasoning together with
    the request handler.
    """
    if submission.status != FormSubmission.Status.COMPLETED:
        raise EmailSendError(
            'Can only email signed submissions. This one is '
            f'currently "{submission.get_status_display()}."'
        )

    customer = submission.customer
    recipient = (customer.email or '').strip()
    if not recipient:
        raise EmailSendError(
            'Customer has no email address on file. Add one to '
            'their profile before sending.'
        )

    # Build the field-by-field render of the signed answers. This is
    # the PHI body of the email — kept in the message itself, not in
    # any audit artifact. The schema_snapshot drives the order +
    # labels so the email reflects exactly what was signed even if
    # the template has changed since.
    fields_render = []
    for field in submission.schema_snapshot.get('fields', []):
        if field.get('type') == 'signature':
            # Skip signature in the body — the email isn't the
            # right venue to embed the canvas image inline. The
            # online view at /sign/<token> is.
            continue
        value = submission.answers.get(field['id'])
        fields_render.append({
            'label': field.get('label', field['id']),
            'value': _format_field_value(field, value),
        })

    # The /sign/<token> URL serves the same signed read-only view
    # the operator sees — sharing it with the customer just means
    # they hit the public route. Build absolute URL from settings.
    fill_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/sign/{submission.token}"

    signed_at_local = submission.signed_at
    signed_date_str = (
        signed_at_local.strftime('%B %-d, %Y') if signed_at_local else 'a recent visit'
    )

    context = {
        'customer': customer,
        'template_name': submission.form_template.name,
        'tenant_name': submission.tenant.name,
        'fields': fields_render,
        'signed_date': signed_date_str,
        'fill_url': fill_url,
    }

    text_body = render_to_string('forms/email/signed_copy.txt', context)
    html_body = render_to_string('forms/email/signed_copy.html', context)

    msg = EmailMultiAlternatives(
        subject=f'Your signed {submission.form_template.name}',
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        # Reply-To set to the tenant's general contact would be a
        # nice touch — Phase 0c per-tenant from-address work. v1
        # leaves it as the central from-address; replies bounce to
        # noreply (acceptable; the email tells the customer to
        # contact the spa directly if they have questions).
    )
    msg.attach_alternative(html_body, 'text/html')

    # `fail_silently=False` — we want exceptions to bubble so the
    # view can return a clear error if SES (prod) or SMTP (dev) is
    # broken, rather than swallowing the failure and lying to the
    # operator.
    msg.send(fail_silently=False)
    return recipient


def _format_field_value(field: dict, value) -> str:
    """Render a stored answer for the email body.

    Matches the read-only display we use elsewhere — choice values
    expanded to their human labels; multi-choice joined with commas;
    empty values shown as a placeholder. Pure formatting; no PHI
    transformation.
    """
    if value in (None, '', []):
        return ''
    field_type = field.get('type')
    if field_type == 'choice_single' and isinstance(value, str):
        for opt in field.get('options', []):
            if opt.get('value') == value:
                return opt.get('label', value)
        return value
    if field_type == 'choice_multiple' and isinstance(value, list):
        labels = []
        opt_map = {opt.get('value'): opt.get('label', opt.get('value')) for opt in field.get('options', [])}
        for v in value:
            labels.append(opt_map.get(v, v))
        return ', '.join(labels)
    return str(value)


# ── PDF rendering ─────────────────────────────────────────────────────


def render_form_submission_pdf(submission: 'FormSubmission') -> bytes:
    """Render a signed form submission as a PDF and return the raw bytes.

    Same architecture as `apps.invoices.services.render_invoice_pdf`
    (ADR 0018): on-demand projection of the row, no caching, no S3
    storage. The submission's `schema_snapshot` + `answers` + frozen
    `signed_at` + `signature_data` are the authoritative record; the
    PDF is a deterministic view of those.

    Renders for both SIGNED and VOIDED submissions. Pending (unsigned)
    submissions raise — there's nothing meaningful to PDF until the
    signature is present. View layer maps that to 400.

    See ADR 0020 for the design rationale and HIPAA framing.
    """
    if submission.status == FormSubmission.Status.PENDING:
        raise ValueError(
            'Cannot render PDF for a pending submission. Sign or void it first.'
        )

    # Lazy imports keep reportlab out of every Django request's
    # import graph.
    import base64
    import io as _io

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        title=f'{submission.form_template.name} — signed',
        author=submission.tenant.name,
    )

    styles = getSampleStyleSheet()
    body = styles['BodyText']
    small = ParagraphStyle('small', parent=body, fontSize=9, leading=11)
    label_style = ParagraphStyle(
        'label', parent=body, fontSize=8, leading=10,
        textColor=colors.HexColor('#737373'),
    )
    value_style = ParagraphStyle(
        'val', parent=body, fontSize=10, leading=14, alignment=TA_LEFT,
    )
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], spaceAfter=4)

    elements: list = []

    customer = submission.customer
    customer_name = (
        f'{customer.first_name} {customer.last_name}'.strip()
        if customer else '—'
    )

    # ── Header ───────────────────────────────────────────────
    elements.append(Paragraph(
        f'<font color="#737373">{submission.tenant.name}</font>', small,
    ))
    elements.append(Paragraph(submission.form_template.name, h1))
    if submission.status == FormSubmission.Status.VOIDED:
        elements.append(Paragraph(
            f'<font color="#b91c1c"><b>VOIDED</b> on '
            f'{submission.voided_at:%b %d, %Y at %-I:%M %p} — '
            f'{submission.voided_reason or "no reason given"}</font>',
            small,
        ))
    elements.append(Spacer(1, 0.15 * inch))

    # ── Bill/sign-to header ──────────────────────────────────
    signed_at_str = (
        submission.signed_at.strftime('%B %-d, %Y at %-I:%M %p')
        if submission.signed_at else '—'
    )
    header_table = Table(
        [[
            [Paragraph('CLIENT', label_style), Paragraph(customer_name, value_style)],
            [Paragraph('SIGNED', label_style), Paragraph(signed_at_str, value_style)],
        ]],
        colWidths=[3.6 * inch, 3.4 * inch],
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.25 * inch))

    # ── Field-by-field render ────────────────────────────────
    # Drive off schema_snapshot.fields (frozen at submission time) so
    # the PDF reflects what was signed even if the live template has
    # changed.
    fields = submission.schema_snapshot.get('fields', [])
    for field in fields:
        if field.get('type') == 'signature':
            # Signature rendered separately below as an image.
            continue
        label = field.get('label', field.get('id', ''))
        value = submission.answers.get(field['id'])
        formatted = _format_field_value(field, value) or '—'

        elements.append(Paragraph(label.upper(), label_style))
        elements.append(Paragraph(formatted.replace('\n', '<br/>'), value_style))
        elements.append(Spacer(1, 0.12 * inch))

    # ── Signature ────────────────────────────────────────────
    if submission.signature_data:
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph('SIGNATURE', label_style))
        # signature_data is a `data:image/png;base64,...` URL or a raw
        # base64 string — strip the URL prefix if present.
        raw = submission.signature_data
        if raw.startswith('data:'):
            raw = raw.split(',', 1)[1] if ',' in raw else ''
        try:
            png_bytes = base64.b64decode(raw)
            sig_buf = _io.BytesIO(png_bytes)
            sig = Image(sig_buf, width=3 * inch, height=1.2 * inch, kind='proportional')
            elements.append(sig)
        except (ValueError, TypeError):
            # Corrupt base64 — render a clear placeholder rather than
            # failing the whole PDF.
            elements.append(Paragraph(
                '<font color="#b91c1c">(signature image could not be rendered)</font>',
                small,
            ))

    # ── Footer ───────────────────────────────────────────────
    elements.append(Spacer(1, 0.3 * inch))
    footer_lines = [
        f'Submission ID: {submission.pk}',
        f'Form template: {submission.form_template.name}',
    ]
    if submission.signed_at:
        footer_lines.append(f'Signed at: {signed_at_str}')
    if submission.ip_address:
        footer_lines.append(f'Signed from IP: {submission.ip_address}')
    elements.append(Paragraph(
        '<br/>'.join(f'<font color="#a3a3a3" size="8">{line}</font>' for line in footer_lines),
        small,
    ))

    doc.build(elements)
    return buf.getvalue()
