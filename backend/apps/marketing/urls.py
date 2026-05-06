"""URL routing for the marketing surface.

Mounted at `/api/`. Phase 1L sessions 1 + 2 ship Audiences,
Templates, and Campaigns. Automations + the send worker land in
session 3.
"""

from rest_framework.routers import DefaultRouter

from django.urls import path

from .views import (
    AudienceViewSet,
    AutomationViewSet,
    CampaignViewSet,
    CustomerMarketingHistoryView,
    MarketingTemplateViewSet,
)
from .views_public import PublicUnsubscribeView

router = DefaultRouter()
router.register(r'marketing/audiences', AudienceViewSet, basename='marketing-audience')
router.register(r'marketing/templates', MarketingTemplateViewSet, basename='marketing-template')
router.register(r'marketing/campaigns', CampaignViewSet, basename='marketing-campaign')
router.register(r'marketing/automations', AutomationViewSet, basename='marketing-automation')
router.register(
    r'marketing/customer-sends',
    CustomerMarketingHistoryView,
    basename='marketing-customer-sends',
)

urlpatterns = [
    *router.urls,
    # Public unsubscribe — no auth, tokenized.
    path(
        'marketing/unsubscribe/<str:token>/',
        PublicUnsubscribeView.as_view(),
        name='marketing-unsubscribe',
    ),
]
