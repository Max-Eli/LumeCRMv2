"""Chart-notes API.

URL surface (under `/api/`):

    GET    /chart-notes/?customer=<id>     List a customer's notes
    POST   /chart-notes/                   Sign a new note
    GET    /chart-notes/<id>/              Retrieve one
    PATCH  /chart-notes/<id>/              Edit body (within window only)

Permission gating:
  - List + retrieve: `VIEW_CHART` (provider, owner, manager).
  - Create + edit: `SIGN_CHART` (same default holders).
  - Edit additionally requires the caller be the original author
    AND the 60-min edit window be open.

Audit: every read writes an `AuditLog` entry; create + edit too.
Body length is captured in metadata; the body itself never leaks
into the audit log.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.customers.models import Customer
from apps.tenants.context import get_current_tenant
from apps.tenants.permissions import P

from .models import ChartNote
from .permissions import ChartNoteWritePermission
from .serializers import (
    ChartNoteAddendumCreateSerializer,
    ChartNoteCreateSerializer,
    ChartNoteSerializer,
    ChartNoteUpdateSerializer,
    ChartNoteVoidSerializer,
)


class ChartNoteViewSet(viewsets.ModelViewSet):
    """CRUD for chart notes, scoped per tenant.

    DELETE intentionally not exposed — chart notes are append-only
    after the edit window. Voiding (with reason) is the v2 path
    via `EDIT_SIGNED_CHART`; v1 has no way to delete.
    """

    permission_classes = [ChartNoteWritePermission]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        qs = (
            ChartNote.objects
            .for_current_tenant()
            .select_related(
                'customer',
                'appointment', 'appointment__service',
                'author', 'author__user', 'author__job_title',
                'voided_by', 'voided_by__user',
                'parent_note',
            )
        )
        params = self.request.query_params
        customer_param = (params.get('customer') or '').strip()
        if customer_param:
            qs = qs.filter(customer_id=customer_param)
        appointment_param = (params.get('appointment') or '').strip()
        if appointment_param:
            qs = qs.filter(appointment_id=appointment_param)

        # Voided notes are included by default so the UI can render
        # them struck-through (the truthful state is more useful to
        # a clinical reviewer than hiding them). Pass
        # `?include_voided=false` to filter them out for an everyday
        # treatment-history read.
        include_voided = (params.get('include_voided') or 'true').strip().lower()
        if include_voided in ('false', '0', 'no'):
            qs = qs.filter(is_voided=False)
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return ChartNoteCreateSerializer
        if self.action in ('update', 'partial_update'):
            return ChartNoteUpdateSerializer
        return ChartNoteSerializer

    # ── List + retrieve ─────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        record(
            action=AuditLog.Action.READ,
            resource_type='chart_note_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'customer_id': request.query_params.get('customer', ''),
                'appointment_id': request.query_params.get('appointment', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='chart_note',
            resource_id=instance.pk,
            request=request,
            metadata={
                'customer_id': instance.customer_id,
                'appointment_id': instance.appointment_id,
                # NO body / excerpt — see ADR 0015 audit-log shape.
            },
        )
        return Response(ChartNoteSerializer(instance).data)

    # ── Create (initial signing) ────────────────────────────────────

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        membership = getattr(request, 'tenant_membership', None)
        # Superusers may not have a tenant membership row but should
        # still be able to write for development convenience. For
        # actual tenanted users, we require the membership AND the
        # SIGN_CHART permission (the permission class already
        # enforced this; we re-resolve membership here to use as the
        # author).
        if membership is None and not request.user.is_superuser:
            raise PermissionDenied('No tenant membership for this user.')

        ser = ChartNoteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Resolve customer + optional appointment against the URL
        # tenant. Generic 400 responses don't disclose whether the
        # cross-tenant resource exists.
        try:
            customer = Customer.objects.get(pk=data['customer_id'], tenant=tenant)
        except Customer.DoesNotExist:
            raise ValidationError({'customer_id': 'Customer not found.'})

        appointment = None
        if data.get('appointment_id'):
            try:
                appointment = Appointment.objects.get(
                    pk=data['appointment_id'], tenant=tenant,
                    customer=customer,
                )
            except Appointment.DoesNotExist:
                raise ValidationError({
                    'appointment_id': (
                        'Appointment not found, or not belonging to this customer.'
                    ),
                })

        # Snapshot the author's clinical status at signing time.
        # Superusers (no membership) get author_was_clinical=False
        # since they're not a clinical role; the row's legal posture
        # is consistent with how the permission system treats them.
        author_was_clinical = bool(
            membership and membership.job_title_id
            and getattr(membership.job_title, 'is_clinical', False),
        )

        note = ChartNote.objects.create(
            tenant=tenant,
            customer=customer,
            appointment=appointment,
            body=data['body'],
            author=membership,
            author_was_clinical=author_was_clinical,
        )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='chart_note',
            resource_id=note.pk,
            request=request,
            metadata={
                'customer_id': customer.pk,
                'appointment_id': appointment.pk if appointment else None,
                'body_length_chars': len(data['body']),
                'author_was_clinical': author_was_clinical,
            },
        )

        return Response(
            ChartNoteSerializer(note).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Edit (within-window only) ───────────────────────────────────

    def update(self, request, *args, **kwargs):
        # PATCH-only — http_method_names excludes PUT.
        instance = self.get_object()
        membership = getattr(request, 'tenant_membership', None)

        # Voided notes are never editable, even within their original
        # edit window (a void supersedes all other state). The
        # within-window edit path also shouldn't be a way to revive
        # voided content.
        if instance.is_voided:
            raise PermissionDenied(
                'This note has been voided and cannot be edited. '
                'Sign a new note if additional context is needed.',
            )

        # Window + ownership gate. The permission class already
        # established the caller has SIGN_CHART; this is the
        # per-record check.
        if not request.user.is_superuser and not instance.can_be_edited_by(membership):
            if instance.is_locked:
                detail = (
                    'This chart note is locked. The edit window has '
                    'closed; addenda will be supported in a future release.'
                )
            else:
                detail = (
                    'Only the original author can edit a chart note '
                    'within the typo-correction window.'
                )
            raise PermissionDenied(detail)

        ser = ChartNoteUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_body = ser.validated_data['body']

        old_length = len(instance.body)
        instance.body = new_body
        instance.save(update_fields=['body', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='chart_note',
            resource_id=instance.pk,
            request=request,
            metadata={
                'customer_id': instance.customer_id,
                'appointment_id': instance.appointment_id,
                'editing_within_window': True,
                'body_length_chars': len(new_body),
                'previous_body_length_chars': old_length,
            },
        )

        return Response(ChartNoteSerializer(instance).data)

    # ── Addendum (Session 2) ────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def addendum(self, request, pk=None):
        """`POST /api/chart-notes/<id>/addendum/` — sign an addendum
        attached to a locked parent.

        Permission: SIGN_CHART (same as creating a top-level note).
        Validation: parent must be locked, not voided, and same
        tenant as the caller. Addenda cannot have addenda.
        """
        parent = self.get_object()  # ChartNoteWritePermission already ran
        membership = getattr(request, 'tenant_membership', None)
        if membership is None and not request.user.is_superuser:
            raise PermissionDenied('No tenant membership for this user.')

        # Threading rules from ADR 0015 § Session 2.
        if parent.parent_note_id is not None:
            raise ValidationError({
                'detail': (
                    'Addenda cannot have addenda. Add another addendum '
                    'to the original note instead.'
                ),
            })
        if parent.is_voided:
            raise ValidationError({
                'detail': (
                    'This note has been voided. Sign a new top-level '
                    'note instead of attaching an addendum.'
                ),
            })
        if not parent.is_locked:
            raise ValidationError({
                'detail': (
                    'Edit the original note instead — it is still in '
                    'the typo-correction window.'
                ),
            })

        ser = ChartNoteAddendumCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        body = ser.validated_data['body']

        author_was_clinical = bool(
            membership and membership.job_title_id
            and getattr(membership.job_title, 'is_clinical', False),
        )

        addendum = ChartNote.objects.create(
            tenant=parent.tenant,
            customer=parent.customer,
            appointment=parent.appointment,  # inherit; clinical context follows
            parent_note=parent,
            body=body,
            author=membership,
            author_was_clinical=author_was_clinical,
        )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='chart_note',
            resource_id=addendum.pk,
            request=request,
            metadata={
                'event': 'addendum_created',
                'parent_note_id': parent.pk,
                'customer_id': parent.customer_id,
                'appointment_id': parent.appointment_id,
                'body_length_chars': len(body),
                'author_was_clinical': author_was_clinical,
            },
        )

        return Response(
            ChartNoteSerializer(addendum).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Void (Session 2) ────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        """`POST /api/chart-notes/<id>/void/` — invalidate a note.

        Permission: EDIT_SIGNED_CHART (owner + manager by default).
        Validation: note must be locked (within-window edits should
        just edit instead) and not already voided. Reason required.

        One-way: there is no un-void path. If a void was a mistake,
        write a new top-level note explaining and referencing the
        voided record.
        """
        instance = self.get_object()
        membership = getattr(request, 'tenant_membership', None)

        # Permission gate: EDIT_SIGNED_CHART. The viewset's class-level
        # ChartNoteWritePermission only enforces SIGN_CHART; we tighten
        # here because voiding has a stronger gate than ordinary
        # signing. Superuser bypass for development convenience.
        if not request.user.is_superuser:
            if membership is None:
                raise PermissionDenied('No tenant membership for this user.')
            if not membership.has(P.EDIT_SIGNED_CHART):
                raise PermissionDenied(
                    'Voiding chart notes requires the EDIT_SIGNED_CHART '
                    'permission (owner or manager).',
                )

        # State guards.
        if instance.is_voided:
            raise ValidationError({
                'detail': 'This note is already voided.',
            })
        if not instance.is_locked:
            raise ValidationError({
                'detail': (
                    'Edit the note instead while it is still in the '
                    'typo-correction window. Voiding is for locked '
                    'notes only.'
                ),
            })

        ser = ChartNoteVoidSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data['reason']

        instance.is_voided = True
        instance.voided_at = timezone.now()
        instance.voided_by = membership
        instance.voided_reason = reason
        instance.save(update_fields=[
            'is_voided', 'voided_at', 'voided_by', 'voided_reason',
            'updated_at',
        ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='chart_note',
            resource_id=instance.pk,
            request=request,
            metadata={
                'event': 'voided',
                'reason': reason,
                'parent_note_id': instance.parent_note_id,
                'customer_id': instance.customer_id,
                'appointment_id': instance.appointment_id,
            },
        )

        return Response(ChartNoteSerializer(instance).data)


# ── Treatment record templates + submissions ──────────────────────


from .models import (
    ServiceTreatmentTemplateAssignment,
    TreatmentRecord,
    TreatmentRecordTemplate,
)
from .serializers import (
    TreatmentRecordAddendumCreateSerializer,
    TreatmentRecordCreateSerializer,
    TreatmentRecordSerializer,
    TreatmentRecordTemplateSerializer,
    TreatmentRecordUpdateSerializer,
    TreatmentRecordVoidSerializer,
)


class _ManageTreatmentTemplatesPermission(ChartNoteWritePermission):
    """Permission for the TreatmentRecordTemplate viewset.

    Templates are catalog config (not PHI), so the permission gates
    map differently from chart records:
      - Reads: any authenticated tenant member (providers need to
        see what they'll be filling out).
      - Writes: MANAGE_SERVICES (same as catalog services / packages).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return membership.has(P.MANAGE_SERVICES)

    def has_object_permission(self, request, view, obj):
        membership = getattr(request, 'tenant_membership', None)
        if request.user.is_superuser:
            return True
        if not membership or obj.tenant_id != membership.tenant_id:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return membership.has(P.MANAGE_SERVICES)


class TreatmentRecordTemplateViewSet(viewsets.ModelViewSet):
    """`/api/treatment-record-templates/` — CRUD on the per-tenant
    templates that providers fill out at appointment time.

    Filters: `?service=<id>` returns templates assigned to that
    service. `?active=true|false` filters by activation state.
    """

    serializer_class = TreatmentRecordTemplateSerializer
    permission_classes = [_ManageTreatmentTemplatesPermission]

    def get_queryset(self):
        return (
            TreatmentRecordTemplate.objects
            .for_current_tenant()
            .prefetch_related('service_assignments')
        )

    def filter_queryset(self, queryset):
        params = self.request.query_params
        service_id = (params.get('service') or '').strip()
        active = (params.get('active') or '').strip().lower()
        if service_id:
            queryset = queryset.filter(
                service_assignments__service_id=service_id,
            ).distinct()
        if active in {'true', '1'}:
            queryset = queryset.filter(is_active=True)
        elif active in {'false', '0'}:
            queryset = queryset.filter(is_active=False)
        return queryset

    @action(detail=False, methods=['get'], url_path='starters')
    def starters(self, request):
        """`/api/treatment-record-templates/starters/` — read-only
        catalog of pre-built starter templates.

        Tenants don't get these pre-seeded into their DB. The picker
        UI fetches this list, the operator picks one + clicks
        "Use this template," and the frontend POSTs a regular
        create-template call with the starter's `name + schema`.
        After that, the tenant copy is fully editable + independent
        of the starter library.

        Returns a flat list grouped client-side by `category`.
        """
        from .starter_templates import STARTER_CATEGORIES, STARTER_TEMPLATES

        # Lightweight shape — no `fields` payload on the list since
        # it can be heavy. The detail endpoint below returns it.
        rows = [
            {
                'slug': s['slug'],
                'name': s['name'],
                'description': s['description'],
                'category': s['category'],
                'field_count': len(s['fields']),
            }
            for s in STARTER_TEMPLATES
        ]
        return Response({
            'categories': list(STARTER_CATEGORIES),
            'starters': rows,
        })

    @action(
        detail=False,
        methods=['get'],
        url_path=r'starters/(?P<slug>[a-z0-9-]+)',
    )
    def starter_detail(self, request, slug=None):
        """`/api/treatment-record-templates/starters/<slug>/` — full
        starter payload including the `fields` array. The picker
        dialog calls this for the preview pane."""
        from .starter_templates import starter_template_by_slug

        starter = starter_template_by_slug(slug)
        if starter is None:
            return Response(
                {'detail': 'Starter template not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({
            'slug': starter['slug'],
            'name': starter['name'],
            'description': starter['description'],
            'category': starter['category'],
            'fields': starter['fields'],
        })

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context.')
        # set_service_ids is a write-only convenience that maps to a
        # join table — pop it from the validated_data so save() doesn't
        # try to pass it to the model constructor.
        services = serializer.validated_data.pop('set_service_ids', None)
        instance = serializer.save(tenant=tenant)
        if services is not None:
            self._sync_service_assignments(instance, services)
        record(
            action=AuditLog.Action.CREATE,
            resource_type='treatment_template',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name, 'version': instance.version},
        )

    def perform_update(self, serializer):
        instance = self.get_object()
        old_schema = instance.schema
        services = serializer.validated_data.pop('set_service_ids', None)
        instance = serializer.save()
        # Bump version when the schema actually changed so submitted
        # records can pin which schema they were signed against.
        if 'schema' in serializer.validated_data and serializer.validated_data['schema'] != old_schema:
            instance.version = (instance.version or 0) + 1
            instance.save(update_fields=['version', 'updated_at'])
        if services is not None:
            self._sync_service_assignments(instance, services)
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='treatment_template',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'fields_changed': sorted(serializer.validated_data.keys()),
                'version': instance.version,
            },
        )

    def perform_destroy(self, instance):
        # Guard against deletion when records reference this template.
        # Soft-delete via is_active=False is the retirement path.
        record_count = TreatmentRecord.objects.filter(template=instance).count()
        if record_count > 0:
            raise ValidationError({
                'detail': (
                    f'Cannot delete: {record_count} treatment record(s) reference '
                    'this template. Mark it inactive instead.'
                ),
            })
        record(
            action=AuditLog.Action.DELETE,
            resource_type='treatment_template',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name},
        )
        instance.delete()

    def _sync_service_assignments(self, instance, services):
        """Replace the template's service assignments with `services`
        (a list of Service instances). Tenant scoping safety: drop
        any service whose tenant isn't ours."""
        valid_services = [s for s in services if s.tenant_id == instance.tenant_id]
        ServiceTreatmentTemplateAssignment.objects.filter(template=instance).delete()
        ServiceTreatmentTemplateAssignment.objects.bulk_create([
            ServiceTreatmentTemplateAssignment(
                tenant=instance.tenant, template=instance, service=svc,
            )
            for svc in valid_services
        ])


