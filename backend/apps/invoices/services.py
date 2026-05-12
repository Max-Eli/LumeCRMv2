"""Invoice service helpers.

Contains the per-tenant invoice-number generator, the on-demand PDF
renderer, and the email-to-client sender. Other invoice-related
services (refund flow) will land here as their features ship.
"""

from __future__ import annotations

import io
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Invoice


class InvoiceEmailError(Exception):
    """Raised when an invoice can't be emailed for a business reason
    (e.g. customer has no email on file). View layer turns this into
    a 400; we keep the exception class here so callers don't need to
    catch a generic ValueError."""

INVOICE_NUMBER_PREFIX = 'INV'

# How many sequence digits to pad to. 4 → up to 9999 invoices per
# tenant per year, which covers any plausible single-spa annual
# volume; we widen this when a tenant approaches the cap.
INVOICE_SEQUENCE_PAD = 4

# Maximum collision-retry attempts before we give up. At single-spa
# scale collisions are vanishingly rare (concurrent creates would have
# to be on the same tenant + same year + millisecond-aligned). 5 is
# generous belt-and-suspenders.
MAX_RETRIES = 5


def generate_invoice_number(tenant, *, year: int | None = None) -> str:
    """Return the next per-tenant invoice number in `INV-YYYY-NNNN` format.

    Uses a `SELECT ... FOR UPDATE` lock on the highest-numbered
    invoice for this tenant + year so concurrent transactions
    serialize. The first-of-year case has no row to lock; the
    `UniqueConstraint` on `(tenant, invoice_number)` is the final
    backstop for that race — callers should wrap the
    `Invoice.objects.create()` in a retry loop (see
    `apps.invoices.signals.create_invoice_for_appointment`).

    `year` defaults to the current calendar year. Sequence resets on
    January 1 — INV-2026-9999 is followed by INV-2027-0001, not
    INV-2026-10000.
    """
    year = year or timezone.now().year
    prefix = f'{INVOICE_NUMBER_PREFIX}-{year}-'

    # `select_for_update` only locks rows it returns. When this query
    # returns the highest existing number, that row is locked; a
    # concurrent transaction calling this function will block on the
    # same row until ours commits, then read the new max. When the
    # query returns None (first invoice of the year), no lock is held —
    # the caller's IntegrityError-retry catches that race.
    last = (
        Invoice.objects
        .select_for_update()
        .filter(tenant=tenant, invoice_number__startswith=prefix)
        .order_by('-invoice_number')
        .first()
    )

    if last and last.invoice_number:
        try:
            last_seq = int(last.invoice_number[len(prefix):])
        except (ValueError, TypeError):
            # Unexpectedly malformed number — should never happen
            # because we control the format. Fall back to 0 so we
            # restart sequencing rather than crash.
            last_seq = 0
    else:
        last_seq = 0

    next_seq = last_seq + 1
    return f'{prefix}{next_seq:0{INVOICE_SEQUENCE_PAD}d}'


def assign_invoice_number(invoice: Invoice) -> None:
    """Assign the next invoice number to a freshly-created invoice.

    Wraps `generate_invoice_number` + a retry loop on collision. The
    caller passes an Invoice that has just been saved with
    `invoice_number=''`; we update it in-place. Idempotent — does
    nothing if the invoice already has a number.

    Must run inside an outer transaction so the SELECT FOR UPDATE
    lock holds. Use this from the signal handler after the Invoice
    row exists.
    """
    if invoice.invoice_number:
        return
    from django.db import IntegrityError
    for attempt in range(MAX_RETRIES):
        try:
            with transaction.atomic():
                number = generate_invoice_number(invoice.tenant)
                Invoice.objects.filter(pk=invoice.pk).update(invoice_number=number)
                invoice.invoice_number = number
                return
        except IntegrityError:
            if attempt == MAX_RETRIES - 1:
                raise
            continue


# ── PDF rendering ────────────────────────────────────────────────────


