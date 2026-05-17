"""Tests for the Zenoti services-with-prices importer.

Shape matches `tests.py` (customer importer): pure mappers tested
directly, end-to-end orchestrator covered for header validation,
idempotent upsert, category find-or-create, Nails-filter, blank-
name rejection, and in-export duplicate handling.
"""

from __future__ import annotations

import io
from decimal import Decimal
from textwrap import dedent

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.imports.zenoti.services_importer import import_zenoti_services
from apps.imports.zenoti.services_mapper import (
    EXPECTED_HEADER,
    _parse_price_to_cents,
    _parse_tax_percent,
    detect_duplicate_external_ids,
    is_skipped_category,
    map_row,
    validate_header,
)
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant_with_defaults


User = get_user_model()


# ── Cleaner tests ──────────────────────────────────────────────────


class ServiceCleanerTests(TestCase):
    def test_price_parser(self):
        self.assertEqual(_parse_price_to_cents('479.00'), 47900)
        self.assertEqual(_parse_price_to_cents('$1,299.50'), 129950)
        self.assertEqual(_parse_price_to_cents(''), 0)
        self.assertEqual(_parse_price_to_cents(None), 0)
        self.assertEqual(_parse_price_to_cents('not a number'), 0)
        self.assertEqual(_parse_price_to_cents('-50'), 0)  # negatives rejected

    def test_tax_parser(self):
        self.assertEqual(_parse_tax_percent('8.88%(Tax Excluded)'), Decimal('8.880'))
        self.assertEqual(_parse_tax_percent('0%'), Decimal('0'))
        self.assertEqual(_parse_tax_percent(''), Decimal('0'))
        self.assertEqual(_parse_tax_percent(None), Decimal('0'))
        # Caps to the model's max (99.999).
        self.assertEqual(_parse_tax_percent('500%'), Decimal('99.999'))

    def test_skip_category(self):
        self.assertTrue(is_skipped_category('Nails'))
        self.assertTrue(is_skipped_category('nails'))
        self.assertTrue(is_skipped_category('category'))  # junk placeholder
        self.assertFalse(is_skipped_category('Injectables'))
        self.assertFalse(is_skipped_category(''))


# ── Header validation ──────────────────────────────────────────────


class ServiceHeaderTests(TestCase):
    def test_exact_match(self):
        self.assertEqual(validate_header(EXPECTED_HEADER), [])

    def test_trailing_blank_tolerated(self):
        padded = EXPECTED_HEADER + ['', '']
        self.assertEqual(validate_header(padded), [])

    def test_rename_fires(self):
        bad = list(EXPECTED_HEADER)
        bad[10] = 'Price'  # renamed FloridaPricePrice
        errs = validate_header(bad)
        self.assertEqual(len(errs), 1)
        self.assertIn('FloridaPricePrice', errs[0])


# ── Row mapper ─────────────────────────────────────────────────────