class TreatmentRecordViewSet(viewsets.ModelViewSet):
    """`/api/treatment-records/` — clinical record CRUD.

    Same lifecycle posture as ChartNote: create signs the record,
    edit window allows the body (`answers`) to be updated within
    EDIT_WINDOW_MINUTES, after that the record locks and the only
    way to extend is an addendum (separate row pointing at the
    parent). Voiding is a separate gated action.

    PHI-tier access: VIEW_CHART for reads, SIGN_CHART for create +
    edit, EDIT_SIGNED_CHART for void.
    """

    serializer_class = TreatmentRecordSerializer
    permission_classes = [ChartNoteWritePermission]

    def get_queryset(self):
        return (
            TreatmentRecord.objects
            .for_current_tenant()
            .select_related(
                'customer', 'appointment', 'appointment__service',
                'template',
                'author', 'author__user', 'author__job_title',
                'voided_by', 'voided_by__user',
            )
        )

    def filter_queryset(self, queryset):
        params = self.request.query_params
        customer_id = (params.get('customer') or '').strip()
        appointment_id = (params.get('appointment') or '').strip()
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        if appointment_id:
            queryset = queryset.filter(appointment_id=appointment_id)
        return queryset

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = (
            response.data.get('results', response.data)
            if isinstance(response.data, dict)
            else response.data
        )
        record(
            action=AuditLog.Action.READ,
            resource_type='treatment_record_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'customer': request.query_params.get('customer', ''),
                'appointment': request.query_params.get('appointment', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='treatment_record',
            resource_id=instance.id,
            request=request,
            metadata={'customer_id': instance.customer_id},
        )
        return Response(self.get_serializer(instance).data)

    def create(self, request, *args, **kwargs):
        ser = TreatmentRecordCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context.')

        membership = getattr(request, 'tenant_membership', None)
        if membership is None and not request.user.is_superuser:
            raise PermissionDenied('No tenant membership for this user.')

        # Tenant-scope every FK manually; we never trust ids in payload.
        try:
            customer = Customer.objects.for_current_tenant().get(pk=data['customer_id'])
        except Customer.DoesNotExist:
            raise ValidationError({'customer_id': 'Customer not found.'})
        try:
            template = TreatmentRecordTemplate.objects.for_current_tenant().get(
                pk=data['template_id'],
            )
        except TreatmentRecordTemplate.DoesNotExist:
            raise ValidationError({'template_id': 'Template not found.'})
        if not template.is_active:
            raise ValidationError({'template_id': 'Template is inactive.'})

        appointment = None
        if data.get('appointment_id'):
            try:
                appointment = Appointment.objects.for_current_tenant().get(
                    pk=data['appointment_id'],
                )
            except Appointment.DoesNotExist:
                raise ValidationError({'appointment_id': 'Appointment not found.'})

        # Snapshot the schema + version. The reader uses these to
        # render the record exactly as it was at signing time, even
        # if the template has since changed.
        instance = TreatmentRecord.objects.create(
            tenant=tenant,
            customer=customer,
            appointment=appointment,
            template=template,
            template_version_at_signing=template.version,
            schema_snapshot=template.schema,
            answers=data.get('answers', {}),
            author=membership,
            author_was_clinical=bool(
                membership and membership.job_title_id
                and membership.job_title.is_clinical
            ),
        )
        record(
            action=AuditLog.Action.CREATE,
            resource_type='treatment_record',
            resource_id=instance.id,
            request=request,
            metadata={
                'customer_id': customer.id,
                'appointment_id': appointment.id if appointment else None,
                'template_id': template.id,
                'template_version': template.version,
            },
        )
        return Response(
            self.get_serializer(instance).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        membership = getattr(request, 'tenant_membership', None)
        if not instance.can_be_edited_by(membership):
            raise PermissionDenied(
                'This treatment record can only be edited by the original '
                'author within the typo-correction window.',
            )
        ser = TreatmentRecordUpdateSerializer(
            data=request.data, partial=True,
        )
        ser.initial_data = request.data  # for the "extra-fields-rejected" guard
        ser.is_valid(raise_exception=True)
        instance.answers = ser.validated_data['answers']
        instance.save(update_fields=['answers', 'updated_at'])
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='treatment_record',
            resource_id=instance.id,
            request=request,
            metadata={
                'event': 'within_window_edit',
                'customer_id': instance.customer_id,
            },
        )
        return Response(self.get_serializer(instance).data)

    update = partial_update  # PUT == PATCH for this surface

    def destroy(self, request, *args, **kwargs):
        # Treatment records are append-only — destruction is via
        # void, not delete. 405 makes the rule explicit.
        return Response(
            {'detail': 'Treatment records cannot be deleted. Use void instead.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'], url_path='addendum')
    def addendum(self, request, pk=None):
        """Sign a new record that's an addendum to the locked
        parent. The parent must be locked (within-window edit
        applies before that) and not voided."""
        parent = self.get_object()
        membership = getattr(request, 'tenant_membership', None)
        if not request.user.is_superuser and (membership is None or not membership.has(P.SIGN_CHART)):
            raise PermissionDenied('Signing requires SIGN_CHART.')
        if parent.parent_record_id is not None:
            raise ValidationError({'detail': 'Addenda cannot have addenda.'})
        if not parent.is_locked:
            raise ValidationError({
                'detail': 'Parent is still within the edit window — edit it instead.',
            })
        if parent.is_voided:
            raise ValidationError({'detail': 'Cannot append to a voided record.'})

        ser = TreatmentRecordAddendumCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        instance = TreatmentRecord.objects.create(
            tenant=parent.tenant,
            customer=parent.customer,
            appointment=parent.appointment,
            template=parent.template,
            template_version_at_signing=parent.template.version,
            schema_snapshot=parent.template.schema,
            answers=ser.validated_data['answers'],
            author=membership,
            author_was_clinical=bool(
                membership and membership.job_title_id
                and membership.job_title.is_clinical
            ),
            parent_record=parent,
        )
        record(
            action=AuditLog.Action.CREATE,
            resource_type='treatment_record',
            resource_id=instance.id,
            request=request,
            metadata={
                'event': 'addendum',
                'parent_record_id': parent.id,
                'customer_id': parent.customer_id,
            },
        )
        return Response(
            self.get_serializer(instance).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='void')
    def void(self, request, pk=None):
        instance = self.get_object()
        membership = getattr(request, 'tenant_membership', None)
        if not request.user.is_superuser:
            if membership is None or not membership.has(P.EDIT_SIGNED_CHART):
                raise PermissionDenied(
                    'Voiding requires the EDIT_SIGNED_CHART permission '
                    '(owner or manager).',
                )
        if instance.is_voided:
            raise ValidationError({'detail': 'This record is already voided.'})
        if not instance.is_locked:
            raise ValidationError({
                'detail': (
                    'Edit the record instead while it is still in the '
                    'typo-correction window. Voiding is for locked records only.'
                ),
            })

        ser = TreatmentRecordVoidSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data['reason']

        instance.is_voided = True
        instance.voided_at = timezone.now()
        instance.voided_by = membership
        instance.voided_reason = reason
        instance.save(update_fields=[
            'is_voided', 'voided_at', 'voided_by', 'voided_reason',
            'updated_at',
        ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='treatment_record',
            resource_id=instance.pk,
            request=request,
            metadata={
                'event': 'voided',
                'reason': reason,
                'parent_record_id': instance.parent_record_id,
                'customer_id': instance.customer_id,
            },
        )
        return Response(self.get_serializer(instance).data)
