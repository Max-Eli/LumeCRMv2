"""Integrations API.

URL surface (under `/api/integrations/`):

    GET    /                                List all providers + this tenant's connection state
    POST   /<provider>/connect/begin/       Start OAuth flow
    POST   /<id>/disconnect/                Disconnect a connected provider
    GET    /meta/oauth/callback/            Meta OAuth callback (browser redirect target)
    GET    /webhooks/meta/                  Meta webhook subscription verification
    POST   /webhooks/meta/                  Meta webhook event delivery

Auth model:
  - The first three endpoints are MANAGE_INTEGRATIONS gated
    (`IntegrationPermission`).
  - The callback is gated by the session-bound state token from
    ADR 0027 §2; CSRF-exempt because Meta is the redirector.
  - The webhook endpoints are AllowAny + CSRF-exempt; security
    comes from the X-Hub-Signature-256 HMAC over the body.

Audit posture (per ADR 0027 §9): every connect / disconnect / inbound
delivery writes an AuditLog row with `resource_type='integration_connection'`
or `'social_message'`. PHI never appears in audit metadata — message
bodies are summarised as length + media count.
"""

from __future__ import annotations

import json
import logging

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant
from apps.tenants.models import Tenant

from . import meta as meta_oauth
from .models import Connection, DataDeletionRequest, SocialMessage, SocialThread
from .permissions import IntegrationPermission
from .providers import all_providers, get_provider
from .serializers import build_provider_list

