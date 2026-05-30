"""Inspect data volume per tenant — read-only.

Used as the safety pre-check before any destructive cross-tenant
operation (bulk customer deletion, test-tenant teardown, etc.).
Prints per-tenant counts of every PHI-bearing table so operators
can confirm exactly what they're about to touch BEFORE running a
delete command.

Output is intentionally tabular + human-readable; pipe through
``jq`` if you need machine-readable.

HIPAA: read-only counts of resource IDs. No PHI in the output —
just integers and tenant slugs. Safe to log + paste into Slack /
support tickets.

Usage:

    python manage.py inspect_tenant_data                  # all tenants
    python manage.py inspect_tenant_data --tenant <slug>  # one tenant
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Print per-tenant counts of customers + related PHI tables (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            help='Limit to one tenant slug. Without this, shows every tenant.',
        )

    def handle(self, *args, **options):
        single_slug = options.get('tenant')
        qs = Tenant.objects.all().order_by('slug')
        if single_slug:
            qs = qs.filter(slug=single_slug)
            if not qs.exists():
                raise CommandError(f'No tenant with slug={single_slug!r}.')

        for tenant in qs:
            self._print_tenant(tenant)

    def _print_tenant(self, tenant: Tenant) -> None:
        # Lazy-import every model so we don't pull in apps we don't
        # need just to count a few tables.
        from apps.appointments.models import Appointment
        from apps.charts.models import ChartNote
        from apps.customers.models import Customer
        from apps.forms.models import FormSubmission
        from apps.giftcards.models import GiftCard
        from apps.invoices.models import Invoice
        from apps.memberships.models import Subscription
        from apps.packages.models import PurchasedPackage
        from apps.payments.models import Charge, Refund

        counts = {
            'customers': Customer.objects.filter(tenant=tenant).count(),
            'appointments': Appointment.objects.filter(tenant=tenant).count(),
            'invoices': Invoice.objects.filter(tenant=tenant).count(),
            'charges': Charge.objects.filter(tenant=tenant).count(),
            'refunds': Refund.objects.filter(tenant=tenant).count(),
            'chart_notes': ChartNote.objects.filter(tenant=tenant).count(),
            'form_submissions': FormSubmission.objects.filter(tenant=tenant).count(),
            'gift_cards': GiftCard.objects.filter(tenant=tenant).count(),
            'purchased_packages': PurchasedPackage.objects.filter(tenant=tenant).count(),
            'subscriptions': Subscription.objects.filter(tenant=tenant).count(),
        }

        # Header with the most-useful identifying info.
        legacy = ' [LEGACY/GRANDFATHERED]' if tenant.grandfathered else ''
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'═══ {tenant.slug} ({tenant.name}){legacy} ═══'
        ))
        self.stdout.write(
            f'  plan={tenant.plan}  status={tenant.status}  id={tenant.id}'
        )
        for resource, n in counts.items():
            marker = '  ' if n == 0 else '⚠ '
            self.stdout.write(f'    {marker}{resource:20s} {n:>8d}')
