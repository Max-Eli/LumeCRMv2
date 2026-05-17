"""Tests for the Zenoti packages importer.

Coverage:

  - Pure parser: Benefit Name parsing (single + multi-service +
    edge cases like commas in names), date parsing, amount
    parsing, guest-name splitting.
  - Header validation (mismatched columns fail).
  - Idempotent multi-file merge (Invoice No dedup; later wins).
  - End-to-end: dry-run writes nothing, live creates
    PurchasedPackage + items, customer matching, service matching
    by name, unmatched-service falls back to text snapshot,
    Expired/Closed → quantity_remaining=0, idempotent re-run
    refreshes balance.
"""

from __future__ import annotations

import io
from decimal import Decimal
from textwrap import dedent

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.imports.zenoti.packages_importer import import_zenoti_packages
from apps.imports.zenoti.packages_mapper import (
    EXPECTED_HEADER,
    _parse_amount,
    _parse_benefit_name,
    _parse_date,
    _split_guest_name,
    map_row,
    merge_files,
    validate_header,
)
from apps.packages.models import PurchasedPackage, PurchasedPackageItem
from apps.services.models import Service
from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant_with_defaults


User = get_user_model()


# ── Pure parser tests ──────────────────────────────────────────────


class BenefitNameParserTests(TestCase):
    def test_single_service(self):
        items = _parse_benefit_name('Brazilian Bikini(Service - 6)')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].service_name, 'Brazilian Bikini')
        self.assertEqual(items[0].qty_purchased, 6)

    def test_multi_service(self):
        items = _parse_benefit_name(
            'Brazilian Bikini(Service - 6),Full Arms(Service - 6),Underarm(Service - 6)'
        )
        self.assertEqual(len(items), 3)
        self.assertEqual([i.service_name for i in items], ['Brazilian Bikini', 'Full Arms', 'Underarm'])
        self.assertEqual([i.qty_purchased for i in items], [6, 6, 6])

    def test_different_quantities(self):
        items = _parse_benefit_name(
            'Lip Flip(Service - 2),Toxin Unit(s)(Service - 60)'
        )
        self.assertEqual(items[0].qty_purchased, 2)
        self.assertEqual(items[1].qty_purchased, 60)

    def test_empty_input(self):
        self.assertEqual(_parse_benefit_name(''), [])
        self.assertEqual(_parse_benefit_name(None), [])

    def test_skips_items_without_service_suffix(self):
        # Product names without (Service - N) get skipped silently.
        items = _parse_benefit_name('Brazilian Bikini(Service - 6),Random Product')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].service_name, 'Brazilian Bikini')


class GuestNameSplitTests(TestCase):
    def test_two_parts(self):
        self.assertEqual(_split_guest_name('Wendy Penn'), ('Wendy', 'Penn'))

    def test_one_part(self):
        self.assertEqual(_split_guest_name('Cher'), ('Cher', ''))

    def test_three_parts_collapses_last(self):
        self.assertEqual(_split_guest_name('Mary Jane Watson'), ('Mary', 'Jane Watson'))

    def test_extra_whitespace(self):
        self.assertEqual(_split_guest_name('  Wendy   Penn  '), ('Wendy', 'Penn'))


class AmountParserTests(TestCase):
    def test_parses_simple(self):
        self.assertEqual(_parse_amount('479.00'), Decimal('479.00'))

    def test_strips_currency_and_commas(self):
        self.assertEqual(_parse_amount('$1,749.30'), Decimal('1749.30'))

    def test_blank_returns_zero(self):
        self.assertEqual(_parse_amount(''), Decimal('0'))
        self.assertEqual(_parse_amount(None), Decimal('0'))


# ── Header validation ──────────────────────────────────────────────


class PackagesHeaderTests(TestCase):
    def test_exact_match(self):
        self.assertEqual(validate_header(EXPECTED_HEADER), [])

    def test_rename_fires(self):
        bad = list(EXPECTED_HEADER)
        bad[1] = 'InvoiceNumber'  # camelCase instead of "Invoice No"
        errs = validate_header(bad)
        self.assertEqual(len(errs), 1)
        self.assertIn('Invoice No', errs[0])