logger = logging.getLogger(__name__)


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

    For Meta providers with `oauth_ready=True` (env-driven on
    `META_APP_ID` / `META_APP_SECRET` / `META_WEBHOOK_VERIFY_TOKEN`),
    returns an `authorize_url` for the frontend to redirect to. If
    the credentials aren't configured the endpoint returns 501 with
    `code='oauth_not_ready'` so the UI can render an "awaiting
    setup" message instead of breaking.
    """

    permission_classes = [IntegrationPermission]

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Returns OAuth authorize URL'),
            501: OpenApiResponse(description='OAuth flow not yet enabled for this provider'),
            400: OpenApiResponse(description='Unknown or unsupported provider'),
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

        # Audit every connect-attempt so disputed reconnects have a trail.
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
                        f'{provider_config.display_name} integration is not '
                        'yet configured on this deployment. Contact support.'
                    ),
                    'code': 'oauth_not_ready',
                    'provider': provider,
                },
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        # Generate state + persist OAuth flow scaffolding.
        state = meta_oauth.generate_state_token()
        meta_oauth.store_state_in_session(
            request,
            state,
            tenant_id=tenant.id,
            provider=provider,
        )

        # Pre-create or update the Connection row to CONNECTING so
        # the integrations list UI shows the in-flight state.
        connection, _created = Connection.objects.update_or_create(
            tenant=tenant,
            provider=provider,
            defaults={
                'status': Connection.Status.CONNECTING,
                'last_error_at': None,
                'last_error_message': '',
            },
        )

        try:
            authorize_url = meta_oauth.build_authorize_url(
                provider=provider, state=state,
            )
        except meta_oauth.MetaOAuthError as e:
            connection.status = Connection.Status.ERROR
            connection.last_error_at = timezone.now()
            connection.last_error_message = str(e)[:500]
            connection.save(update_fields=[
                'status', 'last_error_at', 'last_error_message', 'updated_at',
            ])
            return Response(
                {'detail': str(e), 'code': 'oauth_build_failed'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'authorize_url': authorize_url,
            'state': state,  # echoed for client-side debugging only
            'connection_id': connection.id,
        })


class IntegrationDisconnectView(APIView):
    """Disconnect a connected integration."""

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
        connection.clear_auth_data()
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


@method_decorator(csrf_exempt, name='dispatch')
class MetaOAuthCallbackView(APIView):
    """Meta redirects users here after consent. Browser-driven GET
    with `?code=...&state=...` in the query string.

    Auth: not session-gated in the usual sense — the staff user IS
    authenticated (otherwise the original Connect click wouldn't have
    started the flow), and we validate the session-bound state token
    inside. AllowAny permission + state binding is the standard OAuth
    callback posture.

    Outcome: redirects the browser back to
    `/org/integrations?connected=instagram` (or `?error=...`) so the
    Next.js page can render a toast.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # state token is the auth boundary

    @extend_schema(
        responses={
            302: OpenApiResponse(description='Redirect to /org/integrations with status'),
        },
    )
    def get(self, request):
        code = request.query_params.get('code')
        state = request.query_params.get('state', '')
        provider_error = request.query_params.get('error')

        # User clicked Cancel on Meta's consent screen
        if provider_error:
            return self._redirect_with_error(
                f'Meta consent was cancelled: {provider_error}',
                code='consent_cancelled',
            )

        if not code:
            return self._redirect_with_error(
                'Missing authorization code on callback.',
                code='missing_code',
            )

        try:
            binding = meta_oauth.consume_state_from_session(request, state)
        except meta_oauth.MetaOAuthError as e:
            return self._redirect_with_error(str(e), code='invalid_state')

        tenant_id = binding.get('tenant_id')
        provider = binding.get('provider')

        try:
            tenant = Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist:
            return self._redirect_with_error(
                'Tenant for this OAuth flow no longer exists.',
                code='tenant_missing',
            )

        try:
            connection = Connection.objects.get(
                tenant=tenant, provider=provider,
            )
        except Connection.DoesNotExist:
            return self._redirect_with_error(
                'No in-flight Connection row found; click Connect again.',
                code='connection_missing',
            )

        try:
            tokens = meta_oauth.exchange_code_for_connection(code)
            meta_oauth.subscribe_ig_user_to_webhooks(
                ig_user_id=tokens.ig_user_id,
                access_token=tokens.access_token,
            )
        except meta_oauth.MetaOAuthError as e:
            connection.status = Connection.Status.ERROR
            connection.last_error_at = timezone.now()
            connection.last_error_message = str(e)[:500]
            connection.save(update_fields=[
                'status', 'last_error_at', 'last_error_message', 'updated_at',
            ])
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='integration_connection',
                resource_id=connection.pk,
                request=request,
                metadata={
                    'event': 'oauth_failed',
                    'provider': provider,
                    'error_message': str(e)[:500],
                },
            )
            return self._redirect_with_error(str(e), code='oauth_failed')

        # Success — persist tokens (encrypted) + flip status.
        # external_id holds the IG user_id; that's what Meta sends as
        # entry[].id on every webhook delivery, so payload routing
        # can find this Connection in one query.
        connection.external_id = tokens.ig_user_id
        connection.external_name = (
            f'@{tokens.ig_username}' if tokens.ig_username
            else f'IG account {tokens.ig_user_id}'
        )
        connection.set_auth_data({
            'ig_user_id': tokens.ig_user_id,
            'access_token': tokens.access_token,
            'ig_username': tokens.ig_username,
            'granted_scopes': tokens.granted_scopes,
            'expires_at': tokens.expires_at,
        })
        connection.status = Connection.Status.CONNECTED
        connection.connected_at = timezone.now()
        connection.last_synced_at = timezone.now()
        connection.last_error_at = None
        connection.last_error_message = ''
        connection.save()

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='integration_connection',
            resource_id=connection.pk,
            request=request,
            metadata={
                'event': 'connection_established',
                'provider': provider,
                'external_id': tokens.ig_user_id,
                'instagram_username': tokens.ig_username,
                'granted_scopes': tokens.granted_scopes,
            },
        )

        return HttpResponse(status=302, headers={
            'Location': self._redirect_url('connected=instagram'),
        })

    def _redirect_with_error(self, message: str, *, code: str) -> HttpResponse:
        # NOTE: `message` is reserved by logging's LogRecord — must use a
        # different key in `extra=`.
        logger.warning(
            'integrations.meta.oauth_callback_error',
            extra={'code': code, 'detail': message[:200]},
        )
        from urllib.parse import urlencode
        return HttpResponse(status=302, headers={
            'Location': self._redirect_url(urlencode({
                'integration_error': code,
                'integration_error_message': message[:200],
            })),
        })

    @staticmethod
    def _redirect_url(query: str) -> str:
        from django.conf import settings
        base = settings.PUBLIC_BASE_URL.rstrip('/')
        return f'{base}/org/integrations?{query}'


