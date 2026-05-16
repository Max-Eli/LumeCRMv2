"""Form-templates API.

Endpoints under `/api/form-templates/`:

    GET    /api/form-templates/         List (filters: ?form_type=, ?active=)
    POST   /api/form-templates/         Create (owner+manager via MANAGE_TENANT_SETTINGS)
    GET    /api/form-templates/{id}/    Retrieve
    PATCH  /api/form-templates/{id}/    Update — bumps `version` when schema changes
    DELETE                              Disallowed; soft-delete via is_active=false

`set_service_ids` on PATCH/POST replaces the consent form's service
mapping (full-replace; mirrors `set_location_ids` on memberships).
Intake forms reject service mappings — they auto-assign via the
"first appointment ever" rule, not service mapping.

Tenant scoping via `for_current_tenant()`. Hard delete intentionally
not exposed — submissions FK into templates and the audit trail must
survive. Operators deactivate (`is_active=false`) to retire a template.
"""

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone as djtz
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.api_permissions import IsTenantStaff
from apps.tenants.context import get_current_tenant
from apps.tenants.permissions import P

from .models import FormSubmission, FormTemplate, ServiceFormAssignment
from .serializers import (
    FormSubmissionDetailSerializer,
    FormSubmissionListSerializer,
    FormSubmissionVoidSerializer,
    FormTemplateSerializer,
    PublicFormSignSerializer,
    PublicFormSubmissionSerializer,
)


class FormTemplateViewSet(viewsets.ModelViewSet):
    """CRUD for form templates, scoped to the current tenant.

    Permission model: read open to anyone in the tenant (front-desk
    needs to see what forms are configured); write gated by
    `MANAGE_TENANT_SETTINGS` (owner-only). Mirrors the locations API.

    `version` auto-bumps when the schema actually changes — saving a
    template with the same schema (e.g. just renaming) leaves the
    version alone so submissions don't snapshot a "no-op" version.
    """

    serializer_class = FormTemplateSerializer
    permission_classes = [IsTenantStaff]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        qs = FormTemplate.objects.for_current_tenant().prefetch_related(
            'service_assignments',
        )
        params = self.request.query_params
        form_type = (params.get('form_type') or '').strip().lower()
        if form_type in {'intake', 'consent'}:
            qs = qs.filter(form_type=form_type)
        active_param = (params.get('active') or '').strip().lower()
        if active_param in {'true', '1'}:
            qs = qs.filter(is_active=True)
        return qs

    # ── Permission gate (write-only) ────────────────────────────────

    def _check_write_permission(self, request):
        if request.user.is_superuser:
            return
        membership = getattr(request, 'tenant_membership', None)
        if not membership or not membership.has(P.MANAGE_TENANT_SETTINGS):
            raise PermissionDenied(
                'You do not have permission to manage form templates.',
            )

    # ── Create ──────────────────────────────────────────────────────

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        self._check_write_permission(request)
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service_ids = serializer.validated_data.pop('set_service_ids', None)

        with transaction.atomic():
            instance = FormTemplate.objects.create(
                tenant=tenant,
                **serializer.validated_data,
            )
            if service_ids:
                ServiceFormAssignment.objects.bulk_create([
                    ServiceFormAssignment(
                        tenant=tenant,
                        form_template=instance,
                        service=service,
                    )
                    for service in service_ids
                ])

        record(
            action=AuditLog.Action.CREATE,
            resource_type='form_template',
            resource_id=instance.id,
            request=request,
            metadata={
                'name': instance.name,
                'form_type': instance.form_type,
                'recurrence': instance.recurrence,
                'field_count': len(instance.schema.get('fields', [])),
                'service_ids': sorted(s.id for s in (service_ids or [])),
            },
        )
        return Response(
            self.get_serializer(instance).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Update ──────────────────────────────────────────────────────

    def update(self, request, *args, **kwargs):
        self._check_write_permission(request)
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        service_ids = serializer.validated_data.pop('set_service_ids', None)

        # Detect schema change so version-bump is honest. Comparing the
        # canonical normalized form (from validate_schema) against the
        # stored value avoids false bumps from key reordering.
        new_schema = serializer.validated_data.get('schema', instance.schema)
        schema_changed = new_schema != instance.schema

        # Snapshot pre-save values for the audit log. Captured BEFORE
        # serializer.save() because save() mutates `instance` in place
        # — and the later refresh_from_db (after the version update)
        # would otherwise overwrite our "old" reading of these.
        old_version = instance.version
        old_field_count = len(instance.schema.get('fields', []))

        with transaction.atomic():
            updated = serializer.save()
            if schema_changed:
                FormTemplate.objects.filter(pk=updated.pk).update(
                    version=old_version + 1,
                )
                updated.refresh_from_db()

            if service_ids is not None:
                _replace_service_assignments(updated, service_ids)

        new_field_count = len(updated.schema.get('fields', []))
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='form_template',
            resource_id=updated.id,
            request=request,
            metadata={
                'fields_changed': sorted(
                    k for k in serializer.validated_data.keys()
                    if k not in {'schema'}  # listed separately
                ),
                **(
                    {
                        'schema_changed': True,
                        'from_version': old_version,
                        'to_version': updated.version,
                        'from_field_count': old_field_count,
                        'to_field_count': new_field_count,
                    }
                    if schema_changed else {}
                ),
                **(
                    {'service_ids_replaced_to': sorted(s.id for s in service_ids)}
                    if service_ids is not None else {}
                ),
            },
        )
        return Response(self.get_serializer(updated).data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='form_template',
            resource_id=instance.id,
            request=request,
        )
        return Response(self.get_serializer(instance).data)


