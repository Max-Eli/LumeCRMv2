from rest_framework.routers import DefaultRouter

from .views import ServiceCategoryViewSet, ServiceViewSet

router = DefaultRouter()
router.register('services', ServiceViewSet, basename='service')
router.register('service-categories', ServiceCategoryViewSet, basename='service-category')

urlpatterns = router.urls
