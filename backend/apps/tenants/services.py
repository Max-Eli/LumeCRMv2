"""Tenant onboarding service functions.

Use `create_tenant_with_defaults` to provision a new tenant with seeded job titles,
a default Location, and an Owner membership assigned to that location. This is the
canonical onboarding entry point — call it from the admin onboarding flow, signup
view, or management command.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone as djtz

from .models import (
    Invitation,
    JobTitle,
    Location,
    MembershipLocation,
    Tenant,
    TenantMembership,
)

User = get_user_model()


class InvitationError(Exception):
    """Raised when an invitation can't be created or accepted for a
    business reason (email already a member, token expired, etc.).
    View layer turns this into a 400 with detail from str(e)."""


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


# ── Staff invitations ────────────────────────────────────────────────


def invite_staff(
    tenant: Tenant,
    *,
    email: str,
    role: str,
    job_title: JobTitle | None = None,
    is_bookable: bool = False,
    invited_by,
) -> Invitation:
    """Create a pending Invitation and email the recipient.

    Raises `InvitationError` when:
      - the email is already an active member of this tenant
      - there's an unaccepted, unexpired invitation outstanding for
        this email + tenant (operator should resend the existing one
        rather than duplicating)

    Existing-User-different-tenant is fine — the same person can be
    invited to multiple spas. The accept flow attaches a new
    membership to the existing User.
    """
    email = email.strip().lower()

    # Already a member of this tenant?
    existing_member = TenantMembership.objects.filter(
        tenant=tenant, user__email__iexact=email,
    ).first()
    if existing_member is not None:
        raise InvitationError(
            f'{email} is already a member of this tenant '
            f'({existing_member.get_role_display()}).'
        )

    # Already an outstanding invitation?
    outstanding = Invitation.objects.filter(
        tenant=tenant, email__iexact=email,
        accepted_at__isnull=True,
        expires_at__gt=djtz.now(),
    ).first()
    if outstanding is not None:
        raise InvitationError(
            f'There is already a pending invitation for {email} '
            f'(expires {outstanding.expires_at:%b %d, %Y}). '
            'Resend or revoke the existing one before creating a new one.'
        )

    invitation = Invitation.objects.create(
        tenant=tenant,
        email=email,
        role=role,
        job_title=job_title,
        is_bookable=is_bookable,
        invited_by=invited_by,
    )

    _send_invitation_email(invitation)
    return invitation


def _send_invitation_email(invitation: Invitation) -> None:
    """Render + send the invitation email. Pulled out so a future
    "resend" action can reuse it without re-creating the Invitation
    row (preserves audit trail of original invite_by + created_at)."""
    base = settings.PUBLIC_BASE_URL.rstrip('/')
    accept_url = f'{base}/accept-invitation/{invitation.token}'
    invited_by_name = ''
    if invitation.invited_by_id:
        u = invitation.invited_by
        invited_by_name = (
            f'{u.first_name} {u.last_name}'.strip() or u.email
        )

    context = {
        'invitation': invitation,
        'tenant_name': invitation.tenant.name,
        'invited_by_name': invited_by_name,
        'accept_url': accept_url,
        'expires_at': invitation.expires_at,
        'role_label': dict(TenantMembership.Role.choices).get(
            invitation.role, invitation.role,
        ),
    }

    text_body = render_to_string('tenants/email/invitation.txt', context)
    html_body = render_to_string('tenants/email/invitation.html', context)

    from .email import tenant_from_email, tenant_reply_to

    reply_to = tenant_reply_to(invitation.tenant)

    msg = EmailMultiAlternatives(
        subject=f'You\'re invited to join {invitation.tenant.name} on Lumè CRM',
        body=text_body,
        from_email=tenant_from_email(invitation.tenant),
        to=[invitation.email],
        reply_to=[reply_to] if reply_to else None,
    )
    msg.attach_alternative(html_body, 'text/html')
    # fail_silently=False — caller (the invite endpoint) needs to know
    # if SES rejected the send so it can return a clear error.
    msg.send(fail_silently=False)


@transaction.atomic
def accept_invitation(
    token: str,
    *,
    password: str,
    first_name: str,
    last_name: str,
) -> tuple:
    """Accept a pending invitation: create-or-attach the User, create
    the TenantMembership, mark invitation accepted.

    Atomic: either the whole acceptance succeeds or none of it does.
    The invitation row is locked via `select_for_update` so two
    simultaneous accepts of the same token can't both create
    memberships.

    Returns `(user, membership)`.

    Raises `InvitationError` when:
      - the token isn't recognized
      - the invitation already accepted
      - the invitation expired
      - a user already exists with this email (this path is reserved
        for new-user signup; existing users must use the legacy
        attach-existing flow to avoid clobbering passwords)
    """
    try:
        # Lock only the Invitation row, not the joined tables — the
        # nullable `job_title` FK would otherwise yield a LEFT OUTER
        # JOIN that Postgres rejects with "FOR UPDATE cannot be
        # applied to the nullable side of an outer join."
        invitation = (
            Invitation.objects
            .select_for_update(of=('self',))
            .select_related('tenant', 'job_title')
            .get(token=token)
        )
    except Invitation.DoesNotExist:
        raise InvitationError('Invitation not found.')

    if invitation.accepted_at is not None:
        raise InvitationError('This invitation has already been accepted.')
    if invitation.expires_at <= djtz.now():
        raise InvitationError('This invitation has expired.')

    existing_user = User.objects.filter(email__iexact=invitation.email).first()
    if existing_user is not None:
        raise InvitationError(
            'An account already exists for this email. Sign in with your '
            'existing password instead; the spa owner can attach you '
            'directly without an invitation.'
        )

    user = User.objects.create_user(
        email=invitation.email,
        password=password,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
    )

    membership = TenantMembership.objects.create(
        user=user,
        tenant=invitation.tenant,
        role=invitation.role,
        job_title=invitation.job_title,
        is_bookable=invitation.is_bookable,
        is_active=True,
    )

    default_location = invitation.tenant.locations.filter(is_default=True).first()
    if default_location is not None:
        MembershipLocation.objects.create(
            membership=membership,
            location=default_location,
            is_active=True,
        )

    invitation.accepted_at = djtz.now()
    invitation.accepted_by_user = user
    invitation.save(update_fields=['accepted_at', 'accepted_by_user', 'updated_at'])

    return user, membership
