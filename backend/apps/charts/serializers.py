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

from .models import ChartNote


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