def _replace_service_assignments(template: FormTemplate, services) -> None:
    """Reconcile `ServiceFormAssignment` rows for a template to match
    the target service set. Hard-deletes removed assignments (no
    soft-delete needed — submissions point at the template directly,
    not at the service mapping). Idempotent."""
    target_ids = {s.id for s in services}
    existing = {
        sa.service_id: sa
        for sa in ServiceFormAssignment.objects.filter(form_template=template)
    }
    # Remove no-longer-mapped services.
    to_delete = set(existing.keys()) - target_ids
    if to_delete:
        ServiceFormAssignment.objects.filter(
            form_template=template, service_id__in=to_delete,
        ).delete()
    # Add new mappings.
    to_create = target_ids - set(existing.keys())
    if to_create:
        ServiceFormAssignment.objects.bulk_create([
            ServiceFormAssignment(
                tenant=template.tenant,
                form_template=template,
                service_id=sid,
            )
            for sid in to_create
        ])


# ── Tenant-scoped form submissions API ─────────────────────────────


class FormSubmissionViewSet(viewsets.ReadOnlyModelViewSet):
    """List + retrieve form submissions, scoped to the current tenant.

    Endpoints:
      - `GET /api/form-submissions/` — list, supports `?customer=`,
        `?appointment=`, `?status=` filters.
      - `GET /api/form-submissions/{id}/` — detail (PHI; gated).
      - `POST /api/form-submissions/{id}/void/` — operator voids
        with a required reason. Owner+manager only.

    Permission model:
      - **List + retrieve**: open to anyone in the tenant. The list
        serializer omits PHI; the detail serializer returns it.
        Front desk needs the list to prompt clients but doesn't need
        to read answers — a polish refinement is to gate the detail
        endpoint behind `VIEW_CLIENT_PHI` (clinical roles + assigned
        provider). v1 leaves detail open to authenticated tenant
        members; this is acceptable because submissions are still
        scoped per-tenant and audit-logged on read.
      - **Void**: owner + manager via `MANAGE_STAFF`. Voiding doesn't
        delete; it marks the submission invalidated and excludes it
        from "is the form signed?" rules.

    Hard delete intentionally not exposed — submissions are signed
    consent records; deletion would destroy audit trail. See ADR
    0011 for the design.
    """

    permission_classes = [IsTenantStaff]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        qs = FormSubmission.objects.for_current_tenant().select_related(
            'form_template', 'customer', 'appointment',
        ).order_by('-created_at')
        params = self.request.query_params
        if customer := params.get('customer'):
            qs = qs.filter(customer_id=customer)
        if appointment := params.get('appointment'):
            qs = qs.filter(appointment_id=appointment)
        if submission_status := params.get('status'):
            qs = qs.filter(status=submission_status)
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return FormSubmissionDetailSerializer
        return FormSubmissionListSerializer

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        record(
            action=AuditLog.Action.READ,
            resource_type='form_submission_list',
            request=request,
            metadata={
                'count': len(response.data),
                'customer': request.query_params.get('customer', ''),
                'appointment': request.query_params.get('appointment', ''),
                'status': request.query_params.get('status', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Audit-log every detail read because `answers` and
        # `signature_data` are PHI. HIPAA §164.312(b) — every access
        # to a patient consent record is traceable.
        record(
            action=AuditLog.Action.READ,
            resource_type='form_submission',
            resource_id=instance.id,
            request=request,
            metadata={
                'customer_id': instance.customer_id,
                'template_id': instance.form_template_id,
                'status': instance.status,
            },
        )
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, *args, **kwargs):
        """Render this submission as a PDF and stream it as an attachment.

        Same pattern as the invoice PDF endpoint (ADR 0018) — on-demand
        projection of the row, no caching. Pending submissions return
        400 (nothing to render before the signature). SIGNED and
        VOIDED submissions both render; voided shows a red VOIDED
        banner at the top.

        Permission: any authenticated tenant member (matches list +
        retrieve). The signature + answers are PHI; every PDF download
        writes an `AuditLog` entry with the submission id + customer id
        for HIPAA §164.312(b) coverage.
        """
        from .services import render_form_submission_pdf

        instance = self.get_object()
        try:
            pdf_bytes = render_form_submission_pdf(instance)
        except ValueError as e:
            raise ValidationError({'detail': str(e)})

        record(
            action=AuditLog.Action.READ,
            resource_type='form_submission_pdf',
            resource_id=instance.id,
            request=request,
            metadata={
                'customer_id': instance.customer_id,
                'template_id': instance.form_template_id,
                'bytes': len(pdf_bytes),
            },
        )

        filename = (
            f'{instance.form_template.name} — {instance.pk}.pdf'
            .replace('/', '-')
        )
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=['post'])
    def void(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            membership = getattr(request, 'tenant_membership', None)
            if not membership or not membership.has(P.MANAGE_STAFF):
                raise PermissionDenied(
                    'You do not have permission to void form submissions.',
                )
        instance = self.get_object()
        if instance.status == FormSubmission.Status.VOIDED:
            return Response(
                {'detail': 'Submission is already voided.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = FormSubmissionVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = instance.status
        with transaction.atomic():
            instance.status = FormSubmission.Status.VOIDED
            instance.voided_at = djtz.now()
            instance.voided_by = request.user
            instance.voided_reason = serializer.validated_data['reason']
            instance.save(update_fields=[
                'status', 'voided_at', 'voided_by', 'voided_reason', 'updated_at',
            ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='form_submission',
            resource_id=instance.id,
            request=request,
            metadata={
                'from_status': old_status,
                'to_status': FormSubmission.Status.VOIDED,
                'reason': instance.voided_reason,
            },
        )
        return Response(FormSubmissionDetailSerializer(instance).data)

    @action(detail=True, methods=['post'])
    def email(self, request, *args, **kwargs):
        """`POST /api/form-submissions/{id}/email/` — operator-
        initiated PHI delivery to the customer's email on file.
        See ADR 0012.

        Owner+manager only via `MANAGE_STAFF` (matches the void
        gate; both are operator actions touching PHI).

        Audit log records that an email was sent + the recipient's
        domain — never the full address. Recipient address lives in
        the email body itself + the customer record; the audit log
        is its own queryable surface and shouldn't accumulate raw
        email addresses (which become PHI when paired with treatment
        context).
        """
        if not request.user.is_superuser:
            membership = getattr(request, 'tenant_membership', None)
            if not membership or not membership.has(P.MANAGE_STAFF):
                raise PermissionDenied(
                    'You do not have permission to email form submissions.',
                )
        instance = self.get_object()

        from .services import EmailSendError, email_signed_copy
        try:
            recipient = email_signed_copy(instance, sent_by=request.user)
        except EmailSendError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Domain-only logging — see ADR 0012.
        recipient_domain = (
            recipient.split('@')[1].lower() if '@' in recipient else 'unknown'
        )
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='form_submission',
            resource_id=instance.id,
            request=request,
            metadata={
                'event': 'emailed_to_customer',
                'template_id': instance.form_template_id,
                'template_name': instance.form_template.name,
                'recipient_email_domain': recipient_domain,
            },
        )
        return Response({
            'detail': f'Signed copy emailed to {recipient}.',
            'recipient': recipient,
        })


# ── Public tokenized fill flow (unauthenticated) ───────────────────


class PublicFormSignView(APIView):
    """`GET / POST /api/forms/sign/<token>/` — public form fill page.

    No authentication. The token IS the security boundary; ADR 0011
    explains the rationale (high-entropy + URL path placement +
    no CSRF since there's no session to ride).

    GET returns the schema snapshot + status. POST submits answers +
    signature, transitions `pending` → `completed` exactly once.
    Subsequent POSTs return 409.

    Audit log on signing captures the IP + user-agent (NOT a user;
    no auth context). HIPAA §164.312(b) audit trail.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # Disable session auth + DRF auth — no CSRF either

    def get(self, request, token, *args, **kwargs):
        submission = self._get_submission(token)
        return Response(PublicFormSubmissionSerializer(submission).data)

    def post(self, request, token, *args, **kwargs):
        submission = self._get_submission(token)
        if submission.status == FormSubmission.Status.COMPLETED:
            return Response(
                {'detail': 'This form has already been signed.'},
                status=status.HTTP_409_CONFLICT,
            )
        if submission.status == FormSubmission.Status.VOIDED:
            return Response(
                {'detail': 'This form has been voided. Contact the spa for a new link.'},
                status=status.HTTP_410_GONE,
            )

        serializer = PublicFormSignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answers = serializer.validated_data['answers']
        signature_data = serializer.validated_data['signature_data']

        # Validate answers against the schema snapshot — required
        # fields populated; choice values matching options. Strict
        # because the snapshot is the contract the client agreed to.
        self._validate_answers_against_schema(answers, submission.schema_snapshot)

        # Capture audit info from the request, never trusting the
        # payload to supply IP / user-agent (would defeat the audit).
        ip = _client_ip(request)
        user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:1000]

        with transaction.atomic():
            submission.status = FormSubmission.Status.COMPLETED
            submission.answers = answers
            submission.signature_data = signature_data
            submission.signed_at = djtz.now()
            submission.ip_address = ip
            submission.user_agent = user_agent
            submission.save(update_fields=[
                'status', 'answers', 'signature_data',
                'signed_at', 'ip_address', 'user_agent', 'updated_at',
            ])

        # Audit log entry. user=None — the signer is unauthenticated.
        # IP + user-agent + length-of-signature in metadata. NO PHI in
        # metadata (the answers are in the row itself; logs don't
        # need them).
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='form_submission',
            resource_id=submission.id,
            tenant=submission.tenant,  # no request.tenant since unauth
            user=None,
            request=request,
            metadata={
                'from_status': 'pending',
                'to_status': 'completed',
                'ip_recorded': True,
                'signature_bytes': len(signature_data),
            },
        )
        return Response(PublicFormSubmissionSerializer(submission).data)

    # ── Helpers ────────────────────────────────────────────────────

    def _get_submission(self, token):
        from django.http import Http404
        try:
            return (
                FormSubmission.objects
                .select_related('form_template', 'customer', 'tenant')
                .get(token=token)
            )
        except FormSubmission.DoesNotExist:
            raise Http404('No such form.')

    def _validate_answers_against_schema(self, answers: dict, schema: dict):
        """Reject if a required field is missing or a choice value
        isn't one of the options. Mirrors the schema-validation rules
        defined for templates."""
        from rest_framework.exceptions import ValidationError as DRFValidationError

        fields = schema.get('fields', [])
        for field in fields:
            field_id = field.get('id')
            field_type = field.get('type')
            required = field.get('required', False)
            value = answers.get(field_id)

            if required:
                if field_type == 'signature':
                    # Signature comes through a separate top-level
                    # `signature_data` key, not in `answers`. The
                    # POST handler verifies signature_data exists.
                    continue
                if value in (None, '', []):
                    raise DRFValidationError({
                        'answers': f'Field "{field_id}" is required.',
                    })

            if field_type in {'choice_single', 'choice_multiple'} and value not in (None, ''):
                allowed_values = {opt['value'] for opt in field.get('options', [])}
                if field_type == 'choice_single':
                    if value not in allowed_values:
                        raise DRFValidationError({
                            'answers': f'Field "{field_id}": "{value}" is not a valid option.',
                        })
                else:
                    if not isinstance(value, list):
                        raise DRFValidationError({
                            'answers': f'Field "{field_id}" must be an array of selected values.',
                        })
                    for v in value:
                        if v not in allowed_values:
                            raise DRFValidationError({
                                'answers': f'Field "{field_id}": "{v}" is not a valid option.',
                            })


def _client_ip(request) -> str | None:
    """Best-effort client IP extraction.

    Mirrors `apps.audit.services._client_ip` — checks
    `X-Forwarded-For` first (production behind ALB), falls back to
    `REMOTE_ADDR`. Captured for HIPAA audit; never trusted as
    authentication.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
