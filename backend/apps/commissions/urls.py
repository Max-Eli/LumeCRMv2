from rest_framework.routers import DefaultRouter

from .views import CommissionEntryViewSet, CommissionRuleViewSet

router = DefaultRouter()
router.register(
    'commission-rules', CommissionRuleViewSet, basename='commission-rule',
)
router.register(
    'commission-entries', CommissionEntryViewSet, basename='commission-entry',
)

urlpatterns = router.urls
