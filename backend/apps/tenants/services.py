"""Tenant onboarding service functions.

Use `create_tenant_with_defaults` to provision a new tenant with seeded job titles,
a default Location, and an Owner membership assigned to that location. This is the
canonical onboarding entry point — call it from the admin onboarding flow, signup
view, or management command.
"""

from django.db import transaction

from .models import JobTitle, Location, MembershipLocation, Tenant, TenantMembership


DEFAULT_JOB_TITLES = [
    # (name, is_clinical, sort_order)
    ('Nurse Practitioner', True, 10),
    ('Registered Nurse', True, 20),
    ('Physician Assistant', True, 30),
    ('Aesthetician', False, 40),
    ('Laser Technician', False, 50),
    ('Massage Therapist', False, 60),
    ('Nail Technician', False, 70),
    ('Receptionist', False, 80),
    ('Owner-Operator', False, 90),
]

# Per-site fields that belong to `Location`, not `Tenant`. The
# onboarding kwargs may include these; they're routed to the default
# `Location` rather than the `Tenant` (which no longer carries them
# after the Phase 4E session 4 cleanup migration).
_PER_LOCATION_FIELDS = (
    'timezone',
    'phone',
    'email',
    'address_line1',
    'address_line2',
    'city',
    'state',
    'zip_code',
    'business_open_time',
    'business_close_time',
)


@transaction.atomic
def create_tenant_with_defaults(*, name: str, slug: str, owner_user, **tenant_kwargs) -> Tenant:
    """Create a new tenant, seed default job titles, create the default Location, and add the given user as Owner.

    Args:
        name: Display name (e.g. "Acme Med Spa")
        slug: Subdomain slug (e.g. "acmespa")
        owner_user: User instance who becomes the first Owner of this tenant
        **tenant_kwargs: extra fields. Account-level fields (status, branding)
            land on the Tenant; per-site fields (timezone, address, hours,
            phone, email) land on the seeded default Location.

    Returns:
        The created Tenant instance.
    """
    # Split kwargs by destination model so the per-site fields don't
    # try to set non-existent attributes on Tenant.
    location_kwargs = {
        field: tenant_kwargs.pop(field)
        for field in _PER_LOCATION_FIELDS
        if field in tenant_kwargs
    }

    tenant = Tenant.objects.create(name=name, slug=slug, **tenant_kwargs)

    location = Location.objects.create(
        tenant=tenant,
        name='Main',
        slug='main',
        is_default=True,
        is_active=True,
        **location_kwargs,
    )

    JobTitle.objects.bulk_create([
        JobTitle(tenant=tenant, name=name, is_clinical=is_clinical, sort_order=sort_order)
        for (name, is_clinical, sort_order) in DEFAULT_JOB_TITLES
    ])

    membership = TenantMembership.objects.create(
        user=owner_user,
        tenant=tenant,
        role=TenantMembership.Role.OWNER,
        is_active=True,
    )
    MembershipLocation.objects.create(
        membership=membership,
        location=location,
        is_active=True,
    )

    return tenant
