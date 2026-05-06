from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'user', 'tenant', 'resource_type', 'resource_id', 'ip_address')
    list_filter = ('action', 'tenant', 'resource_type')
    search_fields = ('user__email', 'resource_id', 'ip_address')
    readonly_fields = (
        'timestamp', 'tenant', 'user', 'action', 'resource_type', 'resource_id',
        'ip_address', 'user_agent', 'metadata',
    )
    date_hierarchy = 'timestamp'
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
