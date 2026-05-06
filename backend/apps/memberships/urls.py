from rest_framework.routers import DefaultRouter

from .views import MembershipPlanViewSet, SubscriptionViewSet

router = DefaultRouter()
router.register(
    'membership-plans', MembershipPlanViewSet, basename='membership-plan',
)
router.register(
    'subscriptions', SubscriptionViewSet, basename='subscription',
)

urlpatterns = router.urls
