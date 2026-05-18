"""Tests for the Zenoti employees importer.

Covers the mapper's filter rules (ACTIVE=No, MANAGER/OWNER skip),
job → role mapping, email handling (real vs placeholder), and the
end-to-end User + TenantMembership + MembershipLocation creation.
"""

from __future__ import annotations

import io
from textwrap import dedent

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.imports.zenoti.employees_importer import import_zenoti_employees
from apps.imports.zenoti.employees_mapper import (
    EXPECTED_HEADER,
    SKIPPED_JOBS,
    _looks_like_email,
    _parse_date,
    map_row,
    validate_header,
)
from apps.tenants.models import (
    Location, MembershipLocation, Tenant, TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults


User = get_user_model()


# ── Pure helpers ───────────────────────────────────────────────────


class LooksLikeEmailTests(TestCase):
    def test_real_email_passes(self):
        self.assertTrue(_looks_like_email('ivan@example.com'))
        self.assertTrue(_looks_like_email('a.b.c@x.co.uk'))

    def test_handle_rejected(self):
        self.assertFalse(_looks_like_email('julia'))
        self.assertFalse(_looks_like_email('ad'))

    def test_no_dot_in_domain_rejected(self):
        self.assertFalse(_looks_like_email('a@b'))


class ParseDateTests(TestCase):
    def test_zenoti_iso_format(self):
        import datetime as _dt
        self.assertEqual(_parse_date('2022-01-01 00:00:00'), _dt.date(2022, 1, 1))

    def test_us_format(self):
        import datetime as _dt
        self.assertEqual(_parse_date('5/15/2025'), _dt.date(2025, 5, 15))


# ── Header validation ──────────────────────────────────────────────


class EmployeesHeaderTests(TestCase):
    def test_exact_match(self):
        self.assertEqual(validate_header(EXPECTED_HEADER), [])

    def test_mismatch_fires(self):
        bad = list(EXPECTED_HEADER)
        bad[15] = 'Position'  # was 'JOB'
        errs = validate_header(bad)
        self.assertEqual(len(errs), 1)
        self.assertIn('JOB', errs[0])


# ── Row mapper ─────────────────────────────────────────────────────


class EmployeesMapRowTests(TestCase):
    def _row(self, **overrides) -> dict:
        base = {c: '' for c in EXPECTED_HEADER}
        base.update(overrides)
        return base

    def test_active_technician_maps_to_bookable_provider(self):
        row = self._row(**{
            'CODE': 'ARIONA', 'FIRST NAME': 'Ariona', 'LAST NAME': 'Dhima',
            'UserName': 'ad', 'JOB': 'TECHNICIAN', 'ACTIVE': 'Yes',
            'StartDate': '2022-01-01 00:00:00',
        })
        m, err = map_row(row, line_number=2)
        self.assertIsNone(err)
        self.assertEqual(m.role, 'provider')
        self.assertTrue(m.is_bookable)
        self.assertEqual(m.job_title_name, 'Technician')
        # 'ad' isn't an email → placeholder.
        self.assertTrue(m.email.endswith('@imported.lume-crm.local'))
        self.assertIn('ariona', m.email)

    def test_real_email_used_as_is(self):
        row = self._row(**{
            'CODE': 'IVAN', 'FIRST NAME': 'Ivan', 'LAST NAME': 'Seidametov',
            'UserName': 'ivan.seidametov@gmail.com',
            'JOB': 'MASSAGE THERAPIST', 'ACTIVE': 'Yes',
        })
        m, _ = map_row(row, line_number=2)
        self.assertEqual(m.email, 'ivan.seidametov@gmail.com')
        self.assertEqual(m.job_title_name, 'Massage Therapist')

    def test_receptionist_imported_but_not_bookable(self):
        row = self._row(**{
            'CODE': 'CHRIS', 'FIRST NAME': 'Chris', 'LAST NAME': 'Smith',
            'UserName': 'chris@example.com',
            'JOB': 'RECEPTIONIST', 'ACTIVE': 'Yes',
        })
        m, err = map_row(row, line_number=2)
        self.assertIsNone(err)
        self.assertEqual(m.role, 'front_desk')
        self.assertFalse(m.is_bookable)

    def test_inactive_is_skipped(self):
        row = self._row(**{
            'CODE': 'X', 'FIRST NAME': 'X', 'LAST NAME': 'Y',
            'JOB': 'TECHNICIAN', 'ACTIVE': 'No',
        })
        m, err = map_row(row, line_number=2)
        self.assertIsNone(m)
        self.assertTrue(err.reason.startswith('Skipped (ACTIVE='))

    def test_manager_is_skipped(self):
        row = self._row(**{
            'CODE': 'X', 'FIRST NAME': 'X', 'LAST NAME': 'Y',
            'JOB': 'MANAGER', 'ACTIVE': 'Yes',
        })
        m, err = map_row(row, line_number=2)
        self.assertIsNone(m)
        self.assertIn('MANAGER', err.reason)

    def test_owner_is_skipped(self):
        row = self._row(**{
            'CODE': 'X', 'FIRST NAME': 'X', 'LAST NAME': 'Y',
            'JOB': 'OWNER', 'ACTIVE': 'Yes',
        })
        m, err = map_row(row, line_number=2)
        self.assertIsNone(m)
        self.assertIn('OWNER', err.reason)

    def test_hourly_rate_becomes_pay_type_hourly(self):
        row = self._row(**{
            'CODE': 'X', 'FIRST NAME': 'X', 'LAST NAME': 'Y',
            'JOB': 'TECHNICIAN', 'ACTIVE': 'Yes',
            'HourlyRate': '25.0000',
        })
        m, _ = map_row(row, line_number=2)
        self.assertEqual(m.pay_type, 'hourly')
        self.assertEqual(m.pay_rate_cents, 2500)


# ── End-to-end ─────────────────────────────────────────────────────


_HEADER_LINE = ','.join(f'"{c}"' for c in EXPECTED_HEADER) + '\n'


def _csv(rows: list[str]) -> io.StringIO:
    return io.StringIO(_HEADER_LINE + '\n'.join(rows) + '\n')


def _row_csv(**overrides) -> str:
    base = {c: '' for c in EXPECTED_HEADER}
    base.update(overrides)
    return ','.join('"' + str(base[c]).replace('"', '""') + '"' for c in EXPECTED_HEADER)


class EmployeesImporterEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user(email='emp-owner@test.local', password='x')
        cls.tenant = create_tenant_with_defaults(
            name='Emp Test Spa', slug='emp-test', owner_user=owner,
            status=Tenant.Status.ACTIVE,
        )

    def test_dry_run_writes_nothing(self):
        row = _row_csv(
            **{
                'CODE': 'X', 'FIRST NAME': 'X', 'LAST NAME': 'Y',
                'UserName': 'x@y.com', 'JOB': 'TECHNICIAN', 'ACTIVE': 'Yes',
            }
        )
        report = import_zenoti_employees(
            tenant=self.tenant, file_obj=_csv([row]), dry_run=True,
        )
        self.assertEqual(report.rows_mapped, 1)
        self.assertEqual(report.memberships_created, 0)
        self.assertEqual(
            TenantMembership.objects.filter(tenant=self.tenant, user__email='x@y.com').count(),
            0,
        )

    def test_live_import_creates_user_membership_location(self):
        row = _row_csv(
            **{
                'CODE': 'IVAN', 'FIRST NAME': 'Ivan', 'LAST NAME': 'S',
                'UserName': 'ivan@example.com',
                'JOB': 'MASSAGE THERAPIST', 'ACTIVE': 'Yes',
                'StartDate': '2025-06-01 00:00:00',
                'HourlyRate': '40.0000',
            }
        )
        report = import_zenoti_employees(
            tenant=self.tenant, file_obj=_csv([row]), dry_run=False,
        )
        self.assertEqual(report.users_created, 1)
        self.assertEqual(report.memberships_created, 1)
        # `create_tenant_with_defaults` seeds 9 default JobTitles
        # including "Massage Therapist" — so the importer reuses it
        # rather than creating a new one. The job_title FK is still set.
        self.assertEqual(report.locations_assigned, 1)

        membership = TenantMembership.objects.get(
            tenant=self.tenant, user__email='ivan@example.com',
        )
        self.assertEqual(membership.role, 'provider')
        self.assertTrue(membership.is_bookable)
        self.assertEqual(membership.job_title.name, 'Massage Therapist')
        self.assertEqual(membership.pay_type, 'hourly')
        self.assertEqual(membership.pay_rate_cents, 4000)
        # Auto-assigned to the tenant's default location.
        loc = Location.objects.get(tenant=self.tenant, is_default=True)
        self.assertTrue(
            MembershipLocation.objects.filter(
                membership=membership, location=loc, is_active=True,
            ).exists()
        )

    def test_idempotent_rerun(self):
        row = _row_csv(
            **{
                'CODE': 'IVAN', 'FIRST NAME': 'Ivan', 'LAST NAME': 'S',
                'UserName': 'ivan@example.com',
                'JOB': 'MASSAGE THERAPIST', 'ACTIVE': 'Yes',
            }
        )
        import_zenoti_employees(
            tenant=self.tenant, file_obj=_csv([row]), dry_run=False,
        )
        report2 = import_zenoti_employees(
            tenant=self.tenant, file_obj=_csv([row]), dry_run=False,
        )
        self.assertEqual(report2.users_created, 0)
        self.assertEqual(report2.users_reused, 1)
        self.assertEqual(report2.memberships_created, 0)
        self.assertEqual(report2.memberships_reused, 1)
        # Still exactly one of each.
        self.assertEqual(
            User.objects.filter(email='ivan@example.com').count(), 1,
        )
        self.assertEqual(
            TenantMembership.objects.filter(
                tenant=self.tenant, user__email='ivan@example.com',
            ).count(),
            1,
        )

    def test_existing_user_keeps_their_name(self):
        # Operator already created Ivan with a different first_name —
        # Zenoti shouldn't clobber it.
        User.objects.create_user(
            email='ivan@example.com',
            first_name='Ivan-Operator-Edited',
            last_name='Real-Last',
            password='x',
        )
        row = _row_csv(
            **{
                'CODE': 'IVAN', 'FIRST NAME': 'IvanZenoti', 'LAST NAME': 'ZenotiLast',
                'UserName': 'ivan@example.com',
                'JOB': 'MASSAGE THERAPIST', 'ACTIVE': 'Yes',
            }
        )
        import_zenoti_employees(
            tenant=self.tenant, file_obj=_csv([row]), dry_run=False,
        )
        u = User.objects.get(email='ivan@example.com')
        self.assertEqual(u.first_name, 'Ivan-Operator-Edited')
        self.assertEqual(u.last_name, 'Real-Last')

    def test_filtered_jobs_counted_separately(self):
        rows = [
            _row_csv(**{
                'CODE': 'A', 'FIRST NAME': 'A', 'LAST NAME': 'Z',
                'JOB': 'MANAGER', 'ACTIVE': 'Yes',
            }),
            _row_csv(**{
                'CODE': 'B', 'FIRST NAME': 'B', 'LAST NAME': 'Z',
                'JOB': 'OWNER', 'ACTIVE': 'Yes',
            }),
            _row_csv(**{
                'CODE': 'C', 'FIRST NAME': 'C', 'LAST NAME': 'Z',
                'JOB': 'TECHNICIAN', 'ACTIVE': 'No',
            }),
            _row_csv(**{
                'CODE': 'D', 'FIRST NAME': 'D', 'LAST NAME': 'Z',
                'UserName': 'd@x.com', 'JOB': 'TECHNICIAN', 'ACTIVE': 'Yes',
            }),
        ]
        report = import_zenoti_employees(
            tenant=self.tenant, file_obj=_csv(rows), dry_run=False,
        )
        self.assertEqual(report.rows_skipped_filtered_job, 2)
        self.assertEqual(report.rows_skipped_inactive, 1)
        self.assertEqual(report.memberships_created, 1)