# ── Row mapper ─────────────────────────────────────────────────────


class PackagesMapRowTests(TestCase):
    def _row(self, **overrides) -> dict:
        base = {c: '' for c in EXPECTED_HEADER}
        base.update(overrides)
        return base

    def test_maps_active_single_service(self):
        row = self._row(
            **{
                'Sale Center': 'Florida',
                'Invoice No': '22571',
                'Package Name': '6 large',
                'Guest Name': 'Angela Romersi',
                'Sale Date': '5/13/2026',
                'Expiry Date': '5/13/2027',
                'Sales': '599',
                'Sales(Inc. Tax)': '599',
                'Benefit Name': 'Laser Hair Removal - Large Area(Service - 6)',
                'Value': '599',
                'Balance Value': '399.33',  # ~66% remaining → 4 of 6
                'Package Status': 'Active',
            }
        )
        m, err = map_row(row, line_number=2)
        self.assertIsNone(err)
        self.assertEqual(m.external_id, 'zenoti-package:22571')
        self.assertEqual(m.customer_first, 'Angela')
        self.assertEqual(m.customer_last, 'Romersi')
        self.assertEqual(len(m.items), 1)
        self.assertEqual(m.items[0].service_name, 'Laser Hair Removal - Large Area')
        self.assertEqual(m.items[0].qty_purchased, 6)
        self.assertEqual(m.items[0].qty_remaining, 3)  # floor(6 * 0.66) = 3

    def test_expired_package_has_zero_remaining(self):
        row = self._row(
            **{
                'Sale Center': 'Midtown', 'Invoice No': 'M-MT-19488',
                'Package Name': 'Custom Black Friday',
                'Guest Name': 'Valerie Coleman',
                'Sale Date': '11/30/2024', 'Expiry Date': '11/30/2025',
                'Benefit Name': 'GP VI Peel Original Treatment(Service - 2)',
                'Value': '375', 'Balance Value': '187.5',
                'Package Status': 'Expired',
            }
        )
        m, _ = map_row(row, line_number=2)
        self.assertEqual(m.items[0].qty_remaining, 0)
        self.assertEqual(m.items[0].qty_purchased, 2)

    def test_multi_service_proportional_remaining(self):
        # 5 services × 6 sessions = 30 sessions, $1749.30 sold,
        # $1488.62 remaining (~85%). Each item → 5 of 6 remaining.
        row = self._row(
            **{
                'Sale Center': 'Midtown', 'Invoice No': 'M-MT-19461',
                'Guest Name': 'Reema Iqbal',
                'Benefit Name': (
                    'Brazilian Bikini(Service - 6),Full Arms(Service - 6),'
                    'Full Face(Service - 6),Full Leg(Service - 6),'
                    'Underarm(Service - 6)'
                ),
                'Value': '1749.30', 'Balance Value': '1488.62',
                'Package Status': 'Active',
            }
        )
        m, _ = map_row(row, line_number=2)
        self.assertEqual(len(m.items), 5)
        for item in m.items:
            self.assertEqual(item.qty_purchased, 6)
            self.assertEqual(item.qty_remaining, 5)  # floor(6 * 0.851) = 5

    def test_blank_invoice_no_is_error(self):
        row = self._row(**{
            'Invoice No': '', 'Guest Name': 'X Y',
            'Benefit Name': 'Anything(Service - 1)',
        })
        m, err = map_row(row, line_number=2)
        self.assertIsNone(m)
        self.assertIn('Invoice No', err.reason)

    def test_blank_guest_name_is_error(self):
        row = self._row(**{
            'Invoice No': 'X1', 'Guest Name': '',
            'Benefit Name': 'Anything(Service - 1)',
        })
        m, err = map_row(row, line_number=2)
        self.assertIsNone(m)
        self.assertIn('Guest Name', err.reason)

    def test_unparseable_benefit_is_error(self):
        row = self._row(**{
            'Invoice No': 'X1', 'Guest Name': 'X Y',
            'Benefit Name': 'no recognizable format',
        })
        m, err = map_row(row, line_number=2)
        self.assertIsNone(m)
        self.assertIn('parse', err.reason)