@method_decorator(csrf_exempt, name='dispatch')
class MetaWebhookView(APIView):
    """Meta sends inbound IG / FB / WA messages here.

    GET = subscription handshake; POST = event delivery.

    AllowAny + CSRF-exempt — the security boundary is the
    `X-Hub-Signature-256` HMAC over the raw body (for POST) and
    the `hub.verify_token` echo (for GET).
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Challenge accepted (returns echo)'),
            403: OpenApiResponse(description='Verify token mismatch'),
        },
    )
    def get(self, request):
        mode = request.query_params.get('hub.mode', '')
        token = request.query_params.get('hub.verify_token', '')
        challenge = request.query_params.get('hub.challenge', '')

        accepted = meta_oauth.verify_webhook_subscription_challenge(
            mode=mode, token=token, challenge=challenge,
        )
        if accepted is None:
            return HttpResponse(status=403)
        return HttpResponse(content=accepted, status=200, content_type='text/plain')

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Always 200 — Meta retries 4xx aggressively'),
        },
    )
    def post(self, request):
        raw_body = request.body
        signature = request.headers.get('X-Hub-Signature-256', '')

        if not meta_oauth.verify_webhook_signature(
            raw_body=raw_body, header_value=signature,
        ):
            logger.warning(
                'integrations.meta.webhook_bad_signature',
                extra={
                    'signature_present': bool(signature),
                    'body_length': len(raw_body),
                },
            )
            # ADR 0027 §3 — never 4xx to Meta; log + 200 with status.
            return Response(
                {'received': False, 'reason': 'invalid_signature'},
                status=status.HTTP_200_OK,
            )

        try:
            payload = json.loads(raw_body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            logger.warning('integrations.meta.webhook_bad_json')
            return Response(
                {'received': False, 'reason': 'bad_json'},
                status=status.HTTP_200_OK,
            )

        try:
            result = meta_oauth.ingest_webhook_payload(payload)
        except Exception as e:  # noqa: BLE001 — webhook MUST stay 200
            logger.exception(
                'integrations.meta.webhook_ingest_failed',
                extra={'error': str(e)[:200]},
            )
            return Response(
                {'received': True, 'partial_failure': True},
                status=status.HTTP_200_OK,
            )

        if result.messages_created:
            # Audit each ingestion at aggregate (per-message rows in
            # the SocialMessage table are themselves the per-event audit).
            record(
                action=AuditLog.Action.CREATE,
                resource_type='social_message',
                request=request,
                metadata={
                    'event': 'meta_webhook_ingested',
                    'messages_created': result.messages_created,
                    'threads_touched': result.threads_touched,
                    'messages_duplicate': result.messages_duplicate,
                    'pages_unmatched': result.pages_unmatched,
                },
            )

        return Response(
            {
                'received': True,
                'messages_created': result.messages_created,
                'threads_touched': result.threads_touched,
                'messages_duplicate': result.messages_duplicate,
                'pages_unmatched': result.pages_unmatched,
            },
            status=status.HTTP_200_OK,
        )


# ── Diagnostics (operator + dev troubleshooting) ────────────────────


class IntegrationDiagnosticsView(APIView):
    """Owner+manager endpoint that reports:
      - Which Meta env vars are set (booleans only, never the values).
      - The OAuth + webhook + data-deletion URLs we expect Meta to
        be hitting (built from the same logic the real endpoints use).
      - Per-tenant connection state for each Meta provider.

    Designed for the "why isn't this working?" loop — first thing to
    check is whether the env vars actually landed in the running
    process, vs. only in `.env` or Secrets Manager. This endpoint
    gives a yes/no answer without exposing the actual secrets in the
    response.
    """

    permission_classes = [IntegrationPermission]

    def get(self, request):
        from django.conf import settings as _s
        tenant = get_current_tenant()

        public_base = (getattr(_s, 'PUBLIC_BASE_URL', '') or '').rstrip('/')
        callback = getattr(_s, 'META_OAUTH_REDIRECT_URI', '') or '(unset — using default)'

        env_status = {
            'META_APP_ID': bool(getattr(_s, 'META_APP_ID', '')),
            'META_APP_SECRET': bool(getattr(_s, 'META_APP_SECRET', '')),
            'META_WEBHOOK_VERIFY_TOKEN': bool(getattr(_s, 'META_WEBHOOK_VERIFY_TOKEN', '')),
            'INTEGRATIONS_FERNET_KEY': bool(
                getattr(_s, 'INTEGRATIONS_FERNET_KEY', '')
                or getattr(_s, 'INTEGRATIONS_FERNET_KEYS', None)
            ),
            'META_TEST_MODE': bool(getattr(_s, 'META_TEST_MODE', False)),
        }
        all_creds_present = (
            env_status['META_APP_ID']
            and env_status['META_APP_SECRET']
            and env_status['META_WEBHOOK_VERIFY_TOKEN']
            and env_status['INTEGRATIONS_FERNET_KEY']
        )

        # The exact URLs Meta should be configured to hit. Read from
        # PUBLIC_BASE_URL so dev (localhost) and prod (production
        # domain) report what THIS process is using.
        meta_urls = {
            'oauth_redirect_uri': callback,
            'webhook_callback': (
                f'{public_base}/api/integrations/webhooks/meta/'
                if public_base else '/api/integrations/webhooks/meta/'
            ),
            'data_deletion_callback': (
                f'{public_base}/api/integrations/meta/data-deletion/'
                if public_base else '/api/integrations/meta/data-deletion/'
            ),
        }

        # Per-provider connection state (just for the Meta family;
        # other families add later).
        connections = []
        for c in Connection.objects.filter(
            tenant=tenant, provider__startswith='meta_',
        ):
            # Decrypt + summarise — NEVER returns the token itself,
            # only enough to tell the operator "yes a token is on
            # file" vs "this row is empty."
            try:
                payload = c.auth_data_dict
            except Exception:
                payload = {'_decrypt_failed': True}
            connections.append({
                'id': c.pk,
                'provider': c.provider,
                'status': c.status,
                'external_id': c.external_id,
                'external_name': c.external_name,
                'has_token': bool(payload.get('page_access_token')),
                'token_expires_at': payload.get('expires_at'),
                'instagram_username': payload.get('instagram_username', ''),
                'last_synced_at': (
                    c.last_synced_at.isoformat() if c.last_synced_at else None
                ),
                'last_error_message': c.last_error_message or None,
            })

        return Response({
            'tenant': tenant.slug,
            'env_vars_configured': env_status,
            'all_credentials_present': all_creds_present,
            'ready_to_connect': {
                'meta_instagram': all_creds_present,
                'meta_facebook': False,    # OAuth flow not yet built
                'meta_whatsapp': False,    # OAuth flow not yet built
            },
            'urls_meta_should_hit': meta_urls,
            'connections': connections,
            'help': (
                'If `all_credentials_present` is False, set the missing '
                'vars in backend/.env (dev) or Secrets Manager (prod) '
                'then restart the backend process. If they are set but '
                'OAuth still 501s, check the running process actually '
                'loaded them — `printenv | grep META_` inside the '
                'container is the fastest verification.'
            ),
        })


# ── Data Deletion (ADR 0027 §9 — Meta Platform Terms requirement) ──


@method_decorator(csrf_exempt, name='dispatch')
class MetaDataDeletionView(APIView):
    """Meta calls this when a user removes the app from FB settings.

    Format: `POST signed_request=<sig>.<base64url payload>` (form-encoded).
    We verify the HMAC, locate every Connection authorised by that
    FB user, force-disconnect them (clear tokens), persist a
    DataDeletionRequest audit row, and respond with the JSON Meta
    expects:

        {
            "url": "<status check URL>",
            "confirmation_code": "<short code>"
        }

    Meta hands the URL + code to the user so they can verify deletion
    (handled by `DataDeletionStatusView` below).
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Deletion request accepted'),
            400: OpenApiResponse(description='Malformed signed_request'),
        },
    )
    def post(self, request):
        import secrets as _secrets
        from django.conf import settings as _s

        signed_request = (
            request.POST.get('signed_request')
            or request.data.get('signed_request', '')
        )
        if not signed_request:
            return Response(
                {'detail': 'Missing signed_request field.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = meta_oauth.parse_signed_request(signed_request)
        except meta_oauth.MetaSignatureError as e:
            logger.warning(
                'integrations.meta.data_deletion_bad_signature',
                extra={'error': str(e)},
            )
            # Per Meta's spec the endpoint should respond 400 on
            # signature failure (unlike webhooks where we always 200).
            # This signals "your request was malformed" so Meta
            # doesn't pretend the deletion was honoured.
            return Response(
                {'detail': 'Invalid signed_request signature.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fb_user_id = payload.get('user_id', '')
        if not fb_user_id:
            return Response(
                {'detail': 'signed_request payload missing user_id.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        confirmation_code = _secrets.token_urlsafe(16)
        record_row = DataDeletionRequest.objects.create(
            confirmation_code=confirmation_code,
            external_user_id=fb_user_id,
            status=DataDeletionRequest.Status.PENDING,
        )

        try:
            affected_pairs = meta_oauth.revoke_connections_for_user(fb_user_id)
        except Exception as e:
            logger.exception(
                'integrations.meta.data_deletion_revoke_failed',
                extra={'user_id': fb_user_id},
            )
            record_row.status = DataDeletionRequest.Status.FAILED
            record_row.error_message = str(e)[:500]
            record_row.processed_at = timezone.now()
            record_row.save(update_fields=[
                'status', 'error_message', 'processed_at',
            ])
        else:
            # The affected list may be empty (a user can remove the
            # app before completing OAuth; we still respond with a
            # valid confirmation so Meta's UI doesn't spin).
            affected_ids = [cid for cid, _ in affected_pairs]
            page_ids = [pid for _, pid in affected_pairs if pid]
            record_row.affected_connection_ids = affected_ids
            record_row.affected_page_ids = page_ids
            record_row.status = DataDeletionRequest.Status.PROCESSED
            record_row.processed_at = timezone.now()
            record_row.save(update_fields=[
                'affected_connection_ids', 'affected_page_ids',
                'status', 'processed_at',
            ])
            # One audit entry per affected connection so the per-tenant
            # audit log surfaces "your IG integration was force-revoked
            # because the authorising user removed our app."
            for cid in affected_ids:
                record(
                    action=AuditLog.Action.UPDATE,
                    resource_type='integration_connection',
                    resource_id=cid,
                    request=None,  # no authenticated user — Meta-initiated
                    metadata={
                        'event': 'force_disconnected_by_meta_deletion',
                        'fb_user_id': fb_user_id,
                        'deletion_request_id': record_row.pk,
                    },
                )

        # Build the public status URL Meta hands back to the user.
        status_path = f'/api/integrations/meta/data-deletion-status/{confirmation_code}/'
        public_base = getattr(_s, 'PUBLIC_BASE_URL', '').rstrip('/')
        status_url = (
            f'{public_base}{status_path}' if public_base
            else status_path
        )

        return Response(
            {
                'url': status_url,
                'confirmation_code': confirmation_code,
            },
            status=status.HTTP_200_OK,
        )


class DataDeletionStatusView(APIView):
    """Public status endpoint — user follows the URL Meta gave them
    to verify their deletion request was honoured.

    Returns a minimal JSON payload (no PII). The confirmation_code is
    256 bits of entropy so it serves as both lookup key and capability
    (knowing the code IS authorisation to read its status)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Deletion status'),
            404: OpenApiResponse(description='Unknown confirmation code'),
        },
    )
    def get(self, request, code: str):
        try:
            row = DataDeletionRequest.objects.get(confirmation_code=code)
        except DataDeletionRequest.DoesNotExist:
            return Response(
                {'detail': 'Unknown confirmation code.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({
            'confirmation_code': row.confirmation_code,
            'status': row.status,
            'requested_at': row.requested_at.isoformat(),
            'processed_at': row.processed_at.isoformat() if row.processed_at else None,
            'integrations_revoked': len(row.affected_connection_ids or []),
            'note': (
                'Your Lumè authorization for this app has been revoked. '
                'Conversation history between you and individual spas is '
                'retained as part of their business records — to delete '
                'that, contact the spa directly.'
            ),
        })


# ── Social inbox API (ADR 0027 §6 — read surface for /social UI) ───


class SocialPermission(IntegrationPermission):
    """Same gate as the rest of integrations — owner + manager only.

    The inbox surfaces customer-typed message bodies which may
    incidentally contain PHI; access is restricted to roles that
    already have organisation-wide reach.
    """


class SocialThreadListView(APIView):
    """List threads in the current tenant, newest activity first.

    Query params:
      ?unread=1     — only threads with `read_at IS NULL`
      ?provider=instagram  — filter by provider key
    """

    permission_classes = [SocialPermission]

    def get(self, request):
        tenant = get_current_tenant()
        qs = SocialThread.objects.filter(tenant=tenant).select_related(
            'customer', 'connection',
        ).order_by('-last_message_at')

        if request.query_params.get('unread') == '1':
            qs = qs.filter(read_at__isnull=True)
        provider = request.query_params.get('provider')
        if provider:
            qs = qs.filter(provider=provider)

        return Response({
            'count': qs.count(),
            'threads': [_serialise_thread_summary(t) for t in qs[:200]],
        })


class SocialThreadDetailView(APIView):
    """Full thread + every message in chronological order.

    PHI audit-logged: detail-reads are recorded (`READ` action on
    `social_thread`) because message bodies may contain incidental
    health information.
    """

    permission_classes = [SocialPermission]

    def get(self, request, pk: int):
        tenant = get_current_tenant()
        try:
            thread = SocialThread.objects.select_related(
                'customer', 'connection',
            ).get(tenant=tenant, pk=pk)
        except SocialThread.DoesNotExist:
            return Response(
                {'detail': 'Thread not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        messages = list(
            SocialMessage.objects.filter(thread=thread).order_by('created_at')
        )

        record(
            action=AuditLog.Action.READ,
            resource_type='social_thread',
            resource_id=thread.pk,
            request=request,
            metadata={
                'event': 'thread_read',
                'message_count': len(messages),
                'customer_id': thread.customer_id,
            },
        )

        return Response({
            'thread': _serialise_thread_summary(thread),
            'messages': [_serialise_message(m) for m in messages],
        })


class SocialThreadMarkReadView(APIView):
    """Stamp `read_at = now` on a thread. Idempotent (re-marking a
    read thread is a no-op rather than re-stamping)."""

    permission_classes = [SocialPermission]

    def post(self, request, pk: int):
        tenant = get_current_tenant()
        try:
            thread = SocialThread.objects.get(tenant=tenant, pk=pk)
        except SocialThread.DoesNotExist:
            return Response(
                {'detail': 'Thread not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if thread.read_at is None:
            thread.read_at = timezone.now()
            thread.save(update_fields=['read_at', 'updated_at'])
        return Response({'read_at': thread.read_at.isoformat()})


def _serialise_thread_summary(thread: SocialThread) -> dict:
    """Compact list-row shape. The full body of every message lives
    on the detail endpoint — the list never carries content."""
    customer = thread.customer
    return {
        'id': thread.id,
        'provider': thread.provider,
        'external_username': thread.external_username,
        'last_message_at': thread.last_message_at.isoformat(),
        'last_inbound_at': (
            thread.last_inbound_at.isoformat()
            if thread.last_inbound_at else None
        ),
        'read_at': thread.read_at.isoformat() if thread.read_at else None,
        'is_unread': thread.read_at is None,
        'customer': {
            'id': customer.id,
            'full_name': customer.full_name,
            'is_social_guest': customer.is_social_guest,
            'instagram_handle': customer.instagram_handle,
            'acquisition_source': customer.acquisition_source,
        },
    }


def _serialise_message(msg: SocialMessage) -> dict:
    return {
        'id': msg.id,
        'direction': msg.direction,
        'body': msg.body,
        'media_urls': [u for u in msg.media_urls.splitlines() if u],
        'status': msg.status,
        'sent_by_id': msg.sent_by_id,
        'received_at': msg.received_at.isoformat() if msg.received_at else None,
        'created_at': msg.created_at.isoformat(),
    }
