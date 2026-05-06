"""Integrations API.

URL surface (under `/api/integrations/`):

    GET    /                        List all providers + this tenant's connection state
    POST   /<provider>/connect/begin/   Start OAuth flow (placeholder until Session 2)
    POST   /<id>/disconnect/        Disconnect a connected provider

Read access (the list) is open to any tenant member with
MANAGE_INTEGRATIONS — owner + manager by default. The state-changing
actions (connect/disconnect) write structured AuditLog entries with
`resource_type='integration_connection'` so the trail filters apart
from per-tenant CRUD.

Connect-begin is a placeholder in v1 — it returns 501 Not Implemented
with a structured `code='oauth_not_ready'`. Session 2 wires the real
Meta OAuth flow once the Meta App approval lands.
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .models import Connection
from .permissions import IntegrationPermission
from .providers import all_providers, get_provider
from .serializers import build_provider_list


class IntegrationListView(APIView):
    """List all providers + the tenant's connection state for each."""

    permission_classes = [IntegrationPermission]

    @extend_schema(
        responses={200: OpenApiResponse(description='List of providers + connection state')},
    )
    def get(self, request):
        tenant = get_current_tenant()
        return Response(build_provider_list(tenant))


class IntegrationConnectBeginView(APIView):
    """Start the OAuth flow for a provider.

    v1: returns 501 with `code='oauth_not_ready'` because Meta app
    review hasn't landed yet. Session 2 replaces this with a real
    flow that:
      1. Generates a state token tied to the user's session
      2. Returns the provider's authorize URL with our client_id +
         redirect_uri + scopes + state
      3. The frontend opens that URL; provider redirects back to
         `/api/integrations/<provider>/connect/callback/` with `code`
      4. Callback exchanges code for tokens, creates Connection row
    """

    permission_classes = [IntegrationPermission]

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Returns OAuth authorize URL (when ready)'),
            501: OpenApiResponse(description='OAuth flow not yet implemented for this provider'),
            400: OpenApiResponse(description='Unknown provider'),
        },
    )
    def post(self, request, provider: str):
        tenant = get_current_tenant()
        provider_config = get_provider(provider)
        if not provider_config:
            return Response(
                {'detail': f'Unknown provider: {provider!r}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Audit even the placeholder click — operators should be able
        # to see who tried to connect what, when. Helps debugging
        # "why is this showing connected" reports later.
        record(
            action=AuditLog.Action.CREATE,
            resource_type='integration_connection',
            request=request,
            metadata={
                'event': 'connect_begin_attempted',
                'provider': provider,
                'oauth_ready': provider_config.oauth_ready,
            },
        )

        if not provider_config.oauth_ready:
            return Response(
                {
                    'detail': (
                        f'{provider_config.display_name} integration is awaiting '
                        'Meta App approval. We will email you when it goes live.'
                    ),
                    'code': 'oauth_not_ready',
                    'provider': provider,
                },
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        # Session 2 — real OAuth flow returns here.
        return Response(
            {'detail': 'OAuth flow not yet implemented.'},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


class IntegrationDisconnectView(APIView):
    """Disconnect a connected integration.

    Marks the connection as DISCONNECTED, clears auth_data + external
    fields, records the disconnect timestamp + actor. The row stays
    in the DB so the audit trail survives — re-connecting later
    updates the same row in-place.

    No-op if the connection is already disconnected.
    """

    permission_classes = [IntegrationPermission]

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Connection disconnected'),
            404: OpenApiResponse(description='Connection not found in this tenant'),
        },
    )
    def post(self, request, pk: int):
        tenant = get_current_tenant()
        connection = get_object_or_404(
            Connection.objects.for_current_tenant(),
            pk=pk,
        )

        if connection.status == Connection.Status.DISCONNECTED:
            return Response(
                {'detail': 'Connection is already disconnected.'},
                status=status.HTTP_200_OK,
            )

        previous_status = connection.status
        previous_external_id = connection.external_id
        connection.status = Connection.Status.DISCONNECTED
        connection.auth_data = {}
        connection.external_id = ''
        connection.external_name = ''
        connection.disconnected_at = timezone.now()
        connection.last_error_at = None
        connection.last_error_message = ''
        connection.save(update_fields=[
            'status', 'auth_data', 'external_id', 'external_name',
            'disconnected_at', 'last_error_at', 'last_error_message',
            'updated_at',
        ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='integration_connection',
            resource_id=connection.pk,
            request=request,
            metadata={
                'event': 'connection_disconnected',
                'provider': connection.provider,
                'previous_status': previous_status,
                'previous_external_id': previous_external_id,
            },
        )

        return Response(build_provider_list(tenant))
