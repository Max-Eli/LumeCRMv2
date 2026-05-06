"""Django admin for invoices.

Read-mostly: the lifecycle is supposed to flow through the API
(`close()`, `reopen()`, `void()`) so the audit trail is consistent.
Admin is for inspection and the rare manual fix; mutating fields
through the form bypasses the audit-log entries that the model methods
write, so we keep most fields read-only and warn in the help text.
"""

from django.contrib import admin

from .models import Invoice, InvoiceLineItem


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0
    can_delete = False
    fields = (
        'description', 'service', 'quantity', 'unit_price_cents',
        'tax_rate_percent', 'line_subtotal_cents', 'line_tax_cents', 'created_at',
    )
    readonly_fields = (
        'line_subtotal_cents', 'line_tax_cents', 'created_at',
    )


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'tenant', 'customer', 'status', 'total_cents',
        'closed_at', 'reopen_count', 'created_at',
    )
    list_filter = ('status', 'tenant', 'payment_method')
    search_fields = ('customer__first_name', 'customer__last_name', 'payment_reference')
    autocomplete_fields = ('customer', 'appointment')
    readonly_fields = (
        'subtotal_cents', 'tax_cents', 'total_cents',
        'closed_at', 'closed_by',
        'reopened_at', 'reopened_by', 'reopen_count',
        'voided_at', 'voided_by',
        'created_at', 'updated_at', 'created_by',
    )
    inlines = [InvoiceLineItemInline]

    fieldsets = (
        (None, {
            'fields': ('tenant', 'customer', 'appointment', 'status'),
            'description': (
                'State changes here bypass the audit-logged transitions in '
                'Invoice.close()/reopen()/void(). Prefer the API actions '
                'unless you are intentionally fixing a bad row.'
            ),
        }),
        ('Money', {
            'fields': ('subtotal_cents', 'tax_cents', 'total_cents'),
        }),
        ('Payment', {
            'fields': ('payment_method', 'payment_reference', 'notes'),
        }),
        ('Lifecycle audit', {
            'fields': (
                ('closed_at', 'closed_by'),
                ('reopened_at', 'reopened_by'),
                'reopen_count',
                ('voided_at', 'voided_by'),
                'void_reason',
                ('created_at', 'created_by'),
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
