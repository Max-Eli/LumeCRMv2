"""Tests for the Zenoti appointments importer.

Coverage:
  - Pure mapper: status resolution (closed / cancelled / no-show /
    open past vs future / checkin / deleted), datetime parsing
    (tenant-tz aware), duration parsing.
  - Schedule inference: per-provider weekday set, 8am-8pm blocks.
  - Multi-file dedup (later file wins on Invoice No collision).
  - End-to-end: customer + service + provider matching, status
    classification, invoice close + void wiring, schedule write.
"""

from __future__ import annotations

import datetime as _dt
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.customers.models import Customer
from apps.imports.zenoti.appointments_importer import import_zenoti_appointments
from apps.imports.zenoti.appointments_mapper import (
    EXPECTED_HEADER,
    _parse_datetime,
    _parse_duration_to_minutes,
    infer_provider_weekly_hours,
    map_row,
    merge_appointment_files,
    validate_header,
)
from apps.invoices.models import Invoice
from apps.services.models import Service
from apps.tenants.models import (
    Location, MembershipLocation, ProviderSchedule, Tenant, TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults


User = get_user_model()


# ── Pure parsers ───────────────────────────────────────────────────


class DurationParserTests(TestCase):
    def test_normal(self):
        self.assertEqual(_parse_duration_to_minutes('1:30'), 90)
        self.assertEqual(_parse_duration_to_minutes('0:45'), 45)
        self.assertEqual(_parse_duration_to_minutes('2:00'), 120)

    def test_blank(self):
        self.assertEqual(_parse_duration_to_minutes(''), 0)
        self.assertEqual(_parse_duration_to_minutes(None), 0)


class DatetimeParserTests(TestCase):
    def test_zenoti_format_ny_tz(self):
        # 11/13/2026 11:00 AM in America/New_York → tz-aware UTC.
        dt = _parse_datetime('11/13/2026 11:00 AM')
        self.assertIsNotNone(dt)
        # Nov 13 2026 11:00 ET is UTC-5 (EST) → 16:00 UTC.
        self.assertEqual(dt.tzinfo, _dt.timezone.utc)
        self.assertEqual(dt.month, 11)
        self.assertEqual(dt.day, 13)
        self.assertEqual(dt.hour, 16)
        self.assertEqual(dt.minute, 0)

    def test_blank_returns_none(self):
        self.assertIsNone(_parse_datetime(''))
        self.assertIsNone(_parse_datetime(None))


# ── Map row ────────────────────────────────────────────────────────


class AppointmentMapRowTests(TestCase):
    def _row(self, **overrides) -> dict:
        base = {c: '' for c in EXPECTED_HEADER}
        base.update(overrides)
        return base

    def _now(self):
        return _dt.datetime(2026, 5, 18, 12, 0, 0, tzinfo=_dt.timezone.utc)

    def test_closed_past_becomes_completed(self):
        row = self._row(**{
            'Invoice No': '100', 'Guest Name': 'A B',
            'Service Name': 'X', 'Provider': 'Y Z',
            'Start Time': '1/1/2026 10:00 AM',
            'End Time': '1/1/2026 11:00 AM',
            'Status': 'Closed',
        })
        m, err = map_row(row, line_number=2, now=self._now())
        self.assertIsNone(err)
        self.assertEqual(m.lume_status, 'completed')
        self.assertTrue(m.close_invoice)
        self.assertFalse(m.void_invoice)

    def test_open_future_becomes_booked(self):
        row = self._row(**{
            'Invoice No': '101', 'Guest Name': 'A B',
            'Service Name': 'X', 'Provider': 'Y Z',
            'Start Time': '11/15/2026 10:00 AM',
            'End Time': '11/15/2026 11:00 AM',
            'Status': 'Open',
        })
        m, _ = map_row(row, line_number=2, now=self._now())
        self.assertEqual(m.lume_status, 'booked')
        self.assertFalse(m.close_invoice)
        self.assertFalse(m.void_invoice)

    def test_open_past_becomes_completed(self):
        """Per operator instruction: past appointments are completed
        with OTHER payment regardless of upstream status."""
        row = self._row(**{
            'Invoice No': '102', 'Guest Name': 'A B',
            'Service Name': 'X', 'Provider': 'Y Z',
            'Start Time': '2/1/2026 10:00 AM',
            'End Time': '2/1/2026 11:00 AM',
            'Status': 'Open',
        })
        m, _ = map_row(row, line_number=2, now=self._now())
        self.assertEqual(m.lume_status, 'completed')
        self.assertTrue(m.close_invoice)

    def test_cancelled_voids_invoice(self):
        row = self._row(**{
            'Invoice No': '103', 'Guest Name': 'A B',
            'Service Name': 'X', 'Provider': 'Y Z',
            'Start Time': '2/1/2026 10:00 AM',
            'End Time': '2/1/2026 11:00 AM',
            'Status': 'Cancelled',
        })
        m, _ = map_row(row, line_number=2, now=self._now())
        self.assertEqual(m.lume_status, 'cancelled')
        self.assertTrue(m.void_invoice)
        self.assertFalse(m.close_invoice)

    def test_no_show_voids_invoice(self):
        row = self._row(**{
            'Invoice No': '104', 'Guest Name': 'A B',
            'Service Name': 'X', 'Provider': 'Y Z',
            'Start Time': '2/1/2026 10:00 AM',
            'End Time': '2/1/2026 11:00 AM',
            'Status': 'No Show',
        })
        m, _ = map_row(row, line_number=2, now=self._now())
        self.assertEqual(m.lume_status, 'no_show')
        self.assertTrue(m.void_invoice)

    def test_deleted_is_skipped(self):
        row = self._row(**{
            'Invoice No': '105', 'Guest Name': 'A B',
            'Service Name': 'X', 'Provider': 'Y Z',
            'Start Time': '2/1/2026 10:00 AM',
            'End Time': '2/1/2026 11:00 AM',
            'Status': 'Deleted',
        })
        m, err = map_row(row, line_number=2, now=self._now())
        self.assertIsNone(m)
        self.assertTrue(err.reason.startswith('Skipped'))

    def test_blank_invoice_no_is_error(self):
        row = self._row(**{
            'Invoice No': '', 'Guest Name': 'A B',
            'Service Name': 'X', 'Provider': 'Y Z',
            'Start Time': '2/1/2026 10:00 AM',
            'End Time': '2/1/2026 11:00 AM',
            'Status': 'Closed',
        })
        m, err = map_row(row, line_number=2, now=self._now())
        self.assertIsNone(m)
        self.assertIn('Invoice No', err.reason)


# ── Schedule inference ────────────────────────────────────────────


class ScheduleInferenceTests(TestCase):
    def _appt(self, provider, weekday_iso_dt):
        from apps.imports.zenoti.appointments_mapper import MappedAppointment
        return MappedAppointment(
            external_id=f'x:{provider}:{weekday_iso_dt}',
            provider_name=provider,
            start_time=_dt.datetime.fromisoformat(weekday_iso_dt).replace(
                tzinfo=_dt.timezone.utc,
            ),
        )

    def test_per_provider_weekday_set(self):
        # 2026-05-11 = Monday (NY tz), 2026-05-13 = Wednesday.
        # Use noon UTC so the localtime conversion doesn't shift weekday.
        appts = [
            self._appt('Alice', '2026-05-11T16:00:00'),
            self._appt('Alice', '2026-05-13T16:00:00'),
            self._appt('Bob', '2026-05-12T16:00:00'),
        ]
        schedules = infer_provider_weekly_hours(appts)
        # Alice → monday + wednesday.
        alice = schedules['Alice']
        self.assertEqual(alice['monday'], [{'start': '08:00', 'end': '20:00'}])
        self.assertEqual(alice['wednesday'], [{'start': '08:00', 'end': '20:00'}])
        self.assertEqual(alice['tuesday'], [])
        self.assertEqual(alice['sunday'], [])
        # Bob → only tuesday.
        bob = schedules['Bob']
        self.assertEqual(bob['tuesday'], [{'start': '08:00', 'end': '20:00'}])
        self.assertEqual(bob['monday'], [])


# ── Multi-file dedup ──────────────────────────────────────────────


class MergeFilesTests(TestCase):
    def _appt(self, eid):
        from apps.imports.zenoti.appointments_mapper import MappedAppointment
        return MappedAppointment(external_id=eid)

    def test_dedup_later_wins(self):
        a1 = self._appt('shared')
        a1.upstream_status = 'open'
        a2 = self._appt('shared')
        a2.upstream_status = 'closed'  # newer file
        merged, dupes = merge_appointment_files([[a1], [a2]])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].upstream_status, 'closed')
        self.assertEqual(dupes, ['shared'])


