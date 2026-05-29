"""Custom user model for Lumè.

Users authenticate with email (no username field). All user-tenant relationships
live on `apps.tenants.TenantMembership` — this model is intentionally tenant-agnostic
so the same user record can hold memberships in multiple tenants and so platform
superusers (Lumè staff) can exist without being tied to any tenant.
"""

import datetime as dt
import secrets

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone as djtz


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

    # Email verification — set when the owner clicks the link in the
    # post-signup verification email. The dashboard renders a "verify
    # your email" banner until this is set; some surfaces (sending
    # marketing campaigns, inviting staff) gate on it.
    email_verified_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            "When the user verified their email by clicking the link in "
            "the verification email. Null = unverified. Pre-existing "
            "users created before self-serve signup remain null but are "
            "trusted (operator manually provisioned)."
        ),
    )

    objects = UserManager()

    def __str__(self):
        return self.email


# ── Email verification token (Phase 3 — self-serve signup) ─────────


def _generate_email_verification_token() -> str:
    """256-bit URL-safe token. Same shape as
    apps.portal.CustomerPortalToken — high entropy, path-safe,
    not derivable from the user's email."""
    return secrets.token_urlsafe(32)


# Window in which the verification link is usable. 7 days is the
# industry default — long enough that someone signing up on a Friday
# can verify Monday morning, short enough that a leaked email loses
# utility quickly.
EMAIL_VERIFICATION_EXPIRY = dt.timedelta(days=7)


class EmailVerificationToken(models.Model):
    """Single-use token sent to a freshly-signed-up user's email.

    Issued by ``apps.tenants.signup.create_signup_session`` immediately
    after the User + Tenant are created. The customer's verification
    email links to ``/verify-email/<token>``; the frontend POSTs to
    the consume endpoint which marks the User as verified.

    Security posture mirrors ``apps.portal.CustomerPortalToken``:
      - 256-bit ``secrets.token_urlsafe`` entropy
      - 7-day expiry — bounded blast radius if email leaks
      - Single-use (``used_at`` set atomically on consume)
      - Stored plaintext (token IS the credential; hashing prevents
        lookup-by-token without a full table scan)

    No FK to tenant — verification is a User-level concept that
    applies across every membership the user holds (signup creates
    one membership, but a user could later be invited into others).
    """

    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='verification_tokens',
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_email_verification_token,
        db_index=True,
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)
    requested_user_agent = models.CharField(max_length=400, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self) -> str:
        state = 'used' if self.used_at else 'pending'
        return f'EmailVerificationToken<user={self.user_id} {state}>'

    @classmethod
    def issue(
        cls, *, user, requested_ip: str = '', requested_user_agent: str = '',
    ) -> 'EmailVerificationToken':
        """Create + persist a fresh token for ``user``. Caller dispatches
        the email after this returns."""
        return cls.objects.create(
            user=user,
            expires_at=djtz.now() + EMAIL_VERIFICATION_EXPIRY,
            requested_ip=requested_ip or None,
            requested_user_agent=(requested_user_agent or '')[:400],
        )

    @property
    def is_valid(self) -> bool:
        """True iff the token can still be consumed: not used + not expired.
        Caller (consume view) re-checks inside an atomic block."""
        return self.used_at is None and self.expires_at > djtz.now()