# ── Multi-file merge ───────────────────────────────────────────────


class MergeFilesTests(TestCase):
    def _pkg(self, eid, balance_ratio):
        from apps.imports.zenoti.packages_mapper import MappedPackage
        return MappedPackage(external_id=eid, balance_ratio=balance_ratio)

    def test_no_overlap(self):
        merged, dupes = merge_files([
            [self._pkg('a', 1.0)], [self._pkg('b', 0.5)],
        ])
        self.assertEqual(len(merged), 2)
        self.assertEqual(dupes, [])

    def test_overlap_later_wins(self):
        merged, dupes = merge_files([
            [self._pkg('a', 1.0)],
            [self._pkg('a', 0.3)],  # later balance is authoritative
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(dupes, ['a'])
        self.assertEqual(merged[0].balance_ratio, 0.3)


# ── End-to-end ─────────────────────────────────────────────────────


def _csv(rows: list[str]) -> io.StringIO:
    header = ','.join(EXPECTED_HEADER) + '\n'
    return io.StringIO(header + '\n'.join(rows) + '\n')


class PackagesImporterEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user(email='pkg-owner@test.local', password='x')
        cls.tenant = create_tenant_with_defaults(
            name='Test Spa', slug='pkg-test', owner_user=owner,
            status=Tenant.Status.ACTIVE,
        )
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Angela', last_name='Romersi',
            email='angela@test.local',
        )
        cls.service = Service.objects.create(
            tenant=cls.tenant,
            name='Laser Hair Removal - Large Area',
            price_cents=59900,
        )

    def _row(self, **overrides):
        # Build a single CSV row string from the header + overrides.
        from apps.imports.zenoti.packages_mapper import EXPECTED_HEADER as H
        base = {c: '' for c in H}
        base.update(overrides)
        return ','.join('"' + str(base[c]).replace('"', '""') + '"' for c in H)

    def test_dry_run_writes_nothing(self):
        row = self._row(**{
            'Sale Center': 'Florida', 'Invoice No': '22571',
            'Package Name': '6 large', 'Guest Name': 'Angela Romersi',
            'Sale Date': '5/13/2026',
            'Benefit Name': 'Laser Hair Removal - Large Area(Service - 6)',
            'Value': '599', 'Balance Value': '599',
            'Package Status': 'Active',
        })
        report = import_zenoti_packages(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=True,
        )
        self.assertEqual(report.rows_mapped, 1)
        self.assertEqual(report.rows_created, 0)
        self.assertEqual(
            PurchasedPackage.objects.filter(tenant=self.tenant).count(), 0,
        )

    def test_live_import_creates_package_with_matched_service(self):
        row = self._row(**{
            'Sale Center': 'Florida', 'Invoice No': '22571',
            'Package Name': '6 large', 'Guest Name': 'Angela Romersi',
            'Sale Date': '5/13/2026', 'Sales(Inc. Tax)': '599',
            'Benefit Name': 'Laser Hair Removal - Large Area(Service - 6)',
            'Value': '599', 'Balance Value': '599',
            'Package Status': 'Active',
        })
        report = import_zenoti_packages(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        self.assertEqual(report.rows_created, 1)
        self.assertEqual(report.items_matched_service, 1)
        self.assertEqual(report.items_unmatched_service, 0)
        pkg = PurchasedPackage.objects.get(
            tenant=self.tenant, external_id='zenoti-package:22571',
        )
        self.assertEqual(pkg.customer, self.customer)
        self.assertEqual(pkg.external_invoice_no, '22571')
        self.assertEqual(pkg.price_cents, 59900)
        item = pkg.items.get()
        self.assertEqual(item.service, self.service)
        self.assertEqual(item.service_name, 'Laser Hair Removal - Large Area')
        self.assertEqual(item.quantity_purchased, 6)
        self.assertEqual(item.quantity_remaining, 6)
        self.assertEqual(item.unit_value_cents, 59900)

    def test_unmatched_service_preserves_snapshot(self):
        row = self._row(**{
            'Sale Center': 'Florida', 'Invoice No': 'X1',
            'Guest Name': 'Angela Romersi',
            'Sale Date': '5/13/2026',
            'Benefit Name': 'Unknown Mystery Service(Service - 3)',
            'Value': '300', 'Balance Value': '300',
            'Package Status': 'Active',
        })
        report = import_zenoti_packages(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        self.assertEqual(report.rows_created, 1)
        self.assertEqual(report.items_unmatched_service, 1)
        self.assertIn('Unknown Mystery Service', report.unmatched_service_names)
        item = PurchasedPackageItem.objects.get(
            purchased_package__external_id='zenoti-package:X1',
        )
        self.assertIsNone(item.service)
        self.assertEqual(item.service_name, 'Unknown Mystery Service')
        self.assertEqual(item.quantity_purchased, 3)

    def test_customer_not_found_skipped_and_logged(self):
        row = self._row(**{
            'Sale Center': 'Florida', 'Invoice No': 'X2',
            'Guest Name': 'Nobody Atall',
            'Sale Date': '5/13/2026',
            'Benefit Name': 'Laser Hair Removal - Large Area(Service - 6)',
            'Value': '599', 'Balance Value': '599',
            'Package Status': 'Active',
        })
        report = import_zenoti_packages(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        self.assertEqual(report.rows_created, 0)
        self.assertEqual(report.rows_skipped_no_customer, 1)
        self.assertEqual(len(report.customer_misses), 1)
        self.assertIn('Nobody Atall', report.customer_misses[0])

    def test_idempotent_rerun_refreshes_balance(self):
        # First import: full balance.
        first_row = self._row(**{
            'Sale Center': 'Florida', 'Invoice No': '22571',
            'Guest Name': 'Angela Romersi',
            'Sale Date': '5/13/2026',
            'Benefit Name': 'Laser Hair Removal - Large Area(Service - 6)',
            'Value': '599', 'Balance Value': '599',
            'Package Status': 'Active',
        })
        import_zenoti_packages(
            tenant=self.tenant, file_objs=[_csv([first_row])], dry_run=False,
        )
        # Re-import: balance has been drawn down (3 of 6 remaining).
        # 50% balance → floor(6 * 0.5) = 3 sessions remaining.
        second_row = self._row(**{
            'Sale Center': 'Florida', 'Invoice No': '22571',
            'Guest Name': 'Angela Romersi',
            'Sale Date': '5/13/2026',
            'Benefit Name': 'Laser Hair Removal - Large Area(Service - 6)',
            'Value': '599', 'Balance Value': '299.50',
            'Package Status': 'Active',
        })
        report2 = import_zenoti_packages(
            tenant=self.tenant, file_objs=[_csv([second_row])], dry_run=False,
        )
        self.assertEqual(report2.rows_created, 0)
        self.assertEqual(report2.rows_updated, 1)
        pkg = PurchasedPackage.objects.get(
            tenant=self.tenant, external_id='zenoti-package:22571',
        )
        # Items wiped + re-inserted (so balance refreshes).
        self.assertEqual(pkg.items.count(), 1)
        item = pkg.items.get()
        self.assertEqual(item.quantity_remaining, 3)
        # Still exactly one PurchasedPackage in the DB.
        self.assertEqual(
            PurchasedPackage.objects.filter(tenant=self.tenant).count(), 1,
        )

    def test_aggregate_audit_entry_created(self):
        row = self._row(**{
            'Sale Center': 'Florida', 'Invoice No': '22571',
            'Guest Name': 'Angela Romersi', 'Sale Date': '5/13/2026',
            'Benefit Name': 'Laser Hair Removal - Large Area(Service - 6)',
            'Value': '599', 'Balance Value': '599',
            'Package Status': 'Active',
        })
        import_zenoti_packages(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                tenant=self.tenant,
                resource_type='zenoti_packages_import_run',
            ).count(),
            1,
        )
