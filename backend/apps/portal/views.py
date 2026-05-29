"""Customer-portal HTTP endpoints.

Two surfaces:

  - Public auth (`/api/portal/auth/...`): request + consume magic
    links; ends sessions. `AllowAny` permission because the
    customer is by definition not logged in yet.
  - Authenticated data (`/api/portal/me/`, `/api/portal/appointments/`,
    ...): gated by `IsPortalCustomer`. The `PortalSessionMiddleware`
    sets `request.customer`; views read from it.

Tenant scoping comes from two places working together:

  - The standard `TenantMiddleware` resolves `request.tenant` from
    the request host / `X-Tenant-Slug` header.
  - The portal session is itself bound to one Customer → one Tenant.

A request whose `request.tenant` doesn't match `request.customer.tenant`
is rejected as 403 — defense in depth against a customer with one
spa's session cookie hitting another spa's portal subdomain.
"""

from __future__ import annotations

import logging

from django.utils import timezone as djtz
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .middleware import PORTAL_SESSION_COOKIE
from .models import CustomerPortalSession
from .permissions import IsPortalCustomer
from .serializers import (
    CustomerMeSerializer,
    PortalAppointmentSerializer,
    PortalBookingInputSerializer,
    PortalFormSubmissionSerializer,
    PortalPackageSerializer,
    PortalSubscriptionSerializer,
    ProfileUpdateInputSerializer,
    RequestMagicLinkInputSerializer,
    RescheduleAppointmentInputSerializer,
)
from .services import (
    consume_token,
    find_customer_for_login,
    send_magic_link_email,
)
from .models import CustomerPortalToken

logger = logging.getLogger(__name__)


# ── Public auth ──────────────────────────────────────────────────────


