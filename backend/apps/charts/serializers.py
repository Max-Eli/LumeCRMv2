"""Serializers for the chart-notes API.

`ChartNoteSerializer` is the read shape (used by list + retrieve).
Writes go through `ChartNoteCreateSerializer` (initial signing) and
`ChartNoteUpdateSerializer` (within-window edit). Splitting them
keeps the writable-field set explicit and prevents a PATCH from
sneaking changes into immutable fields like `signed_at` or
`author`.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    ChartNote,
    ServiceTreatmentTemplateAssignment,
    TreatmentRecord,
    TreatmentRecordTemplate,
)


class ChartNoteSerializer(serializers.ModelSerializer):
    """Read shape — what the customer profile's Notes tab renders.

    Author identity is denormalized so the UI can show
    "Sarah Chen, NP" without a second fetch. The `author_was_clinical`
    snapshot is the legal-status anchor (see ADR 0015 for why this
    isn't a live join against the membership's current job title).

    Session 2 added `parent_note_id` (null for top-level notes) and
    the void state. `voided_by_*` fields denormalize the voiding
    operator's identity so the UI can render "Voided by Manager X
    on Y" without a second fetch.
    """

    appointment_id = serializers.IntegerField(
        source='appointment.id', read_only=True, allow_null=True,
    )
    appointment_date = serializers.SerializerMethodField()
    appointment_service_name = serializers.CharField(
        source='appointment.service.name', read_only=True, default='',
    )

    author_id = serializers.IntegerField(source='author.id', read_only=True)
    author_first_name = serializers.CharField(source='author.user.first_name', read_only=True)
    author_last_name = serializers.CharField(source='author.user.last_name', read_only=True)
    author_email = serializers.EmailField(source='author.user.email', read_only=True)
    author_job_title = serializers.SerializerMethodField()

    is_locked = serializers.BooleanField(read_only=True)
    edit_window_ends_at = serializers.DateTimeField(read_only=True)

    parent_note_id = serializers.IntegerField(
        source='parent_note.id', read_only=True, allow_null=True,
    )

    voided_by_first_name = serializers.CharField(
        source='voided_by.user.first_name', read_only=True, default='',
    )
    voided_by_last_name = serializers.CharField(
        source='voided_by.user.last_name', read_only=True, default='',
    )
    voided_by_email = serializers.EmailField(
        source='voided_by.user.email', read_only=True, default='',
    )

    class Meta:
        model = ChartNote
        fields = [
            'id',
            'customer',
            'appointment_id', 'appointment_date', 'appointment_service_name',
            'body',
            'author_id', 'author_first_name', 'author_last_name',
            'author_email', 'author_job_title', 'author_was_clinical',
            'signed_at',
            'is_locked', 'edit_window_ends_at',
            'parent_note_id',
            'is_voided', 'voided_at', 'voided_reason',
            'voided_by_first_name', 'voided_by_last_name', 'voided_by_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields  # everything is read-only on this serializer

    def get_appointment_date(self, note: ChartNote):
        if note.appointment_id is None:
            return None
        return note.appointment.start_time.isoformat()

    def get_author_job_title(self, note: ChartNote):
        return getattr(note.author.job_title, 'name', '') if note.author.job_title_id else ''


class ChartNoteAddendumCreateSerializer(serializers.Serializer):
    """Body validation for `POST /api/chart-notes/<id>/addendum/`.

    Only `body` is in the payload; the parent is from the URL,
    customer + appointment inherit from the parent. The view
    validates the parent is locked + not voided + within the same
    tenant before creating.
    """

    body = serializers.CharField(min_length=1, allow_blank=False)


class ChartNoteVoidSerializer(serializers.Serializer):
    """Body validation for `POST /api/chart-notes/<id>/void/`.

    `reason` is required and stored verbatim on the row + the audit
    log. Common values: "wrong patient", "signed in error",
    "duplicate entry". Free-form because the operator's
    justification is what makes the void legible to a future
    reviewer; constraining to a dropdown would push real reasons
    into a generic "other" bucket.
    """

    reason = serializers.CharField(min_length=1, max_length=500, allow_blank=False)


class ChartNoteCreateSerializer(serializers.Serializer):
    """Body validation for `POST /api/chart-notes/` — initial signing.

    `customer_id` + `body` are required; `appointment_id` is optional
    (standalone clinical observation when null). The view re-validates
    every FK against the request's tenant.

    Author + signed_at + tenant come from the request context, not
    the payload — the caller can't claim to be a different signer.
    """

    customer_id = serializers.IntegerField()
    appointment_id = serializers.IntegerField(required=False, allow_null=True)
    body = serializers.CharField(min_length=1, allow_blank=False)


class ChartNoteUpdateSerializer(serializers.Serializer):
    """Body validation for the within-window edit. Only the body
    field is mutable; everything else (author, customer, appointment,
    signed_at) is locked at signing time.

    Note this is a regular Serializer rather than a ModelSerializer:
    we want PATCH semantics where ONLY `body` is accepted — anything
    else in the payload would silently be ignored by ModelSerializer
    on a PATCH, which is the wrong default for an audit-sensitive
    endpoint. This way unexpected fields raise.
    """

    body = serializers.CharField(min_length=1, allow_blank=False)

    def validate(self, attrs):
        # Reject any unexpected keys — defends against a stale UI or
        # malicious payload trying to update author, signed_at, etc.
        # Initial-data has the raw POST body; we compare against the
        # field set we declared.
        if hasattr(self, 'initial_data'):
            extra = set(self.initial_data.keys()) - {'body'}
            if extra:
                raise serializers.ValidationError({
                    k: 'This field cannot be edited after signing.'
                    for k in extra
                })
        return attrs


# ── Treatment record templates + submissions ──────────────────────


import re

# Same field-type vocabulary as `apps.forms` plus `number` for
# medical fields (units used, dosages, side counts).
ALLOWED_FIELD_TYPES = frozenset({
    'short_text',
    'long_text',
    'choice_single',
    'choice_multiple',
    'number',
    'date',
    'signature',
})

# Field id pattern — same as forms (ASCII alphanumeric + underscore).
_FIELD_ID_RE = re.compile(r'^[a-zA-Z0-9_]{1,64}$')


def _validate_template_field(field, index):
    """Validate a single field dict in a TreatmentRecordTemplate
    schema. Same shape as `apps.forms.serializers._validate_field`
    plus `number`-type validation."""
    if not isinstance(field, dict):
        raise serializers.ValidationError({
            f'fields[{index}]': 'Each field must be an object.',
        })
    field_id = field.get('id')
    field_type = field.get('type')
    label = field.get('label')

    if not field_id or not isinstance(field_id, str) or not _FIELD_ID_RE.match(field_id):
        raise serializers.ValidationError({
            f'fields[{index}]': (
                'Each field requires an `id` (1–64 ASCII letters / '
                'digits / underscore).'
            ),
        })
    if field_type not in ALLOWED_FIELD_TYPES:
        raise serializers.ValidationError({
            f'fields[{index}]': (
                f'Unknown field type "{field_type}". Allowed: '
                f'{sorted(ALLOWED_FIELD_TYPES)}.'
            ),
        })
    if not label or not isinstance(label, str) or not label.strip():
        raise serializers.ValidationError({
            f'fields[{index}]': 'Each field requires a non-empty `label`.',
        })

    if field_type in {'choice_single', 'choice_multiple'}:
        options = field.get('options')
        if not isinstance(options, list) or len(options) < 2:
            raise serializers.ValidationError({
                f'fields[{index}]': (
                    'Choice fields require at least two `options`.'
                ),
            })
        seen_values = set()
        for opt_index, opt in enumerate(options):
            if not isinstance(opt, dict):
                raise serializers.ValidationError({
                    f'fields[{index}].options[{opt_index}]': 'Must be an object.',
                })
            value = opt.get('value')
            opt_label = opt.get('label')
            if not value or not isinstance(value, str):
                raise serializers.ValidationError({
                    f'fields[{index}].options[{opt_index}]': 'Requires non-empty `value`.',
                })
            if not opt_label or not isinstance(opt_label, str):
                raise serializers.ValidationError({
                    f'fields[{index}].options[{opt_index}]': 'Requires non-empty `label`.',
                })
            if value in seen_values:
                raise serializers.ValidationError({
                    f'fields[{index}].options[{opt_index}]': (
                        f'Duplicate option value "{value}" within this field.'
                    ),
                })
            seen_values.add(value)


class TreatmentRecordTemplateSerializer(serializers.ModelSerializer):
    """Read + write shape for `TreatmentRecordTemplate`.

    `version` is read-only; the viewset bumps it on every save
    where `schema` actually changed. `service_ids` is the per-
    service assignment list (full-replace semantics on write,
    same pattern as FormTemplate.set_service_ids)."""

    service_ids = serializers.SerializerMethodField()
    # Late-bind the queryset so the field can be constructed during
    # module import without forcing a cross-app import cycle.
    set_service_ids = serializers.PrimaryKeyRelatedField(
        queryset=__import__(
            'apps.services.models', fromlist=['Service'],
        ).Service.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )

    class Meta:
        model = TreatmentRecordTemplate
        fields = [
            'id',
            'name', 'description',
            'schema',
            'version',
            'is_active',
            'service_ids', 'set_service_ids',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'version', 'service_ids', 'created_at', 'updated_at',
        ]

    def get_service_ids(self, obj) -> list[int]:
        return sorted(
            ServiceTreatmentTemplateAssignment.objects
            .filter(template=obj)
            .values_list('service_id', flat=True)
        )

    def validate_schema(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("`schema` must be an object with a `fields` array.")
        fields = value.get('fields')
        if not isinstance(fields, list):
            raise serializers.ValidationError("`schema.fields` must be an array.")
        seen_ids = set()
        for index, field in enumerate(fields):
            _validate_template_field(field, index)
            field_id = field['id']
            if field_id in seen_ids:
                raise serializers.ValidationError({
                    f'fields[{index}]': f'Duplicate field id "{field_id}".',
                })
            seen_ids.add(field_id)
        return value


class TreatmentRecordSerializer(serializers.ModelSerializer):
    """Read shape — what the customer profile + appointment popover
    render. Author + voiding metadata denormalized for the UI; PHI
    answers + schema_snapshot included so the reader can render the
    record exactly as it was at signing time.
    """

    appointment_id = serializers.IntegerField(
        source='appointment.id', read_only=True, allow_null=True,
    )
    appointment_date = serializers.SerializerMethodField()

    template_id = serializers.IntegerField(source='template.id', read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True)

    author_id = serializers.IntegerField(source='author.id', read_only=True)
    author_first_name = serializers.CharField(source='author.user.first_name', read_only=True)
    author_last_name = serializers.CharField(source='author.user.last_name', read_only=True)
    author_email = serializers.EmailField(source='author.user.email', read_only=True)
    author_job_title = serializers.SerializerMethodField()

    is_locked = serializers.BooleanField(read_only=True)
    edit_window_ends_at = serializers.DateTimeField(read_only=True)

    parent_record_id = serializers.IntegerField(
        source='parent_record.id', read_only=True, allow_null=True,
    )

    voided_by_first_name = serializers.CharField(
        source='voided_by.user.first_name', read_only=True, default='',
    )
    voided_by_last_name = serializers.CharField(
        source='voided_by.user.last_name', read_only=True, default='',
    )
    voided_by_email = serializers.EmailField(
        source='voided_by.user.email', read_only=True, default='',
    )

    class Meta:
        model = TreatmentRecord
        fields = [
            'id',
            'customer',
            'appointment_id', 'appointment_date',
            'template_id', 'template_name',
            'template_version_at_signing',
            'schema_snapshot',
            'answers',
            'author_id', 'author_first_name', 'author_last_name',
            'author_email', 'author_job_title', 'author_was_clinical',
            'signed_at',
            'is_locked', 'edit_window_ends_at',
            'parent_record_id',
            'is_voided', 'voided_at', 'voided_reason',
            'voided_by_first_name', 'voided_by_last_name', 'voided_by_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_appointment_date(self, record):
        if record.appointment_id is None:
            return None
        return record.appointment.start_time.isoformat()

    def get_author_job_title(self, record):
        return getattr(record.author.job_title, 'name', '') if record.author.job_title_id else ''


class TreatmentRecordCreateSerializer(serializers.Serializer):
    """Body validation for `POST /api/treatment-records/` — initial
    signing. Customer + template ids required; appointment optional.
    Author + tenant + signed_at + schema_snapshot all derived from
    the request context, never the payload."""

    customer_id = serializers.IntegerField()
    template_id = serializers.IntegerField()
    appointment_id = serializers.IntegerField(required=False, allow_null=True)
    answers = serializers.DictField(child=serializers.JSONField(), required=False, default=dict)


class TreatmentRecordUpdateSerializer(serializers.Serializer):
    """Within-window edit — only `answers` is mutable. Same anti-
    PATCH-leak posture as ChartNoteUpdateSerializer."""

    answers = serializers.DictField(child=serializers.JSONField())

    def validate(self, attrs):
        if hasattr(self, 'initial_data'):
            extra = set(self.initial_data.keys()) - {'answers'}
            if extra:
                raise serializers.ValidationError({
                    k: 'This field cannot be edited after signing.'
                    for k in extra
                })
        return attrs


class TreatmentRecordAddendumCreateSerializer(serializers.Serializer):
    """Body validation for the addendum endpoint. Only `answers` —
    the parent + customer + appointment all inherit from the parent
    record. Same shape as the create serializer minus the FK fields."""

    answers = serializers.DictField(child=serializers.JSONField())


class TreatmentRecordVoidSerializer(serializers.Serializer):
    """Same posture as ChartNoteVoidSerializer — required reason,
    free-form, capped at 500 chars."""

    reason = serializers.CharField(min_length=1, max_length=500, allow_blank=False)
