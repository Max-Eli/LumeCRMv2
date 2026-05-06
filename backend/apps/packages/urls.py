from rest_framework.routers import DefaultRouter

from .views import PackageViewSet, PurchasedPackageViewSet

router = DefaultRouter()
router.register('packages', PackageViewSet, basename='package')
router.register(
    'purchased-packages',
    PurchasedPackageViewSet,
    basename='purchased-package',
)

urlpatterns = router.urls
