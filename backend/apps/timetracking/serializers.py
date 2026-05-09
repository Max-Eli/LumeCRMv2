"""DRF serializers for the time tracking API."""

from __future__ import annotations

from rest_framework import serializers

from .models import TimeEntry


class TimeEntrySerializer(serializers.ModelSerializer):
    """Read-only entry shape with denormalized membership + actor info.

    Mutations go through the action endpoints (`clock-in/`,
    `clock-out/`) and the standard PATCH for manager edits.
    """

    membership_user_email = serializers.EmailField(
        source='membership.user.email', read_only=True,
    )
    membership_user_first_name = serializers.CharField(
        source='membership.user.first_name', read_only=True,
    )
    membership_user_last_name = serializers.CharField(
        source='membership.user.last_name', read_only=True,
    )
    membership_role = serializers.CharField(
        source='membership.role', read_only=True,
    )
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, allow_null=True,
    )
    edited_by_email = serializers.EmailField(
        source='edited_by.email', read_only=True, allow_null=True,
    )
    is_open = serializers.BooleanField(read_only=True)
    duration_seconds = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = TimeEntry
        fields = [
            'id',
            'membership',
            'membership_user_email',
            'membership_user_first_name',
            'membership_user_last_name',
            'membership_role',
            'clock_in_at',
            'clock_out_at',
            'notes',
            'source',
            'is_open',
            'duration_seconds',
            'created_by_email',
            'edited_at',
            'edited_by_email',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'membership',
            'membership_user_email', 'membership_user_first_name',
            'membership_user_last_name', 'membership_role',
            'is_open', 'duration_seconds',
            'created_by_email', 'edited_at', 'edited_by_email',
            'created_at', 'updated_at',
        ]


class ClockInInputSerializer(serializers.Serializer):
    """Body for `POST /api/time-entries/clock-in/`.

    `membership_id` is optional; defaults to the requesting user's
    own membership in the current tenant. Setting it to a different
    membership requires `MANAGE_STAFF` (kiosk / front-desk model;
    enforced in the view).
    """

    membership_id = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=200,
    )
    source = serializers.ChoiceField(
        choices=TimeEntry.Source.choices,
        required=False,
        default=TimeEntry.Source.SELF,
    )


class ClockOutInputSerializer(serializers.Serializer):
    """Body for `POST /api/time-entries/clock-out/`. Same rules as
    clock-in: defaults to self; cross-membership requires
    MANAGE_STAFF."""

    membership_id = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=200,
    )


class TimeEntryEditInputSerializer(serializers.Serializer):
    """Body for the manager-only PATCH on a time entry. Lets ops
    fix forgot-to-clock-out entries without giving everyone the
    ability to backdate punches."""

    clock_in_at = serializers.DateTimeField(required=False)
    clock_out_at = serializers.DateTimeField(
        required=False, allow_null=True,
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=2000,
    )

    def validate(self, attrs: dict) -> dict:
        ci = attrs.get('clock_in_at')
        co = attrs.get('clock_out_at')
        if ci is not None and co is not None and co <= ci:
            raise serializers.ValidationError(
                'clock_out_at must be after clock_in_at.',
            )
        return attrs
