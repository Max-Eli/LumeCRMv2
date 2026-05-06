from django.contrib import admin

from .models import FormTemplate, ServiceFormAssignment


class ServiceFormAssignmentInline(admin.TabularInline):
    model = ServiceFormAssignment
    extra = 0
    fields = ('service',)
    autocomplete_fields = ('service',)
    fk_name = 'form_template'


@admin.register(FormTemplate)
class FormTemplateAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'tenant', 'form_type', 'recurrence', 'version', 'is_active',
        'updated_at',
    )
    list_filter = ('form_type', 'recurrence', 'is_active', 'tenant')
    search_fields = ('name', 'description', 'tenant__name')
    readonly_fields = ('version', 'created_at', 'updated_at')
    autocomplete_fields = ('tenant',)
    fieldsets = (
        (None, {'fields': ('tenant', 'name', 'description', 'form_type', 'recurrence', 'is_active')}),
        ('Schema', {'fields': ('schema', 'version'), 'classes': ('collapse',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    inlines = [ServiceFormAssignmentInline]


@admin.register(ServiceFormAssignment)
class ServiceFormAssignmentAdmin(admin.ModelAdmin):
    list_display = ('form_template', 'service', 'tenant', 'created_at')
    list_filter = ('tenant',)
    search_fields = ('form_template__name', 'service__name')
    autocomplete_fields = ('form_template', 'service', 'tenant')