def _format_money(cents: int) -> str:
    """Return cents as a USD-formatted string like '$123.45'."""
    return f'${cents / 100:,.2f}'


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """Render `invoice` as an A4 PDF and return the raw bytes.

    Rendering is **on-demand** — the database row is the source of
    truth, and the PDF is a deterministic projection of it. We do
    not store the PDF; subsequent requests re-render. PAID and VOID
    invoices have immutable line items + totals (enforced by state
    machine + CheckConstraints), so the projection is stable for the
    invoice's lifetime. OPEN invoices may change line items, which
    is fine — the rendered PDF reflects the current state at request
    time.

    See ADR 0018 for the trade-offs (on-demand vs S3-cached, the
    immutability argument, why we don't store).
    """
    # Lazy imports keep the reportlab dependency out of the import
    # graph of every Django startup — only loaded on first PDF render.
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title=invoice.invoice_number or f'Invoice #{invoice.pk}',
        author=invoice.tenant.name,
    )

    styles = getSampleStyleSheet()
    body = styles['BodyText']
    small = ParagraphStyle('small', parent=body, fontSize=9, leading=11)
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], spaceAfter=4)
    h_right = ParagraphStyle('hr', parent=body, alignment=TA_RIGHT, fontSize=18, leading=20)
    label = ParagraphStyle(
        'label', parent=body, fontSize=8, leading=10,
        textColor=colors.HexColor('#737373'),
    )

    elements: list = []

    tenant = invoice.tenant
    customer = invoice.customer
    # Status -> display label.
    status_display = {
        Invoice.Status.OPEN: 'Open',
        Invoice.Status.PAID: 'Paid',
        Invoice.Status.VOID: 'Void',
    }.get(invoice.status, invoice.status)

    # ── Header: tenant name (left) + INVOICE label + number (right) ──
    header = Table(
        [[
            Paragraph(f'<b>{tenant.name}</b>', h1),
            Paragraph(f'<font color="#737373">INVOICE</font>', h_right),
        ], [
            Paragraph(
                f'Issued {invoice.created_at:%b %d, %Y}',
                small,
            ),
            Paragraph(
                f'<b>{invoice.invoice_number or f"#{invoice.pk}"}</b>',
                ParagraphStyle('num', parent=body, alignment=TA_RIGHT, fontSize=12),
            ),
        ]],
        colWidths=[3.6 * inch, 3.6 * inch],
    )
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(header)
    elements.append(Spacer(1, 0.25 * inch))

    # ── Bill-to + status block ──
    bill_to_lines = [f'<b>{customer.first_name} {customer.last_name}</b>']
    if customer.email:
        bill_to_lines.append(customer.email)
    if customer.phone:
        bill_to_lines.append(customer.phone)
    bill_to = Paragraph('<br/>'.join(bill_to_lines), body)

    status_lines = [
        Paragraph('STATUS', label),
        Paragraph(f'<b>{status_display}</b>', body),
    ]
    if invoice.status == Invoice.Status.PAID and invoice.closed_at:
        status_lines.append(Paragraph(
            f'Paid {invoice.closed_at:%b %d, %Y at %-I:%M %p}', small,
        ))
        if invoice.payment_method:
            label_method = invoice.get_payment_method_display() if hasattr(invoice, 'get_payment_method_display') else invoice.payment_method
            status_lines.append(Paragraph(f'via {label_method}', small))
        if invoice.payment_reference:
            status_lines.append(Paragraph(f'Ref: {invoice.payment_reference}', small))
    elif invoice.status == Invoice.Status.VOID and invoice.voided_at:
        status_lines.append(Paragraph(
            f'Voided {invoice.voided_at:%b %d, %Y}', small,
        ))

    bill_status = Table(
        [[
            [Paragraph('BILL TO', label), bill_to],
            status_lines,
        ]],
        colWidths=[4.2 * inch, 3.0 * inch],
    )
    bill_status.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(bill_status)
    elements.append(Spacer(1, 0.3 * inch))

    # ── Line items table ──
    line_rows = [['Description', 'Qty', 'Unit price', 'Tax', 'Line total']]
    for line in invoice.line_items.all().order_by('id'):
        line_total = line.line_subtotal_cents + line.line_tax_cents
        tax_label = (
            f'{line.tax_rate_percent.normalize()}%'
            if isinstance(line.tax_rate_percent, Decimal) and line.tax_rate_percent != 0
            else '—'
        )
        line_rows.append([
            Paragraph(line.description, body),
            str(line.quantity),
            _format_money(line.unit_price_cents),
            tax_label,
            _format_money(line_total),
        ])

    lines_table = Table(
        line_rows,
        colWidths=[3.4 * inch, 0.6 * inch, 1.1 * inch, 0.7 * inch, 1.4 * inch],
        repeatRows=1,
    )
    lines_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#404040')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#cccccc')),
        ('LINEBELOW', (0, -1), (-1, -1), 0.25, colors.HexColor('#eeeeee')),
    ]))
    elements.append(lines_table)
    elements.append(Spacer(1, 0.15 * inch))

    # ── Totals block (right-aligned) ──
    totals_rows = [
        ['Subtotal', _format_money(invoice.subtotal_cents)],
        ['Tax', _format_money(invoice.tax_cents)],
    ]
    if invoice.gift_card_credits_cents > 0:
        totals_rows.append(['Gift card credits', f'− {_format_money(invoice.gift_card_credits_cents)}'])
    totals_rows.append(['Total', _format_money(invoice.total_cents)])

    totals = Table(totals_rows, colWidths=[1.5 * inch, 1.4 * inch], hAlign='RIGHT')
    totals.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LINEABOVE', (0, -1), (-1, -1), 0.5, colors.HexColor('#404040')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
    ]))
    elements.append(totals)
    elements.append(Spacer(1, 0.4 * inch))

    # ── Footer ──
    elements.append(Paragraph(
        f'<font color="#a3a3a3">Generated {timezone.now():%b %d, %Y at %-I:%M %p}. '
        f'This invoice is a projection of record {invoice.invoice_number or invoice.pk} '
        f'and is regenerated on demand.</font>',
        small,
    ))

    doc.build(elements)
    return buf.getvalue()


