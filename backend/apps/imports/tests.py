"""Tests for the Zenoti customer importer.

Mappers are pure functions — tested directly with literal row dicts.
The orchestrator's correctness covered by:

  - header validation (mismatched columns fail before any writes)
  - idempotent upsert (re-running on the same CSV is a no-op)
  - acquisition_source immutability post-create
  - per-row error log capture
  - in-export duplicate detection
"""

from __future__ import annotations

import datetime as _dt
import io
from textwrap import dedent

from django.test import TestCase

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.imports.zenoti.importer import import_zenoti_guests
from apps.imports.zenoti.mappers import (
    EXPECTED_HEADER,
    _clean_email,
    _clean_phone,
    _normalise_state,
    _parse_date,
    _parse_yes_no,
    _synthetic_id,
    detect_internal_duplicates,
    map_row,
    validate_header,
)
from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant_with_defaults

from django.contrib.auth import get_user_model

User = get_user_model()


# ── Pure mapper unit tests ─────────────────────────────────────────


class CleanersTests(TestCase):
    def test_email_lowercase_and_strips(self):
        self.assertEqual(_clean_email('  Foo@BAR.com  '), 'foo@bar.com')

    def test_email_rejects_malformed(self):
        self.assertEqual(_clean_email('not-an-email'), '')
        self.assertEqual(_clean_email('two@@at.com'), '')
        self.assertEqual(_clean_email('a@nodom'), '')

    def test_phone_normalises_10_digit_us(self):
        self.assertEqual(_clean_phone('3476266978'), '(347) 626-6978')
        self.assertEqual(_clean_phone('(347) 626-6978'), '(347) 626-6978')
        self.assertEqual(_clean_phone('347.626.6978'), '(347) 626-6978')

    def test_phone_strips_leading_country_code(self):
        self.assertEqual(_clean_phone('1-347-626-6978'), '(347) 626-6978')

    def test_state_full_name_to_abbrev(self):
        self.assertEqual(_normalise_state('New York'), 'NY')
        self.assertEqual(_normalise_state('  florida '), 'FL')

    def test_state_passes_unknown_through(self):
        self.assertEqual(_normalise_state('Ontario'), 'Ontario')

    def test_parse_date_zenoti_format(self):
        self.assertEqual(_parse_date('11/5/2023'), _dt.date(2023, 11, 5))
        self.assertEqual(_parse_date('12/2/2025'), _dt.date(2025, 12, 2))

    def test_parse_date_blank_returns_none(self):
        self.assertIsNone(_parse_date(''))
        self.assertIsNone(_parse_date(None))
        self.assertIsNone(_parse_date('not a date'))

    def test_yes_no_parser(self):
        self.assertTrue(_parse_yes_no('Yes'))
        self.assertTrue(_parse_yes_no('  yes  '))
        self.assertFalse(_parse_yes_no('No'))
        self.assertFalse(_parse_yes_no(''))

    def test_synthetic_id_is_stable(self):
        a = _synthetic_id(first='Maria', last='Lopez', phone='(347) 555-1234', email='m@x.com')
        b = _synthetic_id(first='Maria', last='Lopez', phone='3475551234', email='m@x.com')
        self.assertEqual(a, b, 'phone formatting should not affect the synthetic id')

    def test_synthetic_id_changes_with_contact(self):
        a = _synthetic_id(first='Maria', last='Lopez', phone='', email='m@x.com')
        b = _synthetic_id(first='Maria', last='Lopez', phone='', email='other@x.com')
        self.assertNotEqual(a, b)


# ── Header validation ──────────────────────────────────────────────


class ValidateHeaderTests(TestCase):
    def test_exact_match_passes(self):
        self.assertEqual(validate_header(EXPECTED_HEADER), [])

    def test_trailing_blank_columns_tolerated(self):
        # Zenoti pads with empty trailing columns; we should ignore them.
        padded = EXPECTED_HEADER + ['', '']
        self.assertEqual(validate_header(padded), [])

    def test_renamed_column_surfaces_error(self):
        bad = list(EXPECTED_HEADER)
        bad[0] = 'First Name'  # space added — looks innocent but breaks mapping
        errs = validate_header(bad)
        self.assertEqual(len(errs), 1)
        self.assertIn('FirstName', errs[0])
        self.assertIn('First Name', errs[0])


# ── Row mapper ─────────────────────────────────────────────────────


