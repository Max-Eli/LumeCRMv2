from rest_framework.routers import DefaultRouter

from .views import GiftCardViewSet

router = DefaultRouter()
router.register('gift-cards', GiftCardViewSet, basename='gift-card')

urlpatterns = router.urls
