from django.contrib import admin

from .models import JobTitle, Location, MembershipLocation, Tenant, TenantMembership


class JobTitleInline(admin.TabularInline):
    model = JobTitle
    extra = 0
    fields = ('name', 'is_clinical', 'sort_order')


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 0
    fields = ('user', 'role', 'job_title', 'is_bookable', 'is_active')
    autocomplete_fields = ('user', 'job_title')


class LocationInline(admin.TabularInline):
    model = Location
    extra = 0
    fields = ('name', 'slug', 'is_default', 'is_active', 'timezone', 'city', 'state')
    show_change_link = True


class MembershipLocationInline(admin.TabularInline):
    model = MembershipLocation
    extra = 0
    fields = ('location', 'is_active')
    autocomplete_fields = ('location',)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'status', 'twilio_from_number', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'slug')
    readonly_fields = ('created_at', 'updated_at')

    # Per-site fields (timezone, address, hours, phone, email) live on
    # `Location` after the Phase 4E cleanup — they're managed via the
    # `LocationInline` below (or the dedicated Location admin). What
    # stays here is purely account-level identity + branding +
    # platform-provisioned resources (e.g. the assigned Twilio TFN).
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'status')}),
        ('Branding', {'fields': ('primary_color', 'logo_url')}),
        # SMS sender per spa. Platform admin sets this manually after
        # the Twilio TFN is provisioned + verified. E.164 format —
        # e.g. "+18885551234". When blank, outbound SMS falls back to
        # the platform-default TWILIO_FROM_NUMBER (one shared toll-free
        # used for the first cohort of spas before each gets their own).
        ('SMS sending', {'fields': ('twilio_from_number',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    inlines = [LocationInline, JobTitleInline, TenantMembershipInline]


@admin.register(JobTitle)
class JobTitleAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'is_clinical', 'sort_order')
    list_filter = ('is_clinical', 'tenant')
    search_fields = ('name', 'tenant__name')
    autocomplete_fields = ('tenant',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'slug', 'is_default', 'is_active', 'timezone', 'city', 'state')
    list_filter = ('is_default', 'is_active', 'tenant')
    search_fields = ('name', 'slug', 'tenant__name', 'city')
    autocomplete_fields = ('tenant',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (None, {'fields': ('tenant', 'name', 'slug', 'is_default', 'is_active', 'timezone')}),
        ('Contact', {'fields': ('phone', 'email')}),
        ('Address', {'fields': ('address_line1', 'address_line2', 'city', 'state', 'zip_code')}),
        ('Hours', {'fields': ('business_open_time', 'business_close_time')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'tenant', 'role', 'job_title', 'is_bookable', 'is_active')
    list_filter = ('role', 'is_bookable', 'is_active', 'tenant')
    search_fields = ('user__email', 'tenant__name')
    autocomplete_fields = ('user', 'tenant', 'job_title')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (None, {'fields': ('user', 'tenant', 'role', 'job_title', 'is_bookable', 'is_active')}),
        ('Permission overrides', {
            'fields': ('extra_permissions', 'revoked_permissions'),
            'description': 'JSON arrays of permission strings. See apps.tenants.permissions.P for the catalog.',
        }),
        ('HIPAA', {'fields': ('hipaa_training_acknowledged_at',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    inlines = [MembershipLocationInline]


@admin.register(MembershipLocation)
class MembershipLocationAdmin(admin.ModelAdmin):
    list_display = ('membership', 'location', 'is_active', 'created_at')
    list_filter = ('is_active', 'location__tenant', 'location')
    search_fields = ('membership__user__email', 'location__name', 'location__tenant__name')
    autocomplete_fields = ('membership', 'location')