class MapRowTests(TestCase):
    def _row(self, **overrides) -> dict:
        base = {col: '' for col in EXPECTED_HEADER}
        base.update(overrides)
        return base

    def test_maps_a_typical_guest(self):
        row = self._row(
            FirstName='Maria', LastName='Lopez',
            Code='GMLFL100752',
            BaseCenter='Brooklyn',
            Email='maria.lopez@example.com',
            Mobile='(347) 626-6978',
            State='New York', Country='United States',
            DOB='4/15/1990',
            ReceiveMarketingEmail='Yes',
            ReceiveMarketingSMS='No',
            CreationDate='11/5/2023',
        )
        mapped, err = map_row(row, line_number=7)
        self.assertIsNone(err)
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped.first_name, 'Maria')
        self.assertEqual(mapped.last_name, 'Lopez')
        self.assertEqual(mapped.external_id, 'zenoti-code:GMLFL100752')
        self.assertEqual(mapped.email, 'maria.lopez@example.com')
        self.assertEqual(mapped.phone, '(347) 626-6978')
        self.assertEqual(mapped.state, 'NY')
        self.assertEqual(mapped.date_of_birth, _dt.date(1990, 4, 15))
        self.assertTrue(mapped.email_marketing_opt_in)
        self.assertFalse(mapped.sms_marketing_opt_in)
        self.assertEqual(mapped.base_center, 'Brooklyn')
        self.assertIn('Zenoti home center: Brooklyn', mapped.notes)

    def test_synthetic_id_when_code_blank(self):
        row = self._row(
            FirstName='Aaliyah', LastName='Campbell',
            BaseCenter='Brooklyn',
            Email='aaliyah@example.com',
            Mobile='(347) 626-6978',
        )
        mapped, err = map_row(row, line_number=7)
        self.assertIsNone(err)
        self.assertTrue(mapped.external_id.startswith('zenoti-syn:'))
        # Re-running on the SAME row produces the SAME id (idempotency).
        again, _ = map_row(row, line_number=7)
        self.assertEqual(mapped.external_id, again.external_id)

    def test_missing_both_names_returns_error(self):
        row = self._row(FirstName='', LastName='', Code='X1', Email='x@y.com')
        mapped, err = map_row(row, line_number=99)
        self.assertIsNone(mapped)
        self.assertIsNotNone(err)
        self.assertEqual(err.line_number, 99)
        self.assertIn('FirstName', err.reason)


# ── Duplicate detection ────────────────────────────────────────────


class DetectInternalDuplicatesTests(TestCase):
    def _mapped(self, eid: str):
        from apps.imports.zenoti.mappers import MappedCustomer
        return MappedCustomer(external_id=eid, first_name='X', last_name='Y')

    def test_no_dupes(self):
        self.assertEqual(
            detect_internal_duplicates([self._mapped('a'), self._mapped('b')]),
            {},
        )

    def test_groups_dupes(self):
        rows = [self._mapped('a'), self._mapped('a'), self._mapped('b'), self._mapped('a')]
        groups = detect_internal_duplicates(rows)
        self.assertIn('a', groups)
        self.assertEqual(len(groups['a']), 3)
        self.assertNotIn('b', groups)


# ── End-to-end importer ────────────────────────────────────────────


_PREAMBLE = dedent('''\
    Table 1
    Manhattan Laser Spa,,,,,,,,,,,,,,,,,,,,,,,,,
    Center : Florida,,,,,,,,,,,,,,,,,,,,,,,,,
    UserExport,,,,,,,,,,,,,,,,,,,,,,,,,
    ,,,,,,,,,,,,,,,,,,,,,,,,,
''')

_HEADER_LINE = ','.join(EXPECTED_HEADER) + ',,\n'


def _csv_with_rows(rows: list[str]) -> io.StringIO:
    return io.StringIO(_PREAMBLE + _HEADER_LINE + '\n'.join(rows) + '\n')


class ImporterEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user(email='owner@test.local', password='x')
        cls.tenant = create_tenant_with_defaults(
            name='Manhattan Laser Spa', slug='mls-test', owner_user=owner,
            status=Tenant.Status.ACTIVE,
        )

    def test_dry_run_does_not_write(self):
        csv_obj = _csv_with_rows([
            'Maria,Lopez,GMLFL100752,Brooklyn,Female,Guest,maria@example.com,(347) 626-6978,,,,,,New York,United States,,4/15/1990,,,Yes,Yes,,Midtown,11/5/2023,,',
        ])
        report = import_zenoti_guests(tenant=self.tenant, file_obj=csv_obj, dry_run=True)
        self.assertEqual(report.rows_read, 1)
        self.assertEqual(report.rows_mapped, 1)
        self.assertEqual(report.rows_created, 0)
        self.assertEqual(report.rows_updated, 0)
        # Crucially: no Customer rows written.
        self.assertEqual(
            Customer.objects.filter(tenant=self.tenant, external_source='zenoti').count(),
            0,
        )

    def test_live_import_creates_customer(self):
        csv_obj = _csv_with_rows([
            'Maria,Lopez,GMLFL100752,Brooklyn,Female,Guest,maria@example.com,(347) 626-6978,,,,,,New York,United States,,4/15/1990,,,Yes,No,,Midtown,11/5/2023,,',
        ])
        report = import_zenoti_guests(tenant=self.tenant, file_obj=csv_obj, dry_run=False)
        self.assertEqual(report.rows_created, 1)
        self.assertEqual(report.rows_updated, 0)
        c = Customer.objects.get(
            tenant=self.tenant, external_id='zenoti-code:GMLFL100752',
        )
        self.assertEqual(c.first_name, 'Maria')
        self.assertEqual(c.email, 'maria@example.com')
        self.assertEqual(c.acquisition_source, Customer.AcquisitionSource.ZENOTI_IMPORT)
        self.assertTrue(c.email_marketing_opt_in)
        self.assertFalse(c.sms_marketing_opt_in)
        # Audit entries: per-row + aggregate.
        per_row = AuditLog.objects.filter(
            tenant=self.tenant, resource_type='customer',
        )
        self.assertEqual(per_row.count(), 1)
        self.assertEqual(per_row.first().metadata.get('source'), 'zenoti_import')
        agg = AuditLog.objects.filter(
            tenant=self.tenant, resource_type='zenoti_import_run',
        )
        self.assertEqual(agg.count(), 1)

    def test_idempotent_rerun(self):
        row = 'Maria,Lopez,GMLFL100752,Brooklyn,Female,Guest,maria@example.com,(347) 626-6978,,,,,,New York,United States,,,,,Yes,Yes,,Midtown,,,'
        import_zenoti_guests(tenant=self.tenant, file_obj=_csv_with_rows([row]), dry_run=False)
        report2 = import_zenoti_guests(tenant=self.tenant, file_obj=_csv_with_rows([row]), dry_run=False)
        self.assertEqual(report2.rows_created, 0)
        self.assertEqual(report2.rows_updated, 1)
        # Exactly one row in the DB.
        self.assertEqual(
            Customer.objects.filter(
                tenant=self.tenant, external_id='zenoti-code:GMLFL100752',
            ).count(),
            1,
        )

    def test_acquisition_source_immutable_post_create(self):
        """Re-running should NOT change acquisition_source even if we
        somehow tried to (the importer's write_kwargs() intentionally
        excludes it on update)."""
        row = 'Maria,Lopez,GMLFL100752,Brooklyn,Female,Guest,maria@example.com,(347) 626-6978,,,,,,New York,United States,,,,,Yes,Yes,,Midtown,,,'
        import_zenoti_guests(tenant=self.tenant, file_obj=_csv_with_rows([row]), dry_run=False)
        # Operator manually changes the customer's acquisition_source
        # via admin (shouldn't normally happen, but defending the rule).
        c = Customer.objects.get(tenant=self.tenant, external_id='zenoti-code:GMLFL100752')
        c.acquisition_source = Customer.AcquisitionSource.REFERRAL
        c.save(update_fields=['acquisition_source'])
        # Re-import.
        import_zenoti_guests(tenant=self.tenant, file_obj=_csv_with_rows([row]), dry_run=False)
        c.refresh_from_db()
        self.assertEqual(c.acquisition_source, Customer.AcquisitionSource.REFERRAL)

    def test_blank_name_row_logged_as_error(self):
        csv_obj = _csv_with_rows([
            ',,X1,Brooklyn,Female,Guest,,,,,,,,New York,,,,,,Yes,Yes,,Midtown,,,',
        ])
        report = import_zenoti_guests(tenant=self.tenant, file_obj=csv_obj, dry_run=True)
        self.assertEqual(report.rows_failed_mapping, 1)
        self.assertEqual(report.rows_mapped, 0)
        self.assertEqual(len(report.mapping_errors), 1)

    def test_in_export_duplicate_detected(self):
        # Same Code appearing twice in one export.
        rows = [
            'Maria,Lopez,SAME,Brooklyn,Female,Guest,maria@example.com,(347) 626-6978,,,,,,New York,United States,,,,,Yes,Yes,,Midtown,,,',
            'Maria,Lopez,SAME,Brooklyn,Female,Guest,maria@example.com,(347) 626-6978,,,,,,New York,United States,,,,,Yes,Yes,,Midtown,,,',
        ]
        report = import_zenoti_guests(tenant=self.tenant, file_obj=_csv_with_rows(rows), dry_run=False)
        self.assertIn('zenoti-code:SAME', report.duplicate_external_ids)
        # Only one Customer row written despite two source rows.
        self.assertEqual(report.rows_created + report.rows_updated, 1)
        self.assertEqual(report.rows_skipped_duplicate_in_export, 1)
