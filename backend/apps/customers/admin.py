from django.contrib import admin

from .models import Customer, CustomerTag


@admin.register(CustomerTag)
class CustomerTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'tenant', 'sort_order')
    list_filter = ('tenant',)
    search_fields = ('name', 'tenant__name')
    autocomplete_fields = ('tenant',)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        'last_name', 'first_name', 'email', 'phone',
        'status', 'referral_code', 'tenant', 'created_at',
    )
    list_filter = ('status', 'sex', 'tenant', 'email_opt_in', 'sms_opt_in')
    search_fields = (
        'first_name', 'last_name', 'preferred_name',
        'email', 'phone', 'external_id', 'referral_code',
    )
    autocomplete_fields = ('tenant', 'tags')
    readonly_fields = ('referral_code', 'created_at', 'updated_at')
    fieldsets = (
        ('Identity', {
            'fields': ('tenant', 'first_name', 'last_name', 'preferred_name', 'email', 'phone', 'status', 'tags'),
        }),
        ('Demographics', {
            'fields': ('date_of_birth', 'sex'),
        }),
        ('Address', {
            'fields': ('address_line1', 'address_line2', 'city', 'state', 'zip_code'),
        }),
        ('Emergency contact', {
            'fields': ('emergency_name', 'emergency_phone', 'emergency_relationship'),
        }),
        ('Medical (PHI)', {
            'fields': ('medical_history', 'allergies', 'medications', 'skin_type_fitzpatrick'),
            'classes': ('collapse',),
        }),
        ('CRM', {
            'fields': ('notes', 'referral_source', 'email_opt_in', 'sms_opt_in'),
        }),
        ('Provenance', {
            'fields': ('external_id', 'external_source', 'imported_at'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
