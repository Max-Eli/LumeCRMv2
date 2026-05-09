"""
seed_demo -- create or refresh a demo tenant with realistic medspa data.

Use this for:
  * Internal QA / smoke testing of the live product
  * Sales demos to prospective customers (the data is obviously
    fictional, but the shape mirrors a real medspa's day-to-day)

The command is idempotent. Re-running it on an existing demo tenant
updates the seeded records in place rather than duplicating them.
With `--reset`, the tenant + every owned record is deleted and rebuilt
from scratch (useful when the schema's evolved and old fixtures don't
fit anymore).

Usage:

    # Create or refresh the default demo tenant
    python manage.py seed_demo --owner-email demo-owner@lumecrm.com \
                               --owner-password '<strong-pw>'

    # Customize slug / name (e.g. for a per-prospect sandbox)
    python manage.py seed_demo --slug acme-demo --name "Acme Med Spa Demo" \
                               --owner-email acme@lumecrm.com \
                               --owner-password '<strong-pw>'

    # Wipe and recreate from scratch
    python manage.py seed_demo --slug demo --owner-email demo@... \
                               --owner-password '<pw>' --reset

The owner sign-in URL after seeding is:

    https://<slug>.<your-domain>/login

Data shape per seeded tenant:
  * Default Location ("Main") with realistic NYC business hours
  * 9 standard medspa job titles (from `create_tenant_with_defaults`)
  * 5 service categories (Injectables, Skin, Body, Wellness, Membership)
  * 12 services across those categories
  * 1 owner user (the operator -- you, for your own demo)
  * 3 provider users + 1 front-desk user, all bookable on the
    default Location with realistic schedules
  * 18 customers with varied PHI, tags, and history
  * 30 appointments spanning the previous 14 days and next 14 days
    (mix of completed, upcoming, and a couple of no-shows)

Names + emails use the `example.test` and `example.com` domains and
clearly-fictional first/last names so nothing here can be confused
with a real patient. Phone numbers use the 555 reserved prefix.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.appointments.models import Appointment
from apps.customers.models import Customer, CustomerTag
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import (
    JobTitle,
    Location,
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults


# ── Fixture data ────────────────────────────────────────────────────
#
# Picked to look like a real medspa menu without being any specific
# real one. Dollar amounts are typical Manhattan-tier pricing.

CATEGORIES = [
    # (slug, name, color, sort_order)
    ('injectables', 'Injectables',  '#7c3aed', 10),
    ('skin',        'Skin',         '#0ea5e9', 20),
    ('body',        'Body',         '#10b981', 30),
    ('wellness',    'Wellness',     '#f59e0b', 40),
    ('membership',  'Memberships',  '#ec4899', 50),
]

SERVICES = [
    # (category_slug, name, duration_minutes, buffer_minutes, price_dollars, description)
    ('injectables', 'Botox Consultation',         30,  5,  150, 'Initial consultation and treatment plan.'),
    ('injectables', 'Botox Treatment',            45, 10,  650, 'Per-area neurotoxin injection (forehead, glabella, crows feet).'),
    ('injectables', 'Dermal Filler',              60, 15,  900, 'Hyaluronic acid filler for cheeks, lips, or smile lines.'),
    ('injectables', 'Lip Enhancement',            45, 10,  750, 'Volume + definition; numbing included.'),
    ('skin',        'HydraFacial',                60, 10,  300, 'Multi-step exfoliation, extraction, and hydration.'),
    ('skin',        'Chemical Peel (Medium)',     45, 15,  450, 'TCA-based peel; 3-5 day social downtime.'),
    ('skin',        'Microneedling + PRP',        90, 15,  850, 'Collagen induction with platelet-rich plasma.'),
    ('skin',        'Laser Genesis',              45, 10,  400, 'Non-ablative skin tightening and tone correction.'),
    ('body',        'CoolSculpting Consultation', 30,  5,    0, 'Free assessment for fat-reduction candidacy.'),
    ('body',        'CoolSculpting Treatment',   120, 15, 1500, 'Per-cycle cryolipolysis.'),
    ('wellness',    'IV Hydration',               45, 10,  225, 'Vitamin + electrolyte drip, 1L saline.'),
    ('membership',  'Glow Membership (monthly)',  15,  0,  199, 'Monthly recurring; 10% off all services + free monthly facial.'),
]

CUSTOMER_TAGS = [
    # (name, color)
    ('VIP',         '#dc2626'),
    ('New patient', '#10b981'),
    ('Member',      '#7c3aed'),
    ('Referral',    '#f59e0b'),
]

# Fictional patients. First/last names obviously fake; PHI realistic
# in shape but invented. Phone numbers use 555-01XX (reserved per
# NANPA for fiction).
CUSTOMERS = [
    # (first, last, email, phone, dob, sex, fitz, tags, notes)
    ('Aria',     'Holloway',   'aria.h@example.test',     '555-0101', '1988-03-12', 'female', 3, ['VIP', 'Member'],     'Prefers afternoon appointments. Allergic to lidocaine.'),
    ('Beatrix',  'Ng',         'bea.ng@example.test',     '555-0102', '1995-07-21', 'female', 4, ['New patient'],       ''),
    ('Cassia',   'Okafor',     'cas.o@example.test',      '555-0103', '1979-11-04', 'female', 5, ['VIP', 'Referral'],   'Referred by Aria H.'),
    ('Devon',    'Park',       'devon@example.test',      '555-0104', '1991-04-30', 'male',   2, ['Member'],            ''),
    ('Esme',     'Liu',        'esme.l@example.test',     '555-0105', '1985-09-09', 'female', 3, ['VIP'],               'Long-term Botox patient. Sensitive to retinoids.'),
    ('Florian',  'Marsh',      'flo.m@example.test',      '555-0106', '2000-02-17', 'male',   4, ['New patient'],       ''),
    ('Greta',    'Vance',      'greta.v@example.test',    '555-0107', '1972-12-01', 'female', 2, [],                    ''),
    ('Hugo',     'Asante',     'hugo.a@example.test',     '555-0108', '1983-06-14', 'male',   5, ['Member'],            ''),
    ('Indira',   'Cho',        'indira.c@example.test',   '555-0109', '1994-08-22', 'female', 4, ['Referral'],          'Referred by Devon Park.'),
    ('Juniper',  'Adelaide',   'juni.a@example.test',     '555-0110', '1990-01-05', 'female', 3, ['VIP', 'Member'],     'Wedding in 6 months -- working through filler / glow plan.'),
    ('Kasimir',  'Petrov',     'kas.p@example.test',      '555-0111', '1976-05-18', 'male',   2, [],                    ''),
    ('Liora',    'Bennett',    'liora.b@example.test',    '555-0112', '1989-10-03', 'female', 3, ['New patient'],       ''),
    ('Maeve',    'Strand',     'maeve.s@example.test',    '555-0113', '1992-12-26', 'female', 4, ['Member'],            ''),
    ('Nikolai',  'Ross',       'niko.r@example.test',     '555-0114', '1981-03-29', 'male',   3, ['VIP'],               ''),
    ('Olive',    'Tanaka',     'olive.t@example.test',    '555-0115', '1998-07-07', 'female', 4, ['New patient'],       ''),
    ('Pierce',   'Quinn',      'pierce.q@example.test',   '555-0116', '1974-09-11', 'male',   2, [],                    ''),
    ('Quincey',  'Hartwell',   'quin.h@example.test',     '555-0117', '1996-04-04', 'female', 5, ['Member', 'Referral'], 'Referred by Esme Liu.'),
    ('Rumi',     'Kapoor',     'rumi.k@example.test',     '555-0118', '1987-11-13', 'female', 4, ['VIP'],               ''),
]

# Staff. The owner is created from --owner-email; these are providers
# + a front-desk user who get fictional emails on the demo subdomain.
STAFF = [
    # (first, last, email_local, role, job_title)
    ('Sloane',  'Park',     'sloane',    TenantMembership.Role.PROVIDER,   'Nurse Practitioner'),
    ('Tariq',   'Mensah',   'tariq',     TenantMembership.Role.PROVIDER,   'Registered Nurse'),
    ('Una',     'Solano',   'una',       TenantMembership.Role.PROVIDER,   'Aesthetician'),
    ('Vesper',  'Kim',      'vesper',    TenantMembership.Role.FRONT_DESK, 'Receptionist'),
]


class Command(BaseCommand):
    help = 'Create or refresh a demo tenant with realistic medspa fixture data.'

    def add_arguments(self, parser):
        parser.add_argument('--slug', default='demo', help='Tenant subdomain slug. Default: "demo".')
        parser.add_argument('--name', default='Lumè Demo Spa', help='Tenant display name.')
        parser.add_argument('--owner-email', required=True, help='Email of the owner user. Created if absent.')
        parser.add_argument('--owner-password', required=True, help='Password to set on the owner user.')
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Wipe the existing tenant + all data before reseeding. Use when a fixture refresh is needed.',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        slug: str = opts['slug']
        name: str = opts['name']
        owner_email: str = opts['owner_email']
        owner_password: str = opts['owner_password']
        reset: bool = opts['reset']

        User = get_user_model()

        # ── Reset path ────────────────────────────────────────────
        if reset:
            existing = Tenant.objects.filter(slug=slug).first()
            if existing:
                self.stdout.write(self.style.WARNING(
                    f'--reset: deleting existing tenant "{slug}" and all its data...'
                ))
                existing.delete()  # cascades through TenantedModel children

        # ── Owner user ────────────────────────────────────────────
        owner, owner_created = User.objects.get_or_create(
            email=owner_email,
            defaults={'first_name': 'Demo', 'last_name': 'Owner'},
        )
        if owner.is_platform_admin:
            raise CommandError(
                f'{owner_email} is a platform admin. Pick a different email for the demo owner '
                'so platform/tenant worlds stay disjoint.'
            )
        owner.set_password(owner_password)
        owner.is_active = True
        owner.save()
        self.stdout.write(
            f'Owner: {owner_email} ({"created" if owner_created else "updated"})'
        )

        # ── Tenant ────────────────────────────────────────────────
        tenant = Tenant.objects.filter(slug=slug).first()
        if tenant is None:
            tenant = create_tenant_with_defaults(
                name=name,
                slug=slug,
                owner_user=owner,
                # Tenant model defaults to TRIAL; the request middleware
                # only resolves ACTIVE tenants -- a demo tenant in TRIAL
                # silently gets 403 on every API call. Set ACTIVE here.
                status=Tenant.Status.ACTIVE,
                # Per-location fields go to the seeded default Location.
                timezone='America/New_York',
                phone='555-0100',
                email='hello@example.test',
                address_line1='123 Madison Ave',
                city='New York',
                state='NY',
                zip_code='10016',
                business_open_time='09:00:00',
                business_close_time='19:00:00',
            )
            self.stdout.write(self.style.SUCCESS(f'Created tenant "{slug}".'))
        else:
            # Update name + force ACTIVE status (in case the tenant was
            # created before this fix landed and is still in TRIAL).
            dirty = False
            if tenant.name != name:
                tenant.name = name
                dirty = True
            if tenant.status != Tenant.Status.ACTIVE:
                tenant.status = Tenant.Status.ACTIVE
                dirty = True
            if dirty:
                tenant.save()
            # Make sure owner has an active membership
            membership, _ = TenantMembership.objects.get_or_create(
                user=owner, tenant=tenant,
                defaults={'role': TenantMembership.Role.OWNER, 'is_active': True},
            )
            if membership.role != TenantMembership.Role.OWNER or not membership.is_active:
                membership.role = TenantMembership.Role.OWNER
                membership.is_active = True
                membership.save()
            self.stdout.write(f'Tenant "{slug}" already exists; refreshing data.')

        location = Location.objects.filter(tenant=tenant, is_default=True).first()
        if location is None:
            raise CommandError(f'Tenant "{slug}" has no default Location -- this should not happen.')

        # ── Customer tags ─────────────────────────────────────────
        tag_by_name = {}
        for sort_order, (tag_name, color) in enumerate(CUSTOMER_TAGS, start=10):
            tag, _ = CustomerTag.objects.update_or_create(
                tenant=tenant, name=tag_name,
                defaults={'color': color, 'sort_order': sort_order * 10},
            )
            tag_by_name[tag_name] = tag

        # ── Service categories + services ─────────────────────────
        category_by_slug = {}
        for slug_, cat_name, color, sort_order in CATEGORIES:
            cat, _ = ServiceCategory.objects.update_or_create(
                tenant=tenant, name=cat_name,
                defaults={'color': color, 'sort_order': sort_order},
            )
            category_by_slug[slug_] = cat

        for cat_slug, svc_name, duration, buffer_min, price_dollars, desc in SERVICES:
            Service.objects.update_or_create(
                tenant=tenant, name=svc_name,
                defaults={
                    'category': category_by_slug[cat_slug],
                    'description': desc,
                    'duration_minutes': duration,
                    'buffer_minutes': buffer_min,
                    'price_cents': price_dollars * 100,
                    'tax_rate_percent': Decimal('0'),
                    'service_type': Service.ServiceType.REGULAR,
                    'is_bookable_online': True,
                    'is_active': True,
                },
            )

        # ── Staff ─────────────────────────────────────────────────
        provider_users = []
        for first, last, email_local, role, job_title_name in STAFF:
            email = f'{email_local}@{slug}.example.test'
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={'first_name': first, 'last_name': last},
            )
            user.is_active = True
            user.save()
            membership, _ = TenantMembership.objects.update_or_create(
                user=user, tenant=tenant,
                defaults={'role': role, 'is_active': True},
            )
            # Assign job title
            job_title = JobTitle.objects.filter(tenant=tenant, name=job_title_name).first()
            if job_title and membership.job_title_id != job_title.id:
                membership.job_title = job_title
                membership.save(update_fields=['job_title'])
            # Mark providers as bookable
            if role == TenantMembership.Role.PROVIDER:
                if not membership.is_bookable:
                    membership.is_bookable = True
                    membership.save(update_fields=['is_bookable'])
                provider_users.append(user)
            # Assign to default location
            MembershipLocation.objects.update_or_create(
                membership=membership, location=location,
                defaults={'is_active': True},
            )

        # ── Customers ─────────────────────────────────────────────
        customer_objs = []
        for c in CUSTOMERS:
            first, last, email, phone, dob, sex, fitz, tags, notes = c
            customer, _ = Customer.objects.update_or_create(
                tenant=tenant, email=email,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'phone': phone,
                    'date_of_birth': dob,
                    'sex': sex,
                    'skin_type_fitzpatrick': fitz,
                    'notes': notes,
                    'status': Customer.Status.ACTIVE,
                    'email_opt_in': True,
                    'sms_opt_in': True,
                    'city': 'New York',
                    'state': 'NY',
                    'zip_code': '10016',
                },
            )
            # Sync tags (replace-set)
            customer.tags.set([tag_by_name[t] for t in tags if t in tag_by_name])
            customer_objs.append(customer)

        # ── Appointments ──────────────────────────────────────────
        # Spread 30 appointments across [-14, +14] days. Mix statuses.
        # Run with a stable seed so reseeding is reproducible.
        rng = random.Random(f'lume-demo-{slug}')
        services = list(Service.objects.filter(tenant=tenant, is_active=True))

        if not provider_users:
            self.stdout.write(self.style.WARNING(
                'No provider memberships found; skipping appointment seeding.'
            ))
        else:
            # Build the list of provider memberships (Appointment.provider FK
            # points at TenantMembership, not User).
            provider_memberships = list(
                TenantMembership.objects.filter(
                    tenant=tenant,
                    user__in=provider_users,
                    role=TenantMembership.Role.PROVIDER,
                )
            )

            # Wipe existing demo appointments before reseeding so
            # quantity stays bounded across multiple --reset-less runs.
            # Invoices have on_delete=PROTECT pointing at Appointment,
            # so we delete the invoices first (they're regenerated
            # downstream of appointment data anyway in a real flow).
            from apps.invoices.models import Invoice
            Invoice.objects.filter(tenant=tenant).delete()
            Appointment.objects.filter(tenant=tenant).delete()

            now = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
            for i in range(30):
                day_offset = rng.randint(-14, 14)
                hour = rng.randint(9, 17)
                start = now + timedelta(days=day_offset, hours=(hour - now.hour))

                customer = rng.choice(customer_objs)
                provider = rng.choice(provider_memberships)
                service = rng.choice(services)
                end = start + timedelta(minutes=service.duration_minutes)

                # Decide status by recency: past = mostly completed,
                # future = mostly booked. A small fraction of past
                # appointments are no-shows / cancellations, mirroring
                # real-world rates.
                if day_offset < 0:
                    status = rng.choices(
                        [
                            Appointment.Status.COMPLETED,
                            Appointment.Status.NO_SHOW,
                            Appointment.Status.CANCELLED,
                        ],
                        weights=[85, 10, 5],
                    )[0]
                else:
                    status = rng.choices(
                        [
                            Appointment.Status.CONFIRMED,
                            Appointment.Status.BOOKED,
                        ],
                        weights=[60, 40],
                    )[0]

                Appointment.objects.create(
                    tenant=tenant,
                    customer=customer,
                    provider=provider,
                    service=service,
                    location=location,
                    start_time=start,
                    end_time=end,
                    status=status,
                    quoted_price_cents=service.price_cents,
                    notes='',
                )

        # ── Done ──────────────────────────────────────────────────
        n_customers = Customer.objects.filter(tenant=tenant).count()
        n_appts = Appointment.objects.filter(tenant=tenant).count()
        n_services = Service.objects.filter(tenant=tenant).count()
        n_staff = TenantMembership.objects.filter(tenant=tenant).count()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Demo tenant "{slug}" ready: {n_staff} staff, {n_customers} customers, '
            f'{n_services} services, {n_appts} appointments.'
        ))
        self.stdout.write('')
        self.stdout.write(f'Sign in at: https://{slug}.<your-domain>/login')
        self.stdout.write(f'  Email:    {owner_email}')
        self.stdout.write('  Password: (the one you passed via --owner-password)')
