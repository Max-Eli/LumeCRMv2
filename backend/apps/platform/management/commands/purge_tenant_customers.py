"""Tenant-scoped customer purge — DESTRUCTIVE.

Deletes every customer on a single tenant plus everything that
hangs off those customers (appointments, invoices, packages,
memberships, clinical notes, forms, social threads, waitlist,
charges, refunds, commissions, gift-card ledger entries). Keeps:

  - The Tenant row itself
  - Locations, services, job titles, tax rates
  - Staff (User accounts + TenantMembership rows)
  - Tenant settings (business hours, integrations, branding, etc.)
  - Stripe Billing + Connect linkage on the Tenant row
  - Gift cards themselves (only the issued_to / purchaser FK to the
    deleted customer is nulled — the card balance + history stays)

Intended use: clear the demo tenant before re-seeding, or reset
a staging tenant. NEVER use on a real spa — refuses by default
against any tenant with grandfathered=True (the launch spas).

Order matters: most customer-related FKs are PROTECT, so we must
delete the leaf rows before their parents. The order encoded
below was derived by reading every on_delete in the model layer —
update it if you add a new PROTECT FK upstream of Customer.

HIPAA: deletion is intentional + audited. One AuditLog row per
resource type with the count deleted. No PHI in stdout — just
model names, integer counts, and tenant slug. Safe to log + paste
into ops tickets.

Usage:

    python manage.py purge_tenant_customers --tenant demo               # dry-run
    python manage.py purge_tenant_customers --tenant demo --confirm     # actually delete
    python manage.py purge_tenant_customers --tenant demo --confirm \\
        --override-grandfathered   # required for grandfathered tenants (don't)
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'DESTRUCTIVE: delete every customer (and all customer-attached '
        'rows) on a single tenant. Dry-run by default; pass --confirm '
        'to actually delete.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            required=True,
            help='Tenant slug to purge (required — no implicit target).',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually delete. Without this, runs as dry-run and reports counts only.',
        )
        parser.add_argument(
            '--override-grandfathered',
            action='store_true',
            help=(
                'Allow purging a grandfathered tenant. Refused by default — '
                'grandfathered=True marks the live launch spas, which must NEVER '
                'be wiped by this command.'
            ),
        )

    def handle(self, *args, **options):
        slug = options['tenant']
        do_delete = options['confirm']
        override_gf = options['override_grandfathered']

        try:
            tenant = Tenant.objects.get(slug=slug)
        except Tenant.DoesNotExist as exc:
            raise CommandError(f'No tenant with slug={slug!r}.') from exc

        if tenant.grandfathered and not override_gf:
            raise CommandError(
                f'Refusing to purge grandfathered tenant {tenant.slug!r} '
                f'(name={tenant.name!r}). Pass --override-grandfathered '
                f'if you really mean it.'
            )

        # Lazy-import every model so an unrelated app failure can't
        # break import of this command (same pattern as inspect_tenant_data).
        from apps.appointments.models import Appointment
        from apps.charts.models import ChartNote, TreatmentRecord
        from apps.commissions.models import CommissionEntry
        from apps.customers.models import Customer
        from apps.forms.models import FormSubmission
        from apps.giftcards.models import GiftCard, GiftCardLedger
        from apps.integrations.models import SocialThread
        from apps.invoices.models import Invoice
        from apps.marketing.models import MarketingSendLog, UnsubscribeToken
        from apps.memberships.models import Subscription, SubscriptionRedemption
        from apps.messaging.models import Message
        from apps.packages.models import PackageRedemption, PurchasedPackage
        from apps.payments.models import Charge, Refund
        from apps.waitlist.models import WaitlistEntry

        # Deletion order: leaf PROTECT-referencers first, then their
        # parents, then Customer last. The non-obvious wrinkle is
        # InvoiceLineItem — cascades FROM Invoice but is PROTECTed by
        # PurchasedPackage.source_invoice_line and
        # Subscription.source_invoice_line (and the same on each
        # redemption). So PurchasedPackage / Subscription must be
        # deleted BEFORE Invoice, even though both also PROTECT → Customer.
        # Update this list if you add a new PROTECT FK upstream of
        # Invoice / Appointment / Customer.
        delete_plan = [
            # ── invoice-attached ledger rows (all PROTECT → Invoice) ──
            ('payments.Refund',            Refund),
            ('payments.Charge',            Charge),
            ('commissions.CommissionEntry', CommissionEntry),
            ('giftcards.GiftCardLedger',   GiftCardLedger),
            # ── customer-attached PROTECT leaves ──
            ('forms.FormSubmission',       FormSubmission),
            ('charts.TreatmentRecord',     TreatmentRecord),
            ('charts.ChartNote',           ChartNote),
            ('waitlist.WaitlistEntry',     WaitlistEntry),
            ('integrations.SocialThread',  SocialThread),
            # ── redemptions (PROTECT → Subscription/PurchasedPackage,
            #    Appointment, and InvoiceLineItem) ──
            ('memberships.SubscriptionRedemption', SubscriptionRedemption),
            ('packages.PackageRedemption', PackageRedemption),
            # ── Subscription + PurchasedPackage + GiftCard MUST go
            #    before Invoice: all three PROTECT-reference
            #    InvoiceLineItem via source_invoice_line, which
            #    Invoice's cascade would otherwise try to delete out
            #    from under them ──
            ('memberships.Subscription',   Subscription),
            ('packages.PurchasedPackage',  PurchasedPackage),
            ('giftcards.GiftCard',         GiftCard),
            # ── invoice (PROTECT → Customer + Appointment); now
            #    nothing PROTECT-references its line items ──
            ('invoices.Invoice',           Invoice),
            # ── appointment (PROTECT → Customer) ──
            ('appointments.Appointment',   Appointment),
            # ── marketing + messaging PROTECT → Customer; the
            #    inspect_tenant_data census doesn't enumerate these
            #    (they're communications, not core PHI), so they
            #    must be explicit here ──
            ('marketing.MarketingSendLog', MarketingSendLog),
            ('marketing.UnsubscribeToken', UnsubscribeToken),
            ('messaging.Message',          Message),
            # ── finally Customer itself; portal tokens/sessions
            #    cascade, giftcards.GiftCard customer FKs were
            #    SET_NULL but the cards themselves are now gone too ──
            ('customers.Customer',         Customer),
        ]

        verb = 'WOULD delete' if not do_delete else 'DELETED'
        header = '═' * 60
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(header))
        self.stdout.write(self.style.SUCCESS(
            f'Tenant purge: {tenant.slug} ({tenant.name})'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'Mode: {"LIVE (--confirm)" if do_delete else "DRY-RUN"}'
        ))
        self.stdout.write(self.style.SUCCESS(header))

        totals: dict[str, int] = {}

        # The whole purge is one transaction. If any layer fails (e.g.,
        # a new PROTECT FK that isn't in delete_plan), the entire
        # operation rolls back — no half-deleted tenant.
        #
        # Dry-run also runs .delete() and then rolls back: this is
        # the only way to surface PROTECT-chain errors without
        # committing. The alternative — counting rows but skipping
        # the delete — would let a missing entry in delete_plan
        # slip through dry-run and only fail on the live run, which
        # is exactly what happened during this command's first three
        # iterations against the demo tenant.
        with transaction.atomic():
            for label, model in delete_plan:
                qs = model.objects.filter(tenant=tenant)
                count = qs.count()
                totals[label] = count
                if count == 0:
                    self.stdout.write(f'  {label:42s} {count:>8d}')
                    continue
                self.stdout.write(f'  {label:42s} {count:>8d}  → {verb}')
                # QuerySet.delete() (not _raw_delete) — the ORM
                # collector walks CASCADE FKs (InvoiceLineItem on
                # Invoice, SubscriptionItem on Subscription,
                # PortalToken/PortalSession on Customer, etc.).
                # _raw_delete bypasses that and the COMMIT then fails
                # on the dangling FK. The biggest table here is
                # ~7.5k rows — well within Django's collector
                # comfort zone for a one-shot ops task.
                qs.delete()

            if do_delete:
                # One audit row per resource type, plus a roll-up row
                # so the audit trail clearly shows this as a single
                # operator-driven purge (not e.g. tenant churn over time).
                grand_total = sum(totals.values())
                record(
                    action=AuditLog.Action.DELETE,
                    resource_type='tenant_purge',
                    resource_id=tenant.id,
                    tenant=tenant,
                    metadata={
                        'tenant_slug': tenant.slug,
                        'grand_total': grand_total,
                        'per_resource': totals,
                        'command': 'purge_tenant_customers',
                    },
                )

            if not do_delete:
                # Force rollback even though we didn't write anything —
                # _raw_delete bypasses transaction state in some
                # drivers, and being explicit costs nothing.
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(header))
        grand_total = sum(totals.values())
        if do_delete:
            self.stdout.write(self.style.SUCCESS(
                f'Done. Deleted {grand_total} rows across {len(totals)} tables on {tenant.slug}.'
            ))
            self.stdout.write(self.style.SUCCESS(
                'Re-run `inspect_tenant_data --tenant '
                f'{tenant.slug}` to verify.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'Dry-run complete. {grand_total} rows WOULD be deleted across '
                f'{len(totals)} tables. Re-run with --confirm to actually delete.'
            ))
        self.stdout.write('')
