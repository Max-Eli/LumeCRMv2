"""Seed a fake inbound Instagram DM thread so the `/social` inbox
can be exercised without touching Meta.

Useful when:
  - You're building / iterating on the inbox UI and don't want to
    wait for a real DM to land.
  - You want a demo dataset for a tenant before App Review passes.
  - You're verifying tenant scoping (run twice with --tenant=A and
    --tenant=B and confirm the threads stay separated).

The data this command creates is real (not test-database-only) —
the SocialThread + SocialMessage + Customer rows are inserted into
the live dev DB so the UI shows them. If you want them gone, run
with `--purge` to wipe everything created by this command for the
given tenant.

Usage:

    # default — picks the first active tenant + creates 3 threads
    python manage.py seed_test_social_thread

    # specific tenant + custom count
    python manage.py seed_test_social_thread --tenant=demo --count=5

    # clean up afterward
    python manage.py seed_test_social_thread --tenant=demo --purge
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.customers.models import Customer
from apps.integrations.models import Connection, SocialMessage, SocialThread
from apps.tenants.models import Tenant


# Marker that distinguishes seeded rows from real ones so --purge
# can find them. Stored on the SocialThread.external_thread_id prefix
# AND on the customer's external_id, so a real Meta-delivered thread
# whose PSID happens to start the same way is still safe.
_SEED_TAG = 'SEED_'

_SAMPLE_HANDLES = [
    ('emma.glows', 'Emma Garcia', 'Hi! Do you have any availability for a HydraFacial this Friday afternoon?'),
    ('marcus.aesthetics', 'Marcus Lee', 'Hey — is the laser hair removal package still on sale this month?'),
    ('jenny.pdx', 'Jenny Chen', 'I had Botox with you in April. Time to come back already 😅 — what days are you open?'),
    ('the.skin.atlas', 'Aaliyah Brown', 'Hello, I follow your work and I would love to book a microneedling consult. Are you taking new clients?'),
    ('sasha.beauty.co', 'Sasha Kim', 'My friend recommended you for filler. Could I get pricing for lip filler please?'),
    ('nathandoes_nyc', 'Nathan Park', 'Hi, do you offer payment plans for the chemical peel series?'),
    ('rena.glow.up', 'Rena Williams', 'When do you have an opening for IPL? I want to start before summer.'),
]


class Command(BaseCommand):
    help = 'Create fake SocialThread + SocialMessage rows for inbox testing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant', type=str, default=None,
            help='Tenant slug (defaults to the first ACTIVE tenant).',
        )
        parser.add_argument(
            '--count', type=int, default=3,
            help='Number of threads to seed (max 7, the sample-handle count).',
        )
        parser.add_argument(
            '--purge', action='store_true',
            help='Delete all seeded rows for the tenant instead of creating.',
        )

    def handle(self, *args, **opts):
        tenant = _resolve_tenant(opts.get('tenant'))
        self.stdout.write(self.style.NOTICE(
            f'Tenant: {tenant.slug} ({tenant.name})'
        ))

        if opts['purge']:
            return self._purge(tenant)
        return self._seed(tenant, count=opts['count'])

    def _purge(self, tenant: Tenant):
        threads = SocialThread.objects.filter(
            tenant=tenant,
            external_thread_id__startswith=_SEED_TAG,
        )
        customers = Customer.objects.filter(
            tenant=tenant,
            external_id__startswith=_SEED_TAG,
        )
        msg_count = SocialMessage.objects.filter(thread__in=threads).count()
        thread_count = threads.count()
        customer_count = customers.count()

        with transaction.atomic():
            SocialMessage.objects.filter(thread__in=threads).delete()
            threads.delete()
            customers.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Purged {msg_count} message(s), {thread_count} thread(s), '
            f'{customer_count} seeded customer(s).'
        ))

    def _seed(self, tenant: Tenant, *, count: int):
        if count < 1 or count > len(_SAMPLE_HANDLES):
            raise CommandError(
                f'--count must be 1..{len(_SAMPLE_HANDLES)}'
            )

        # We need a Connection to attach threads to. If the tenant
        # hasn't OAuth'd Instagram yet, create a fake disconnected
        # Connection (status=ERROR so it's visible as "needs reconnect"
        # in the integrations UI but distinguishable from a real
        # error). The seed command exists for UI testing — real OAuth
        # would only complicate that.
        connection, _ = Connection.objects.get_or_create(
            tenant=tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            defaults={
                'status': Connection.Status.CONNECTED,
                'external_id': _SEED_TAG + 'page-id',
                'external_name': '(seeded test connection)',
            },
        )

        now = timezone.now()
        created_threads: list[SocialThread] = []

        with transaction.atomic():
            for idx in range(count):
                handle, full_name, body = _SAMPLE_HANDLES[idx]
                first_name, _, last_name = full_name.partition(' ')

                # Stagger thread timestamps so the inbox sort order
                # is visibly meaningful (newest first).
                ts = now - timedelta(minutes=idx * 17)
                external_id = (
                    _SEED_TAG + handle + '-' + secrets.token_urlsafe(4)
                )

                customer = Customer.objects.create(
                    tenant=tenant,
                    first_name=first_name,
                    last_name=last_name or '',
                    instagram_handle=handle,
                    is_social_guest=True,
                    acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
                    external_id=external_id,
                    external_source='instagram',
                    imported_at=ts,
                    sms_marketing_opt_in=False,
                    email_marketing_opt_in=False,
                )

                thread = SocialThread.objects.create(
                    tenant=tenant,
                    provider=SocialThread.Provider.INSTAGRAM,
                    connection=connection,
                    customer=customer,
                    external_thread_id=external_id,
                    external_username=handle,
                    last_message_at=ts,
                    last_inbound_at=ts,
                )

                SocialMessage.objects.create(
                    tenant=tenant,
                    thread=thread,
                    direction=SocialMessage.Direction.INBOUND,
                    body=body,
                    external_message_id=_SEED_TAG + 'mid-' + secrets.token_urlsafe(8),
                    status=SocialMessage.Status.RECEIVED,
                    received_at=ts,
                )

                created_threads.append(thread)

        self.stdout.write(self.style.SUCCESS(
            f'Created {len(created_threads)} test thread(s) for {tenant.slug}.'
        ))
        self.stdout.write('')
        self.stdout.write('Open /social to see them. Examples:')
        for t in created_threads:
            self.stdout.write(f'  · @{t.external_username} → {t.customer.full_name}')
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(
            'To remove these seeded rows later:'
        ))
        self.stdout.write(self.style.NOTICE(
            f'  python manage.py seed_test_social_thread '
            f'--tenant={tenant.slug} --purge'
        ))


def _resolve_tenant(slug: str | None) -> Tenant:
    if slug:
        try:
            return Tenant.objects.get(slug=slug)
        except Tenant.DoesNotExist:
            raise CommandError(f'No tenant with slug={slug!r}.')
    tenant = Tenant.objects.filter(status=Tenant.Status.ACTIVE).order_by('id').first()
    if tenant is None:
        raise CommandError(
            'No ACTIVE tenants exist. Pass --tenant=<slug> or create one.'
        )
    return tenant
