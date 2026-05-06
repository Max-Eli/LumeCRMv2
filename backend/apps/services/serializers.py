"""DRF serializers for the services API.

`ServiceSerializer` is one shape for both list and detail. `ServiceCategorySerializer`
exposes eligibility rules as nested job-title objects on read and accepts an array
of `eligible_job_title_ids` on write — same pattern as Customer tags.
"""

from rest_framework import serializers

from apps.tenants.models import JobTitle
from apps.tenants.views import JobTitleSerializer

from .models import Service, ServiceCategory


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
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'category', 'price_dollars', 'created_at', 'updated_at']
