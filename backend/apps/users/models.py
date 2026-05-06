"""Custom user model for Lumè.

Users authenticate with email (no username field). All user-tenant relationships
live on `apps.tenants.TenantMembership` — this model is intentionally tenant-agnostic
so the same user record can hold memberships in multiple tenants and so platform
superusers (Lumè staff) can exist without being tied to any tenant.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Manager for the custom email-as-username User model.

    Required because we removed the `username` field — Django's default UserManager
    expects to receive a `username` positional argument that we don't have.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Authenticated principal in the system.

    Email is the unique identifier and the login credential. Tenant-scoped role
    and permissions are NOT stored on this model — see `apps.tenants.TenantMembership`
    for the per-tenant role + job_title + permission overrides.

    `is_superuser=True` is the standard Django flag granting Django-admin
    access. Distinct from `is_platform_admin` below — most platform admins
    don't need Django admin and shouldn't have it.

    `is_platform_admin=True` denotes Lumè-the-company staff who manage
    customer tenants from `/platform/*`. These accounts authenticate via
    a SEPARATE login flow (`/api/auth/platform/login/`) and are required
    to have ZERO TenantMembership rows — the customer auth surface and
    the platform admin auth surface are deliberately disjoint, with no
    path between them. See `apps.users.views.PlatformLoginView` and
    `apps.platform.permissions.PlatformPermission`.

    Personal contact fields (phone + address) live here, not on
    TenantMembership, because they're person-level — the same person
    has the same address regardless of which spa they work at. Per-spa
    fields (pay rate, employment type, hire date) live on the
    membership instead so a person who works at two centers can have
    different employment terms at each.
    """

    username = None
    email = models.EmailField('email address', unique=True)

    # Platform-admin flag — see class docstring. Distinct from is_superuser:
    # is_superuser is Django's stock admin-access flag; is_platform_admin is
    # OUR concept of "Lumè staff who manage customer tenants." A user can
    # be either, both, or neither, but in practice platform admins should
    # always have is_platform_admin=True and tenant users should always
    # have is_platform_admin=False.
    is_platform_admin = models.BooleanField(
        default=False,
        help_text=(
            "Lumè-the-platform staff. Authenticates via /api/auth/platform/login/ "
            "and accesses /platform/*. Must have zero TenantMembership rows — "
            "platform admins and tenant users are disjoint."
        ),
    )

    # Personal contact — populated by the staff editor at /staff/employees/[id].
    # All optional; the only required identity is email.
    phone = models.CharField(max_length=20, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=10, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email
