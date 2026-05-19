"""DRF serializers for the services API.

`ServiceSerializer` is one shape for both list and detail. `ServiceCategorySerializer`
exposes eligibility rules as nested job-title objects on read and accepts an array
of `eligible_job_title_ids` on write — same pattern as Customer tags.
"""

from rest_framework import serializers

from apps.tenants.models import JobTitle
from apps.tenants.views import JobTitleSerializer

from .models import Service, ServiceCategory, ServiceProtocol


class ServiceCategorySerializer(serializers.ModelSerializer):
    """Service category with full eligibility detail."""

    eligible_job_titles = JobTitleSerializer(many=True, read_only=True)
    eligible_job_title_ids = serializers.PrimaryKeyRelatedField(
        queryset=JobTitle.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source='eligible_job_titles',
    )
    service_count = serializers.IntegerField(source='services.count', read_only=True)

    class Meta:
        model = ServiceCategory
        fields = [
            'id',
            'name',
            'color',
            'sort_order',
            'eligible_job_titles',
            'eligible_job_title_ids',
            'service_count',
        ]
        read_only_fields = ['id', 'eligible_job_titles', 'service_count']


class _NestedServiceCategorySerializer(serializers.ModelSerializer):
    """Slim category representation used inside ServiceSerializer to keep service
    payloads small. Full eligibility data is fetched separately when needed."""

    class Meta:
        model = ServiceCategory
        fields = ['id', 'name', 'color', 'sort_order']


class ServiceSerializer(serializers.ModelSerializer):
    category = _NestedServiceCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ServiceCategory.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
        source='category',
    )
    price_dollars = serializers.CharField(read_only=True)
    # `hero_photo_url` is a read-only convenience exposing the storage's
    # public/signed URL. Upload + delete happen through the dedicated
    # `/api/services/{id}/photo/` action so the main service form stays
    # JSON-only (no multipart juggling on every save).
    hero_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id',
            'name',
            'code',
            'description',
            'service_type',
            'category',
            'category_id',
            'duration_minutes',
            'buffer_minutes',
            'price_cents',
            'price_dollars',
            'tax_rate_percent',
            'is_bookable_online',
            'is_active',
            'sort_order',
            'hero_photo_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'category', 'price_dollars',
            'hero_photo_url', 'created_at', 'updated_at',
        ]

    def get_hero_photo_url(self, obj: Service) -> str | None:
        if not obj.hero_photo:
            return None
        try:
            url = obj.hero_photo.url
        except (ValueError, OSError):
            return None
        # Build an absolute URL so the booking page (different origin
        # in dev) can load the file. S3 signed URLs are already
        # absolute and pass through `build_absolute_uri` unchanged.
        request = self.context.get('request')
        if request is not None:
            return request.build_absolute_uri(url)
        return url


class ServiceProtocolSerializer(serializers.ModelSerializer):
    """Read/write shape for a service's clinical protocol.

    `tenant` is set by the view from request context; `service` is
    derived from the URL. Neither is writable from the client.
    `updated_by_email` is a read-only display field — operators see
    "Last edited by …" without us exposing the User object."""

    updated_by_email = serializers.EmailField(
        source='updated_by.email', read_only=True, allow_null=True,
    )
    is_empty = serializers.BooleanField(read_only=True)

    class Meta:
        model = ServiceProtocol
        fields = [
            'id',
            'service',
            'pre_treatment',
            'intra_treatment',
            'post_treatment',
            'notes',
            'is_empty',
            'updated_by_email',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'service', 'is_empty',
            'updated_by_email', 'created_at', 'updated_at',
        ]
