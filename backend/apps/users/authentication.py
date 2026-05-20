"""JWT authentication for the Lumè staff mobile app.

The web CRM authenticates with Django session cookies. Native apps
can't cleanly carry a session cookie + CSRF token, so the staff mobile
app authenticates with JWT bearer tokens instead (see ADR 0031). This
class is additive — it sits ahead of `SessionAuthentication` in
`DEFAULT_AUTHENTICATION_CLASSES` and returns `None` when there is no
`Authorization: Bearer …` header, so every existing browser request
falls through to session auth completely unchanged.

`MobileJWTAuthentication` extends SimpleJWT's class with one critical
addition: it re-resolves `request.tenant_membership`.

`TenantMiddleware` runs *before* DRF authentication. For a JWT request
the user is still anonymous at middleware time, so the middleware
leaves `request.tenant_membership` as `None`. We resolve it here, once
the token has identified the user — and reject the request outright if
the user has no active membership in the tenant named by the
`X-Tenant-Slug` header. That is the mobile equivalent of the web's
subdomain `_enforce_tenant_isolation` guarantee: a token can only ever
act inside a tenant its owner actually belongs to.
"""

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.tenants.models import TenantMembership


class MobileJWTAuthentication(JWTAuthentication):
    """SimpleJWT auth that also binds the request's tenant membership."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            # No bearer token — let SessionAuthentication take the request.
            return None

        user, validated_token = result

        # `request` is the DRF Request; `_request` is the Django
        # HttpRequest that TenantMiddleware annotated with `.tenant`.
        django_request = request._request
        tenant = getattr(django_request, 'tenant', None)

        if tenant is not None:
            membership = (
                TenantMembership.objects
                .filter(tenant=tenant, user=user, is_active=True)
                .select_related('job_title')
                .first()
            )
            if membership is None:
                # Valid token, but the holder is not a member of the
                # workspace they addressed. Fail closed.
                raise AuthenticationFailed(
                    'No active membership for this workspace.',
                    code='tenant_membership_required',
                )
            django_request.tenant_membership = membership

        return user, validated_token
