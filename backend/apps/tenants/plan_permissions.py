"""DRF permission classes for plan-based feature gating.

Separate from ``apps.tenants.permissions`` because that module is the
role + permission catalog (who can do what within the tenant); this
module is the tier catalog (which features the tenant's subscription
includes). Both compose: an endpoint can require BOTH a permission
AND a plan feature.

Example usage:

    from apps.tenants.permissions import PermissionRequired, P
    from apps.tenants.plan_permissions import PlanFeatureRequired
    from apps.tenants.plans import F_EMAIL_MARKETING

    class CampaignViewSet(...):
        permission_classes = [
            PermissionRequired(P.SEND_MARKETING_CAMPAIGN),
            PlanFeatureRequired(F_EMAIL_MARKETING),
        ]

A missing PERMISSION returns 403 (you can't do that). A missing PLAN
FEATURE returns 402 with a structured body (upgrade your plan to get
this) so the frontend can route to a tier-specific upsell instead of
showing a generic "access denied."
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission

from apps.tenants.plans import tenant_has_feature

if TYPE_CHECKING:
    from rest_framework.request import Request


class FeatureNotInPlan(APIException):
    """402 Payment Required — the caller's tenant plan doesn't include
    the feature this endpoint requires.

    Body shape (consumed by the frontend upsell modal):

        {
            "detail": "...human message...",
            "code": "feature_not_in_plan",
            "feature": "email_marketing",
            "current_plan": "starter",
            "upgrade_url": "/settings/billing"
        }

    The frontend reads ``feature`` + ``current_plan`` to render a
    tier-specific upsell ("Upgrade to Pro to send email campaigns").
    """

    status_code = 402
    default_code = 'feature_not_in_plan'
    default_detail = 'Your current plan does not include this feature.'

    def __init__(self, feature_key: str, current_plan: str):
        super().__init__(
            detail={
                'detail': (
                    f'Your current plan ({current_plan}) does not include '
                    f'the "{feature_key}" feature.'
                ),
                'code': self.default_code,
                'feature': feature_key,
                'current_plan': current_plan,
                # Where the frontend should send the operator. Owners
                # land at /settings/billing for self-serve plan changes
                # (where applicable) or a "book a demo" CTA for
                # Pro/Enterprise. The frontend can override per upsell
                # context — this is the default fallback.
                'upgrade_url': '/settings/billing',
            },
            code=self.default_code,
        )


def PlanFeatureRequired(feature_key: str) -> type[BasePermission]:
    """Factory that returns a DRF permission class gating on a single
    plan feature.

    Used in ``permission_classes`` as a class, not an instance — DRF
    instantiates it per request:

        permission_classes = [PlanFeatureRequired(F_EMAIL_MARKETING)]

    Returns 402 (via ``FeatureNotInPlan``) when the tenant lacks the
    feature, not 403, so the frontend can distinguish "you can't do
    this" from "your plan doesn't allow this."

    Grandfathered tenants always pass — see
    ``apps.tenants.plans.features_for``.

    Anonymous / cross-tenant requests fall through to False (the
    standard "not authenticated" 403) — this class is NEVER the only
    gate on an endpoint. Combine with the standard auth + tenant
    membership permissions.
    """

    class _PlanFeatureRequired(BasePermission):
        # The class-level message is the fallback DRF uses for 403 if
        # something falls through to False. The real customer-facing
        # message goes in the FeatureNotInPlan exception body.
        message = (
            f'This endpoint requires the "{feature_key}" feature, '
            f'which is not in your current plan.'
        )

        def has_permission(self, request: 'Request', view) -> bool:
            user = getattr(request, 'user', None)
            if not user or not user.is_authenticated:
                return False
            # Superuser bypass — platform admins debugging in any tenant.
            if user.is_superuser:
                return True

            membership = getattr(request, 'tenant_membership', None)
            if not membership:
                return False
            tenant = getattr(membership, 'tenant', None)
            if not tenant:
                return False

            if tenant_has_feature(tenant, feature_key):
                return True

            # The endpoint exists, the caller is authenticated and on the
            # right tenant — they just don't have this feature on their
            # plan. Raise 402 with the structured upsell payload.
            raise FeatureNotInPlan(
                feature_key=feature_key,
                current_plan=tenant.plan,
            )

        def has_object_permission(self, request, view, obj) -> bool:
            # The plan check is independent of which object is being
            # accessed — if has_permission passed, every object passes
            # too. Object-level permission gating lives on the
            # role-based permission classes that this composes with.
            return True

    # Stable repr for debug / DRF schema generation — without this the
    # class shows up as just "_PlanFeatureRequired" everywhere.
    _PlanFeatureRequired.__name__ = f'PlanFeatureRequired_{feature_key}'
    _PlanFeatureRequired.__qualname__ = _PlanFeatureRequired.__name__
    return _PlanFeatureRequired
