from django.contrib import admin

from .models import Product, ProductCategory


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'sort_order')
    list_filter = ('tenant',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'sku', 'tenant', 'category',
        'price_cents', 'stock_quantity', 'is_active',
    )
    list_filter = ('tenant', 'category', 'is_active', 'track_inventory')
    search_fields = ('name', 'sku')
    readonly_fields = ('created_at', 'updated_at')