# ── End-to-end ─────────────────────────────────────────────────────


_HEADER_LINE = ','.join(f'"{c}"' for c in EXPECTED_HEADER) + '\n'


def _csv(rows: list[str]) -> io.StringIO:
    return io.StringIO(_HEADER_LINE + '\n'.join(rows) + '\n')


def _row_csv(**overrides) -> str:
    base = {c: '' for c in EXPECTED_HEADER}
    base.update(overrides)
    return ','.join('"' + str(base[c]).replace('"', '""') + '"' for c in EXPECTED_HEADER)


class AppointmentsImporterEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user(email='appt-owner@test.local', password='x')
        cls.tenant = create_tenant_with_defaults(
            name='Appt Test Spa', slug='appt-test', owner_user=owner,
            status=Tenant.Status.ACTIVE,
        )
        cls.location = Location.objects.get(tenant=cls.tenant, is_default=True)
        # Customer.
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Jane', last_name='Doe',
        )
        # Service.
        cls.service = Service.objects.create(
            tenant=cls.tenant, name='Botox',
            price_cents=50000, duration_minutes=30,
        )
        # Provider: bookable membership for 'Maria Lopez'.
        provider_user = User.objects.create_user(
            email='maria.lopez@test.local',
            first_name='Maria', last_name='Lopez', password='x',
        )
        cls.provider = TenantMembership.objects.create(
            tenant=cls.tenant, user=provider_user,
            role=TenantMembership.Role.PROVIDER, is_active=True, is_bookable=True,
        )
        MembershipLocation.objects.create(
            membership=cls.provider, location=cls.location, is_active=True,
        )

    def test_past_completed_closes_invoice_with_other(self):
        # Future-dated `now` so the appointment's actual start_time
        # falls in the past relative to `now`.
        appt_row = _row_csv(**{
            'Invoice No': '200', 'Guest Name': 'Jane Doe',
            'Service Name': 'Botox', 'Provider': 'Maria Lopez',
            'Center Name': 'Florida',
            'Start Time': '1/15/2026 10:00 AM',
            'End Time': '1/15/2026 10:30 AM',
            'Status': 'Closed',
        })
        report = import_zenoti_appointments(
            tenant=self.tenant, file_objs=[_csv([appt_row])], dry_run=False,
        )
        self.assertEqual(report.rows_created, 1)
        self.assertEqual(report.invoices_closed, 1)
        appt = Appointment.objects.get(external_id='zenoti-appt:200')
        self.assertEqual(appt.status, 'completed')
        invoice = Invoice.objects.get(appointment=appt)
        self.assertEqual(invoice.status, 'paid')
        self.assertEqual(invoice.payment_method, 'other')

    def test_cancelled_voids_invoice(self):
        row = _row_csv(**{
            'Invoice No': '201', 'Guest Name': 'Jane Doe',
            'Service Name': 'Botox', 'Provider': 'Maria Lopez',
            'Start Time': '1/15/2026 10:00 AM',
            'End Time': '1/15/2026 10:30 AM',
            'Status': 'Cancelled',
        })
        report = import_zenoti_appointments(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        self.assertEqual(report.invoices_voided, 1)
        appt = Appointment.objects.get(external_id='zenoti-appt:201')
        self.assertEqual(appt.status, 'cancelled')
        invoice = Invoice.objects.get(appointment=appt)
        self.assertEqual(invoice.status, 'void')

    def test_provider_match_miss_skips_row(self):
        row = _row_csv(**{
            'Invoice No': '202', 'Guest Name': 'Jane Doe',
            'Service Name': 'Botox', 'Provider': 'Ghost Person',
            'Start Time': '1/15/2026 10:00 AM',
            'End Time': '1/15/2026 10:30 AM',
            'Status': 'Closed',
        })
        report = import_zenoti_appointments(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        self.assertEqual(report.rows_created, 0)
        self.assertEqual(report.rows_skipped_no_provider, 1)
        self.assertIn('Ghost Person', report.provider_misses)

    def test_provider_schedule_set_from_appointment_weekday(self):
        # 2026-05-11 (UTC noon) = Monday in NY (5/11 morning ET).
        row = _row_csv(**{
            'Invoice No': '203', 'Guest Name': 'Jane Doe',
            'Service Name': 'Botox', 'Provider': 'Maria Lopez',
            'Start Time': '5/11/2026 10:00 AM',
            'End Time': '5/11/2026 10:30 AM',
            'Status': 'Open',
        })
        report = import_zenoti_appointments(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        self.assertEqual(report.schedules_set, 1)
        ml = MembershipLocation.objects.get(
            membership=self.provider, location=self.location,
        )
        schedule = ProviderSchedule.objects.get(membership_location=ml)
        self.assertEqual(
            schedule.weekly_hours['monday'],
            [{'start': '08:00', 'end': '20:00'}],
        )
        self.assertEqual(schedule.weekly_hours['tuesday'], [])

    def test_idempotent_rerun(self):
        row = _row_csv(**{
            'Invoice No': '204', 'Guest Name': 'Jane Doe',
            'Service Name': 'Botox', 'Provider': 'Maria Lopez',
            'Start Time': '1/15/2026 10:00 AM',
            'End Time': '1/15/2026 10:30 AM',
            'Status': 'Open',
        })
        import_zenoti_appointments(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        report2 = import_zenoti_appointments(
            tenant=self.tenant, file_objs=[_csv([row])], dry_run=False,
        )
        self.assertEqual(report2.rows_created, 0)
        self.assertEqual(report2.rows_updated, 1)
        # Still exactly one appointment.
        self.assertEqual(
            Appointment.objects.filter(external_id='zenoti-appt:204').count(),
            1,
        )