class ServiceMapRowTests(TestCase):
    def _row(self, **overrides) -> dict:
        base = {col: '' for col in EXPECTED_HEADER}
        base.update(overrides)
        return base

    def test_maps_typical_injectable(self):
        row = self._row(
            ServiceName='0.55cc Juvederm Ultra',
            Category='Injectables',
            SubCategory='Juvederm Product',
            Duration='0',
            CommissionEligible='Yes',
            ServiceDescription='0.55cc Juvederm Ultra',
            Code='INJADDON1',
            FloridaPricePrice='479.00',
            FloridaPriceTax='8.88%(Tax Excluded)',
            MidtownPricePrice='479.00',
            MidtownPriceTax='8.88%(Tax Excluded)',
        )
        m, err = map_row(row, line_number=6)
        self.assertIsNone(err)
        self.assertEqual(m.name, '0.55cc Juvederm Ultra')
        self.assertEqual(m.external_id, 'zenoti-service:INJADDON1')
        self.assertEqual(m.code, 'INJADDON1')
        self.assertEqual(m.category_name, 'Injectables')
        self.assertEqual(m.price_cents, 47900)
        self.assertEqual(m.tax_rate_percent, Decimal('8.880'))
        self.assertEqual(m.duration_minutes, 60)  # 0 → 60 default
        self.assertIn('Subcategory: Juvederm Product', m.description)

    def test_florida_only_no_midtown_fallback(self):
        """Florida price is the SOLE source. Even when Midtown has a
        value, blank Florida → $0 (operator fills later)."""
        row = self._row(
            ServiceName='Advanced Fractional Laser',
            Category='Facials',
            Code='AFLRT',
            FloridaPricePrice='',          # blank Florida
            MidtownPricePrice='899.00',    # Midtown has a value
        )
        m, err = map_row(row, line_number=6)
        self.assertIsNone(err)
        self.assertEqual(m.price_cents, 0)

    def test_nails_category_skipped(self):
        row = self._row(
            ServiceName='Gel Manicure',
            Category='Nails',
            Code='GELMANI',
            FloridaPricePrice='45.00',
        )
        m, err = map_row(row, line_number=6)
        self.assertIsNone(m)
        self.assertIsNotNone(err)
        self.assertIn('Skipped', err.reason)

    def test_blank_name_is_error(self):
        row = self._row(ServiceName='', Code='X')
        m, err = map_row(row, line_number=99)
        self.assertIsNone(m)
        self.assertEqual(err.line_number, 99)
        self.assertIn('blank', err.reason)

    def test_duration_preserved_when_set(self):
        row = self._row(
            ServiceName='Consultation', Category='Consultations',
            Code='C1', Duration='30', FloridaPricePrice='0.00',
        )
        m, _ = map_row(row, line_number=6)
        self.assertEqual(m.duration_minutes, 30)

    def test_synthetic_id_for_blank_code(self):
        row = self._row(
            ServiceName='Unique Service',
            Category='Body Treatments',
            Code='',
            FloridaPricePrice='100.00',
        )
        m, err = map_row(row, line_number=6)
        self.assertIsNone(err)
        self.assertTrue(m.external_id.startswith('zenoti-service:syn-'))


# ── Duplicate detection ────────────────────────────────────────────


class ServiceDuplicateTests(TestCase):
    def _mapped(self, eid: str):
        from apps.imports.zenoti.services_mapper import MappedService
        return MappedService(external_id=eid, name='X')

    def test_no_dupes(self):
        self.assertEqual(
            detect_duplicate_external_ids([self._mapped('a'), self._mapped('b')]),
            {},
        )

    def test_groups_dupes(self):
        rows = [self._mapped('a'), self._mapped('a'), self._mapped('b')]
        groups = detect_duplicate_external_ids(rows)
        self.assertIn('a', groups)
        self.assertEqual(len(groups['a']), 2)


# ── End-to-end orchestrator ────────────────────────────────────────


_PREAMBLE = dedent('''\
    Notification,,,,,,,,,,,,,,
    Center : Florida,,,,,,,,,,,,,,
    Service Centers,,,,,,,,,,,,,,
    ,,,,,,,,,,,,,,
''')

_HEADER_LINE = ','.join(EXPECTED_HEADER) + ',\n'


def _csv(rows: list[str]) -> io.StringIO:
    return io.StringIO(_PREAMBLE + _HEADER_LINE + '\n'.join(rows) + '\n')


class ServicesImporterEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user(email='svc-owner@test.local', password='x')
        cls.tenant = create_tenant_with_defaults(
            name='Test Spa', slug='svc-test', owner_user=owner,
            status=Tenant.Status.ACTIVE,
        )

    def test_dry_run_writes_nothing(self):
        csv_obj = _csv([
            '0.55cc Juvederm Ultra,Injectables,Juvederm Product,0,0,Yes,desc,100,0,INJADDON1,479.00,8.88%(Tax Excluded),479.00,8.88%(Tax Excluded),',
        ])
        report = import_zenoti_services(tenant=self.tenant, file_obj=csv_obj, dry_run=True)
        self.assertEqual(report.rows_mapped, 1)
        self.assertEqual(report.rows_created, 0)
        self.assertEqual(
            Service.objects.filter(tenant=self.tenant, external_source='zenoti').count(),
            0,
        )

    def test_live_import_creates_service_and_category(self):
        csv_obj = _csv([
            '0.55cc Juvederm Ultra,Injectables,Juvederm Product,0,0,Yes,desc,100,0,INJADDON1,479.00,8.88%(Tax Excluded),479.00,8.88%(Tax Excluded),',
        ])
        report = import_zenoti_services(tenant=self.tenant, file_obj=csv_obj, dry_run=False)
        self.assertEqual(report.rows_created, 1)
        self.assertEqual(report.categories_created, 1)
        s = Service.objects.get(tenant=self.tenant, external_id='zenoti-service:INJADDON1')
        self.assertEqual(s.name, '0.55cc Juvederm Ultra')
        self.assertEqual(s.price_cents, 47900)
        self.assertEqual(s.tax_rate_percent, Decimal('8.880'))
        self.assertEqual(s.category.name, 'Injectables')

    def test_idempotent_rerun(self):
        row = '0.55cc Juvederm Ultra,Injectables,Juvederm Product,0,0,Yes,desc,100,0,INJADDON1,479.00,,479.00,,'
        import_zenoti_services(tenant=self.tenant, file_obj=_csv([row]), dry_run=False)
        report2 = import_zenoti_services(tenant=self.tenant, file_obj=_csv([row]), dry_run=False)
        self.assertEqual(report2.rows_created, 0)
        self.assertEqual(report2.rows_updated, 1)
        self.assertEqual(report2.categories_created, 0)
        self.assertEqual(
            Service.objects.filter(tenant=self.tenant, external_source='zenoti').count(),
            1,
        )

    def test_service_type_immutable_post_create(self):
        """Operator's later 'this is actually an add-on' classification
        must survive a re-import."""
        row = '0.55cc Juvederm Ultra,Injectables,Juvederm Product,0,0,Yes,desc,100,0,INJADDON1,479.00,,479.00,,'
        import_zenoti_services(tenant=self.tenant, file_obj=_csv([row]), dry_run=False)
        s = Service.objects.get(tenant=self.tenant, external_id='zenoti-service:INJADDON1')
        s.service_type = Service.ServiceType.ADDON
        s.is_bookable_online = False
        s.save(update_fields=['service_type', 'is_bookable_online'])
        import_zenoti_services(tenant=self.tenant, file_obj=_csv([row]), dry_run=False)
        s.refresh_from_db()
        self.assertEqual(s.service_type, Service.ServiceType.ADDON)
        self.assertFalse(s.is_bookable_online)

    def test_nails_filter_counted_separately(self):
        csv_obj = _csv([
            '0.55cc Juvederm Ultra,Injectables,Juvederm Product,0,0,Yes,,100,0,INJADDON1,479.00,,479.00,,',
            'Gel Manicure,Nails,MANICURE,0,0,Yes,,100,0,GELMANI,45.00,,45.00,,',
        ])
        report = import_zenoti_services(tenant=self.tenant, file_obj=csv_obj, dry_run=False)
        self.assertEqual(report.rows_created, 1)
        self.assertEqual(report.rows_skipped_filtered, 1)
        self.assertEqual(report.rows_failed_mapping, 0)
        # Only the Injectable landed.
        self.assertFalse(
            Service.objects.filter(tenant=self.tenant, name='Gel Manicure').exists(),
        )

    def test_aggregate_audit_entry_created(self):
        csv_obj = _csv([
            '0.55cc Juvederm Ultra,Injectables,Juvederm Product,0,0,Yes,,100,0,INJADDON1,479.00,,479.00,,',
        ])
        import_zenoti_services(tenant=self.tenant, file_obj=csv_obj, dry_run=False)
        self.assertEqual(
            AuditLog.objects.filter(
                tenant=self.tenant, resource_type='zenoti_services_import_run',
            ).count(),
            1,
        )
