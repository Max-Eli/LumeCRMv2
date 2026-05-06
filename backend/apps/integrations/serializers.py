"""Serializers for the integrations API.

The list endpoint returns one entry per known provider — even if the
tenant hasn't connected it yet — so the frontend can render the
settings page from a single GET. Connected providers carry status
+ external account name + last-synced timestamp; disconnected ones
carry just the provider metadata.
"""

from rest_framework import serializers

from .models import Connection
from .providers import ProviderConfig, all_providers


class ProviderEntrySerializer(serializers.Serializer):
    """Single row in the integrations list — provider metadata + (if
    a connection exists for this tenant) its status + account info."""

    # Provider metadata (always present)
    key = serializers.CharField()
    display_name = serializers.CharField()
    family = serializers.CharField()
    short_description = serializers.CharField()
    enables = serializers.ListField(child=serializers.CharField())
    oauth_ready = serializers.BooleanField()

    # Connection state (null when no connection exists yet)
    connection_id = serializers.IntegerField(allow_null=True)
    status = serializers.CharField(allow_null=True)
    external_id = serializers.CharField(allow_null=True)
    external_name = serializers.CharField(allow_null=True)
    last_synced_at = serializers.DateTimeField(allow_null=True)
    last_error_message = serializers.CharField(allow_null=True)
    connected_at = serializers.DateTimeField(allow_null=True)

    @classmethod
    def from_provider_and_connection(
        cls,
        provider: ProviderConfig,
        connection: Connection | None,
    ) -> dict:
        return {
            'key': provider.key,
            'display_name': provider.display_name,
            'family': provider.family,
            'short_description': provider.short_description,
            'enables': provider.enables,
            'oauth_ready': provider.oauth_ready,
            'connection_id': connection.id if connection else None,
            'status': connection.status if connection else 'disconnected',
            'external_id': connection.external_id if connection else None,
            'external_name': connection.external_name if connection else None,
            'last_synced_at': connection.last_synced_at if connection else None,
            'last_error_message': (connection.last_error_message or None) if connection else None,
            'connected_at': connection.connected_at if connection else None,
        }


def build_provider_list(tenant) -> list[dict]:
    """Compose the full list of providers + this tenant's connection state."""
    connections = {
        c.provider: c
        for c in Connection.objects.for_current_tenant().filter(tenant=tenant)
    }
    return [
        ProviderEntrySerializer.from_provider_and_connection(p, connections.get(p.key))
        for p in all_providers()
    ]
