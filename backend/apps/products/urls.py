from rest_framework.routers import DefaultRouter

from .views import ProductCategoryViewSet, ProductViewSet

router = DefaultRouter()
router.register('products', ProductViewSet, basename='product')
router.register('product-categories', ProductCategoryViewSet, basename='product-category')

urlpatterns = router.urls