# ── Email to client ──────────────────────────────────────────────────


def send_invoice_email(invoice: Invoice, *, sender_user) -> str:
    """Email the invoice PDF to the customer of record.

    Renders the invoice PDF via `render_invoice_pdf` and attaches it
    to a transactional email sent through Django's mail backend
    (django-ses in prod, file-based in dev, locmem in tests). Returns
    the recipient address used. Raises `InvoiceEmailError` if the
    customer has no email on file — view layer surfaces this as 400.

    `sender_user` is the staff user who initiated the send; it's
    recorded in the audit log at the view layer. The actual email
    From is the tenant's configured DEFAULT_FROM_EMAIL — the spa's
    branded sending identity, not the operator's personal address.
    HIPAA + SOC 2: the customer should not receive emails that look
    like they came from a staff member's personal inbox.

    Uses `fail_silently=False` so SES / SMTP errors bubble up — we
    want the view to return a clear 502/503 if the mail backend is
    broken, not silently lie about successful delivery.
    """
    customer = invoice.customer
    recipient = (customer.email or '').strip()
    if not recipient:
        raise InvoiceEmailError(
            'Customer has no email on file. Add one to their profile '
            'before sending the invoice.'
        )

    pdf_bytes = render_invoice_pdf(invoice)

    invoice_label = invoice.invoice_number or f'#{invoice.pk}'
    context = {
        'customer': customer,
        'invoice': invoice,
        'invoice_label': invoice_label,
        'tenant_name': invoice.tenant.name,
        # ADR 0007: the row, not the PDF, is the legal record. The
        # email mentions this so a customer doesn't think the PDF
        # itself is the source of truth.
        'total_label': f'${invoice.total_cents / 100:,.2f}',
    }

    text_body = render_to_string('invoices/email/sent.txt', context)
    html_body = render_to_string('invoices/email/sent.html', context)

    msg = EmailMultiAlternatives(
        subject=f'Your invoice from {invoice.tenant.name} — {invoice_label}',
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    msg.attach_alternative(html_body, 'text/html')
    msg.attach(
        filename=f'{invoice_label}.pdf',
        content=pdf_bytes,
        mimetype='application/pdf',
    )
    msg.send(fail_silently=False)
    return recipient