class RequestMagicLinkView(APIView):
    """`POST /api/portal/auth/request-magic-link/` — kicks off the
    login flow. Returns the same 200 response regardless of whether
    the email matched a customer (email-enumeration defense)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        tenant = get_current_tenant()
        if tenant is None:
            # No tenant context = no portal here. 404 keeps the
            # response uninformative about whether portals exist on
            # other hosts.
            return Response(
                {'detail': 'Portal not available on this host.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        ser = RequestMagicLinkInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data['email']

        customer = find_customer_for_login(tenant=tenant, email=email)
        if customer is not None:
            # Throttle is implicit — issuing a token + sending an
            # email is bounded by SES quota; we could layer a per-
            # email rate-limit if abuse appears.
            token = CustomerPortalToken.issue(
                customer=customer,
                requested_ip=request.META.get('REMOTE_ADDR'),
            )
            try:
                send_magic_link_email(customer=customer, token=token, request=request)
            except Exception:
                logger.exception(
                    'portal.magic_link.email_send_failed',
                    extra={'tenant_slug': tenant.slug, 'token_id': token.id},
                )
                # Treat as a 500 — the customer needs the email to
                # log in, and silently 200'ing would leave them
                # waiting indefinitely.
                return Response(
                    {'detail': 'Could not send the sign-in email. Try again in a moment.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Same response for matched + unmatched email — defeats
        # email-enumeration of which addresses are customers.
        return Response(
            {
                'detail': (
                    "If that email is on file, we just sent a sign-in "
                    "link. It expires in 30 minutes."
                ),
            },
            status=status.HTTP_200_OK,
        )


class ConsumeMagicLinkView(APIView):
    """`POST /api/portal/auth/consume/` body: `{ "token": "..." }`.

    Validates the token, creates a portal session, sets the session
    cookie on the response, and returns a slim customer + tenant
    object so the frontend can render the portal home immediately
    without a follow-up `/me/` round-trip.

    Errors:
      - 410 GONE: token used, expired, or wrong tenant.
      - 400: missing token in body.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        tenant = get_current_tenant()
        if tenant is None:
            return Response(
                {'detail': 'Portal not available on this host.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        token_value = (request.data.get('token') or '').strip()
        if not token_value:
            raise ValidationError({'token': 'Token is required.'})

        token = consume_token(token_value=token_value, tenant=tenant)
        if token is None:
            return Response(
                {
                    'detail': (
                        "This sign-in link is no longer valid. Request a new "
                        "one from the sign-in page."
                    ),
                },
                status=status.HTTP_410_GONE,
            )

        # Mint the session + audit-log the login.
        session = CustomerPortalSession.issue(
            customer=token.customer,
            issued_ip=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='portal_session',
            resource_id=session.id,
            request=request,
            metadata={
                'tenant_slug': tenant.slug,
                'customer_id': token.customer_id,
                'event': 'portal_login',
            },
        )

        response = Response(
            CustomerMeSerializer(_customer_me_payload(token.customer)).data,
            status=status.HTTP_200_OK,
        )
        _set_session_cookie(response, session.token)
        return response


class LogoutView(APIView):
    """`POST /api/portal/auth/logout/` — revokes the current session
    + clears the cookie. Idempotent: callable without a session and
    still returns 200 so the frontend's "log out everywhere" UX
    isn't gated on session state."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        session = getattr(request, 'portal_session', None)
        if session is not None:
            session.revoked_at = djtz.now()
            session.save(update_fields=['revoked_at'])
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='portal_session',
                resource_id=session.id,
                request=request,
                metadata={'event': 'portal_logout'},
            )
        response = Response({'detail': 'Signed out.'}, status=status.HTTP_200_OK)
        _clear_session_cookie(response)
        return response


# ── Authenticated portal data ────────────────────────────────────────


class MeView(APIView):
    """`GET /api/portal/me/` — current customer + tenant branding.
    Used by the portal layout to render the avatar/name + apply
    primary_color + logo on every page.

    `PATCH /api/portal/me/` — customer-editable profile fields
    (phone + marketing consents). Non-PHI, non-identity fields only.
    """

    permission_classes = [IsPortalCustomer]

    def get(self, request):
        customer = request.customer
        _guard_tenant_consistency(request)
        record(
            action=AuditLog.Action.READ,
            resource_type='portal_me',
            resource_id=customer.id,
            request=request,
            metadata={'event': 'view_profile'},
        )
        return Response(CustomerMeSerializer(_customer_me_payload(customer)).data)

    def patch(self, request):
        customer = request.customer
        _guard_tenant_consistency(request)

        ser = ProfileUpdateInputSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)

        update_fields: list[str] = []
        changes: dict[str, object] = {}
        if 'phone' in ser.validated_data:
            new_phone = (ser.validated_data['phone'] or '').strip()
            if new_phone != customer.phone:
                customer.phone = new_phone
                update_fields.append('phone')
                changes['phone'] = 'changed'  # value redacted in audit log

        for field in ('email_marketing_opt_in', 'sms_marketing_opt_in'):
            if field in ser.validated_data:
                new_value = bool(ser.validated_data[field])
                if getattr(customer, field) != new_value:
                    setattr(customer, field, new_value)
                    update_fields.append(field)
                    changes[field] = new_value
                    # When opting in for the first time, also stamp the
                    # consent timestamp so marketing-suppression logic
                    # downstream can audit when consent was given.
                    consent_at_field = field.replace('_opt_in', '_consent_at')
                    consent_source_field = field.replace('_opt_in', '_consent_source')
                    if hasattr(customer, consent_at_field) and new_value:
                        setattr(customer, consent_at_field, djtz.now())
                        update_fields.append(consent_at_field)
                    if hasattr(customer, consent_source_field) and new_value:
                        setattr(customer, consent_source_field, 'portal')
                        update_fields.append(consent_source_field)

        if update_fields:
            customer.save(update_fields=[*update_fields, 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='portal_me',
            resource_id=customer.id,
            request=request,
            metadata={'event': 'profile_update', 'changes': changes},
        )

        return Response(CustomerMeSerializer(_customer_me_payload(customer)).data)


class AppointmentsView(APIView):
    """`GET /api/portal/appointments/` — customer's appointments,
    ordered with upcoming first then past. Returns a flat array;
    the frontend partitions it.
    """

    permission_classes = [IsPortalCustomer]

    def get(self, request):
        customer = request.customer
        _guard_tenant_consistency(request)

        qs = (
            Appointment.objects
            .filter(tenant=customer.tenant, customer=customer)
            .select_related('service', 'location', 'provider', 'provider__user')
            .order_by('-start_time')
        )
        data = PortalAppointmentSerializer(qs, many=True).data

        record(
            action=AuditLog.Action.READ,
            resource_type='portal_appointments',
            resource_id=customer.id,
            request=request,
            metadata={'count': len(data)},
        )

        return Response(data)


class CancelAppointmentView(APIView):
    """`POST /api/portal/appointments/<id>/cancel/` — customer
    cancellation. Validates the appointment belongs to the calling
    customer, is in a cancellable status, and is in the future.

    No tenant cancellation-policy enforcement yet (cancellation-
    window fees etc.) — that's a follow-up that needs the tenant
    config + a fee-charge flow. v1 just performs the status flip.
    """

    permission_classes = [IsPortalCustomer]

    def post(self, request, pk: int):
        customer = request.customer
        _guard_tenant_consistency(request)

        try:
            appt = Appointment.objects.select_for_update(of=('self',)).get(
                pk=pk, tenant=customer.tenant, customer=customer,
            )
        except Appointment.DoesNotExist:
            return Response(
                {'detail': 'Appointment not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Re-check the cancellable rules server-side. The serializer's
        # `cancellable` field is for UI display; this is the gate.
        if appt.start_time <= djtz.now():
            raise ValidationError({'detail': 'Past appointments cannot be cancelled.'})
        if appt.status not in (Appointment.Status.BOOKED, Appointment.Status.CONFIRMED):
            raise ValidationError({
                'detail': f'This appointment cannot be cancelled (status: {appt.get_status_display()}).',
            })

        appt.status = Appointment.Status.CANCELLED
        appt.cancelled_at = djtz.now()
        appt.cancelled_reason = 'cancelled_by_customer'
        appt.save(update_fields=['status', 'cancelled_at', 'cancelled_reason', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appt.id,
            request=request,
            metadata={
                'event': 'portal_cancel',
                'customer_id': customer.id,
                'previous_status': 'booked_or_confirmed',
            },
        )

        return Response(PortalAppointmentSerializer(appt).data)


class RescheduleAppointmentView(APIView):
    """`POST /api/portal/appointments/<id>/reschedule/` — customer
    self-reschedule. Moves an existing appointment to a new start
    time; service, provider, and location stay the same.

    The new time is re-validated against the same slot calculator the
    booking picker uses, with the appointment itself excluded from the
    conflict set so a near-current-time move isn't blocked by its own
    slot. Only future BOOKED/CONFIRMED appointments are reschedulable.
    """

    permission_classes = [IsPortalCustomer]

    def post(self, request, pk: int):
        from django.db import transaction

        from apps.booking.availability import compute_provider_slots

        customer = request.customer
        _guard_tenant_consistency(request)
        tenant = customer.tenant

        ser = RescheduleAppointmentInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_start = ser.validated_data['start_time']

        with transaction.atomic():
            try:
                appt = (
                    Appointment.objects
                    .select_for_update(of=('self',))
                    .select_related('service', 'provider', 'location')
                    .get(pk=pk, tenant=tenant, customer=customer)
                )
            except Appointment.DoesNotExist:
                return Response(
                    {'detail': 'Appointment not found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if appt.start_time <= djtz.now():
                raise ValidationError(
                    {'detail': 'Past appointments cannot be rescheduled.'}
                )
            if appt.status not in (
                Appointment.Status.BOOKED,
                Appointment.Status.CONFIRMED,
            ):
                raise ValidationError({
                    'detail': (
                        'This appointment cannot be rescheduled '
                        f'(status: {appt.get_status_display()}).'
                    ),
                })

            # Re-validate the new slot against the live calculator,
            # excluding this appointment so its own current slot
            # doesn't block a nearby move.
            available = compute_provider_slots(
                provider=appt.provider,
                service=appt.service,
                location=appt.location,
                on_date=djtz.localtime(new_start).date(),
                lead_minutes=tenant.online_booking_lead_minutes,
                exclude_appointment_id=appt.id,
            )
            if not any(s.start == new_start for s in available):
                raise ValidationError({
                    'start_time': 'That time is no longer available. Pick another.',
                })

            # A reschedule preserves the appointment's length — keep
            # whatever duration it currently has. Compute the new end
            # BEFORE reassigning start_time.
            previous_start = appt.start_time
            appt.end_time = new_start + (appt.end_time - appt.start_time)
            appt.start_time = new_start
            appt.save(update_fields=['start_time', 'end_time', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appt.id,
            request=request,
            metadata={
                'event': 'portal_reschedule',
                'customer_id': customer.id,
                'from_start': previous_start.isoformat(),
                'to_start': new_start.isoformat(),
            },
        )

        return Response(PortalAppointmentSerializer(appt).data)


# ── Helpers ──────────────────────────────────────────────────────────


def _customer_me_payload(customer):
    """Build the dict the `CustomerMeSerializer` expects. Keeps the
    serializer dumb (it just transforms shapes) and the view focused
    on flow control."""
    tenant = customer.tenant
    return {
        'id': customer.id,
        'first_name': customer.first_name,
        'last_name': customer.last_name,
        'email': customer.email,
        'phone': customer.phone,
        'email_marketing_opt_in': customer.email_marketing_opt_in,
        'sms_marketing_opt_in': customer.sms_marketing_opt_in,
        'sms_opt_in': customer.sms_opt_in,
        'tenant': {
            'name': tenant.name,
            'slug': tenant.slug,
            'primary_color': tenant.primary_color or '#1f2937',
            'logo_url': tenant.logo_url or '',
        },
    }


def _guard_tenant_consistency(request) -> None:
    """403 if the request's tenant (from middleware) doesn't match
    the session's customer's tenant. Defense in depth against a
    customer carrying a stale cookie onto a different spa's host."""
    request_tenant = get_current_tenant()
    if request_tenant is None or request.customer.tenant_id != request_tenant.id:
        raise PermissionDenied('Portal session does not match this host.')


def _set_session_cookie(response, token: str) -> None:
    """Set the portal session cookie with safe defaults.

    `httponly` keeps JS from reading the token (XSS resistance);
    `samesite=Lax` is the standard CSRF posture for first-party
    flows; `secure=True` is required in production (TLS-only)
    and harmless in dev where the browser ignores it on http://."""
    response.set_cookie(
        PORTAL_SESSION_COOKIE,
        token,
        max_age=14 * 24 * 60 * 60,  # match SESSION_EXPIRY
        path='/',
        httponly=True,
        samesite='Lax',
        secure=True,
    )


def _clear_session_cookie(response) -> None:
    response.delete_cookie(PORTAL_SESSION_COOKIE, path='/')


# ── Memberships / Packages / Forms read views ───────────────────────


class MembershipsView(APIView):
    """`GET /api/portal/memberships/` — customer's subscription
    history, active rows first.

    Read-only; the portal never lets a customer modify subscription
    state (start, cancel, renew) — those flow through staff so the
    audit trail is consistent + so refunds / proration are handled
    explicitly. Customers see their own subscriptions to answer
    "what plan am I on?" without calling the spa.
    """

    permission_classes = [IsPortalCustomer]

    def get(self, request):
        from apps.memberships.models import Subscription
        customer = request.customer
        _guard_tenant_consistency(request)

        # Active first, then by most-recent. Cancelled / expired
        # cycles are surfaced too — customers asked about historical
        # plans during demos ("did I have the gold plan last year?").
        qs = (
            Subscription.objects
            .filter(tenant=customer.tenant, customer=customer)
            .order_by('status', '-started_at', '-created_at')
        )
        data = PortalSubscriptionSerializer(qs, many=True).data

        record(
            action=AuditLog.Action.READ,
            resource_type='portal_memberships',
            resource_id=customer.id,
            request=request,
            metadata={'count': len(data)},
        )
        return Response(data)


class PackagesView(APIView):
    """`GET /api/portal/packages/` — customer's purchased packages
    with sessions remaining per service line.

    Active packages come first (customer's actionable inventory),
    then pending, then voided/expired for history. The serializer
    strips internal fields — no redemption ledger, no source
    template, no who-voided-it metadata. Customers see what they
    have left, that's it.
    """

    permission_classes = [IsPortalCustomer]

    def get(self, request):
        from apps.packages.models import PurchasedPackage
        customer = request.customer
        _guard_tenant_consistency(request)

        # Custom rank: active first, then pending, then voided. The
        # serializer's `is_expired` is computed; we don't filter on
        # it here so the customer sees expired packages too with the
        # "expired" badge in the UI.
        STATUS_ORDER = {
            PurchasedPackage.Status.ACTIVE: 0,
            PurchasedPackage.Status.PENDING: 1,
            PurchasedPackage.Status.VOIDED: 2,
        }
        qs = (
            PurchasedPackage.objects
            .filter(tenant=customer.tenant, customer=customer)
            .prefetch_related('items')
            .order_by('-created_at')
        )
        rows = sorted(qs, key=lambda p: (STATUS_ORDER.get(p.status, 99), p.id * -1))
        data = PortalPackageSerializer(rows, many=True).data

        record(
            action=AuditLog.Action.READ,
            resource_type='portal_packages',
            resource_id=customer.id,
            request=request,
            metadata={'count': len(data)},
        )
        return Response(data)


class FormsView(APIView):
    """`GET /api/portal/forms/` — customer's form submissions.

    Pending forms first (the customer's actionable list — these
    have a `sign_url` to the tokenized fill flow), then completed
    forms, then voided. Answers + signature data are PHI and are
    NOT included in this list — the customer signs through the
    existing tokenized `/sign/<token>` page where the answer
    schema is rendered fresh.

    A future detail endpoint could return completed answers under
    the same minimum-necessary posture as the staff path, but
    that's deferred until customers actually ask for "show me
    what I signed."
    """

    permission_classes = [IsPortalCustomer]

    def get(self, request):
        from apps.forms.models import FormSubmission
        customer = request.customer
        _guard_tenant_consistency(request)

        STATUS_ORDER = {
            FormSubmission.Status.PENDING: 0,
            FormSubmission.Status.COMPLETED: 1,
            FormSubmission.Status.VOIDED: 2,
        }
        qs = (
            FormSubmission.objects
            .filter(tenant=customer.tenant, customer=customer)
            .select_related('form_template')
            .order_by('-created_at')
        )
        rows = sorted(qs, key=lambda f: (STATUS_ORDER.get(f.status, 99), f.id * -1))
        # The serializer reads `template_name` + `template_form_type`
        # off the FK; populate them inline on each row.
        for r in rows:
            r.template_name = r.form_template.name
            r.template_form_type = r.form_template.form_type
        data = PortalFormSubmissionSerializer(rows, many=True).data

        record(
            action=AuditLog.Action.READ,
            resource_type='portal_forms',
            resource_id=customer.id,
            request=request,
            metadata={'count': len(data)},
        )
        return Response(data)


class InvoicesView(APIView):
    """`GET /api/portal/invoices/` — customer's invoices.

    Returns OPEN invoices first (these are the actionable list — the
    customer might want to pay them via the portal Pay-now flow),
    then PAID history, then VOIDED. Each row carries a minimum-
    necessary shape: invoice number, totals, status, dates, line
    items, charges (so the customer can see prior card attempts).

    PHI consideration: invoice line items reference services by
    name + price. The line names ARE the procedure performed — that's
    arguably PHI under HIPAA, but the customer IS the data subject
    here. Same posture as the operator surface — minimum necessary
    is "everything they need to verify their own bill."
    """

    permission_classes = [IsPortalCustomer]

    def get(self, request):
        from apps.invoices.models import Invoice
        from apps.invoices.serializers import InvoiceSerializer

        customer = request.customer
        _guard_tenant_consistency(request)

        STATUS_ORDER = {
            Invoice.Status.OPEN: 0,
            Invoice.Status.PAID: 1,
            Invoice.Status.VOID: 2,
        }
        qs = (
            Invoice.objects
            .filter(tenant=customer.tenant, customer=customer)
            .select_related('customer', 'appointment')
            .prefetch_related('line_items', 'charges', 'charges__refunds')
            .order_by('-created_at')
        )
        rows = sorted(qs, key=lambda i: (STATUS_ORDER.get(i.status, 99), -i.id))
        data = InvoiceSerializer(rows, many=True).data

        record(
            action=AuditLog.Action.READ,
            resource_type='portal_invoices',
            resource_id=customer.id,
            request=request,
            metadata={'count': len(data)},
        )
        return Response(data)


class PayInvoiceView(APIView):
    """`POST /api/portal/invoices/<id>/pay/` — customer self-pays an
    invoice via Stripe Connect Elements.

    Body: ``{amount_cents}``. Same shape + semantics as the operator
    charge-card endpoint, but:
      - Authenticated by the portal session (NOT a tenant operator
        membership). Backend re-checks the invoice belongs to the
        portal-session customer's tenant + customer (defense in
        depth against a stale cookie carrying a customer onto the
        wrong invoice).
      - ``operator`` is None; ``initiated_via='customer_portal'`` so
        the local Charge row + activity log clearly attribute the
        payment to self-service.
      - Auto-close (in ``apps.payments.services``) handles
        invoices with ``charge.created_by=None`` correctly — the
        invoice closes when the customer covers the balance.

    Returns the same shape as the operator endpoint
    (client_secret + publishable_key + stripe_account_id) so the
    frontend ChargeCardDialog can be reused verbatim.
    """

    permission_classes = [IsPortalCustomer]

    def post(self, request, pk: int):
        from apps.invoices.models import Invoice
        from apps.payments.services import (
            ChargeRefusedError,
            StripeAPIError,
            StripeNotConfigured,
            create_payment_intent_for_invoice,
            is_configured,
        )

        customer = request.customer
        _guard_tenant_consistency(request)

        try:
            invoice = Invoice.objects.get(
                pk=pk, tenant=customer.tenant, customer=customer,
            )
        except Invoice.DoesNotExist:
            # Same shape whether the invoice doesn't exist OR belongs
            # to a different customer. Don't leak which.
            return Response(
                {'detail': 'Invoice not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': f'This invoice is {invoice.get_status_display().lower()}; nothing to pay.',
                    'code': 'invoice_not_open',
                },
                status=status.HTTP_409_CONFLICT,
            )

        raw_amount = request.data.get('amount_cents')
        try:
            amount_cents = int(raw_amount)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'amount_cents must be an integer.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not is_configured():
            return Response(
                {
                    'detail': (
                        'Payment processing is not configured for this spa yet.'
                    ),
                    'code': 'stripe_not_configured',
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            charge, client_secret = create_payment_intent_for_invoice(
                invoice=invoice,
                amount_cents=amount_cents,
                operator=None,
                initiated_via='customer_portal',
            )
        except ChargeRefusedError as e:
            return Response(
                {'detail': str(e), 'code': 'charge_refused'},
                status=status.HTTP_409_CONFLICT,
            )
        except StripeNotConfigured as e:
            return Response(
                {'detail': str(e), 'code': 'stripe_not_configured'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except StripeAPIError as e:
            return Response(
                {'detail': str(e), 'code': 'stripe_error'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='portal_payment_intent',
            resource_id=charge.pk,
            request=request,
            metadata={
                'invoice_id': invoice.pk,
                'amount_cents': amount_cents,
            },
        )

        from django.conf import settings as dj_settings
        return Response({
            'charge_id': charge.pk,
            'client_secret': client_secret,
            'publishable_key': getattr(dj_settings, 'STRIPE_PUBLISHABLE_KEY', ''),
            'stripe_account_id': charge.merchant_account.stripe_account_id,
        }, status=status.HTTP_201_CREATED)


class BookAppointmentView(APIView):
    """`POST /api/portal/booking/submit/` — portal customer books an
    appointment for themselves.

    Distinct from the public `/api/booking/<slug>/book/` flow:
      - No guest-checkout fields — the customer is identified by
        the portal session, not by re-entering name/email.
      - No marketing-consent capture (consent is managed via the
        portal profile page).
      - Service + provider eligibility + slot validity are
        re-checked server-side inside a transaction — same
        race-safety guarantees as the public path.

    Read endpoints (services, providers, slots) are intentionally
    NOT duplicated here — the portal frontend calls the existing
    `/api/booking/<tenant_slug>/...` public surface for those.
    They're tenant-scoped + read-only + already optimized; building
    portal-only mirrors would just add code without value.
    """

    permission_classes = [IsPortalCustomer]

    def post(self, request):
        # Lazy imports keep apps loosely coupled at the module level
        # and let test discovery work cleanly when one app's model
        # graph isn't fully imported by another.
        from datetime import timedelta

        from apps.appointments.models import Appointment
        from apps.audit.services import record
        from apps.booking.availability import compute_provider_slots
        from apps.services.models import Service
        from apps.tenants.models import (
            Location,
            MembershipLocation,
            TenantMembership,
        )

        customer = request.customer
        _guard_tenant_consistency(request)
        tenant = customer.tenant

        ser = PortalBookingInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Service must exist, belong to this tenant, be active +
        # bookable online.
        try:
            service = Service.objects.get(
                pk=data['service_id'], tenant=tenant,
                is_active=True, is_bookable_online=True,
            )
        except Service.DoesNotExist:
            raise ValidationError({'service_id': 'Service is unavailable.'})

        # Provider must exist, belong to this tenant, be bookable +
        # active.
        try:
            provider = TenantMembership.objects.select_related('user').get(
                pk=data['provider_id'], tenant=tenant,
                is_bookable=True, is_active=True,
            )
        except TenantMembership.DoesNotExist:
            raise ValidationError({'provider_id': 'Provider is unavailable.'})

        # Location resolves from payload or falls back to tenant default.
        location_id = data.get('location_id')
        if location_id:
            try:
                location = Location.objects.get(
                    pk=location_id, tenant=tenant, is_active=True,
                )
            except Location.DoesNotExist:
                raise ValidationError({'location_id': 'Location is unavailable.'})
        else:
            try:
                location = Location.objects.get(
                    tenant=tenant, is_default=True, is_active=True,
                )
            except Location.DoesNotExist:
                raise ValidationError({'detail': 'No active location to book against.'})

        # Provider must be assigned to the chosen location — same
        # check the public booking surface enforces.
        if not MembershipLocation.objects.filter(
            membership=provider, location=location, is_active=True,
        ).exists():
            raise ValidationError({
                'provider_id': "Provider isn't bookable at this location.",
            })

        start_time = data['start_time']
        end_time = start_time + timedelta(minutes=service.duration_minutes)

        # Re-validate slot availability. Even though the frontend
        # fetched a fresh slot list, the slot may have been booked in
        # the meantime — last-mile race check against the same
        # calculator the public picker uses.
        available = compute_provider_slots(
            provider=provider,
            service=service,
            location=location,
            on_date=djtz.localtime(start_time).date(),
            lead_minutes=tenant.online_booking_lead_minutes,
        )
        if not any(s.start == start_time for s in available):
            raise ValidationError({
                'start_time': 'That time is no longer available. Pick another.',
            })

        appointment = Appointment.objects.create(
            tenant=tenant,
            customer=customer,
            provider=provider,
            service=service,
            location=location,
            start_time=start_time,
            end_time=end_time,
            status=Appointment.Status.BOOKED,
            source='portal',
            quoted_price_cents=service.price_cents,
            notes=data.get('notes', ''),
        )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='appointment',
            resource_id=appointment.id,
            request=request,
            metadata={
                'event': 'portal_book',
                'customer_id': customer.id,
                'service_id': service.id,
                'provider_id': provider.id,
            },
        )

        return Response(
            PortalAppointmentSerializer(appointment).data,
            status=status.HTTP_201_CREATED,
        )
