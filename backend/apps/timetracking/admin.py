from django.contrib import admin

from .models import TimeEntry


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'tenant', 'membership',
        'clock_in_at', 'clock_out_at', 'source',
        'created_by',
    )
    list_filter = ('tenant', 'source')
    search_fields = (
        'membership__user__email',
        'membership__user__first_name',
        'membership__user__last_name',
        'notes',
    )
    readonly_fields = (
        'tenant', 'membership',
        'clock_in_at', 'clock_out_at',
        'created_by', 'edited_at', 'edited_by',
        'created_at', 'updated_at',
    )
