"""Zenoti employees import orchestration.

Creates User + TenantMembership + MembershipLocation rows per
imported employee:

  - User      (email-as-key idempotency; existing users by email
              are NOT re-created, just re-linked to the tenant)
  - TenantMembership (role + is_bookable + JobTitle FK + employment
              fields; found-or-created per (tenant, user))
  - MembershipLocation (auto-assigned to the tenant's default
              Location so they show up on the calendar)

Two-pass mirrors the other importers (customers / services / packages):

  Pass 1: validate header, map every row (skipped + failures
          counted separately), detect email duplicates inside the
          export. NO DB writes.
  Pass 2: per-row upsert wrapped in atomic. One bad row never rolls
          back the others. Per-row + aggregate audit entries.

JobTitle creation is a side effect: each unique (tenant, title) is
auto-created via get_or_create. JobTitle's `is_clinical` flag stays
default (False) — operator can flip it later for clinical roles
like NURSE if compliance reports need the distinction.

Existing users (by email) keep their original name + phone (we
don't overwrite them in case the email matches a real person
who's already in the system with different formatting).
"""

from __future__ import annotations

import csv
import logging
import secrets
from dataclasses import dataclass, field
from typing import IO

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.services import record as audit_record
from apps.tenants.models import (
    JobTitle, Location, MembershipLocation, Tenant, TenantMembership,
)

from .employees_mapper import (
    EXPECTED_HEADER,
    EmployeeMapError,
    MappedEmployee,
    detect_email_duplicates,
    map_row,
    validate_header,
)

User = get_user_model()
logger = logging.getLogger(__name__)


@dataclass
class EmployeesImportReport:
    rows_read: int = 0
    rows_mapped: int = 0
    rows_skipped_inactive: int = 0
    rows_skipped_filtered_job: int = 0
    rows_failed_mapping: int = 0
    rows_skipped_duplicate_in_export: int = 0
    rows_skipped_db_error: int = 0
    users_created: int = 0
    users_reused: int = 0
    memberships_created: int = 0
    memberships_reused: int = 0
    job_titles_created: int = 0
    locations_assigned: int = 0
    header_errors: list[str] = field(default_factory=list)
    mapping_errors: list[EmployeeMapError] = field(default_factory=list)
    db_errors: list[str] = field(default_factory=list)
    duplicate_emails: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict:
        return {
            'rows_read': self.rows_read,
            'rows_mapped': self.rows_mapped,
            'rows_skipped_inactive': self.rows_skipped_inactive,
            'rows_skipped_filtered_job': self.rows_skipped_filtered_job,
            'rows_failed_mapping': self.rows_failed_mapping,
            'rows_skipped_duplicate_in_export': self.rows_skipped_duplicate_in_export,
            'rows_skipped_db_error': self.rows_skipped_db_error,
            'users_created': self.users_created,
            'users_reused': self.users_reused,
            'memberships_created': self.memberships_created,
            'memberships_reused': self.memberships_reused,
            'job_titles_created': self.job_titles_created,
            'locations_assigned': self.locations_assigned,
            'header_error_count': len(self.header_errors),
            'mapping_error_count': len(self.mapping_errors),
            'db_error_count': len(self.db_errors),
            'duplicate_email_count': len(self.duplicate_emails),
        }


def import_zenoti_employees(
    *,
    tenant: Tenant,
    file_obj: IO,
    dry_run: bool = True,
    actor=None,
) -> EmployeesImportReport:
    """Run an employees import against `tenant`.

    Returns the reconciliation report. Skipped-row kinds are split
    into three counters so the operator can tell intentional filters
    (inactive, MANAGER/OWNER) from real mapping failures (blank
    names, bad data).
    """
    report = EmployeesImportReport()

    reader = csv.DictReader(file_obj)
    header_list = reader.fieldnames or []
    header_errors = validate_header(header_list)
    if header_errors:
        report.header_errors.extend(header_errors)
        return report

    # ── Pass 1: map every row ──────────────────────────────────────
    mapped_rows: list[MappedEmployee] = []
    for line_number, row in enumerate(reader, start=2):
        report.rows_read += 1
        mapped, err = map_row(row, line_number=line_number)
        if err is not None:
            if err.reason.startswith('Skipped (ACTIVE='):
                report.rows_skipped_inactive += 1
            elif err.reason.startswith('Skipped (JOB='):
                report.rows_skipped_filtered_job += 1
            else:
                report.rows_failed_mapping += 1
                report.mapping_errors.append(err)
        if mapped is not None:
            mapped_rows.append(mapped)
    report.rows_mapped = len(mapped_rows)

    dupes = detect_email_duplicates(mapped_rows)
    report.duplicate_emails = list(dupes.keys())

    if dry_run:
        return report

    # ── Pass 2: write ──────────────────────────────────────────────
    default_location = (
        Location.objects.filter(tenant=tenant, is_default=True).first()
        or Location.objects.filter(tenant=tenant).order_by('id').first()
    )
    job_title_cache: dict[str, JobTitle] = {}
    seen_emails: set[str] = set()

    for mapped in mapped_rows:
        if mapped.email in seen_emails:
            report.rows_skipped_duplicate_in_export += 1
            continue
        seen_emails.add(mapped.email)

        try:
            user, user_created = _upsert_user(mapped)
            job_title = _resolve_job_title(
                tenant=tenant, name=mapped.job_title_name,
                cache=job_title_cache, report=report,
            )
            membership, membership_created = _upsert_membership(
                tenant=tenant, user=user, mapped=mapped, job_title=job_title,
            )
            if default_location is not None:
                created_loc = _ensure_membership_location(
                    membership=membership, location=default_location,
                )
                if created_loc:
                    report.locations_assigned += 1
        except IntegrityError as e:
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.email}: {e}'[:300])
            logger.warning(
                'imports.zenoti.employees.row_db_error',
                extra={'email_domain': mapped.email.split('@')[-1], 'error': str(e)[:200]},
            )
            continue
        except Exception as e:  # noqa: BLE001
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.email}: {type(e).__name__}: {e}'[:300])
            logger.exception(
                'imports.zenoti.employees.row_unexpected_error',
                extra={'email_domain': mapped.email.split('@')[-1]},
            )
            continue

        if user_created:
            report.users_created += 1
        else:
            report.users_reused += 1
        if membership_created:
            report.memberships_created += 1
        else:
            report.memberships_reused += 1

        audit_record(
            action=AuditLog.Action.CREATE if membership_created else AuditLog.Action.UPDATE,
            resource_type='tenant_membership',
            resource_id=membership.id,
            user=actor,
            tenant=tenant,
            metadata={
                'source': 'zenoti_import',
                'zenoti_code': mapped.zenoti_code,
                'role': mapped.role,
                'is_bookable': mapped.is_bookable,
                'job_title': mapped.job_title_name,
                'upstream_center': mapped.upstream_center,
                # Domain-only — never log full email addresses in audit
                # metadata; consistent with the marketing send-log
                # PHI-light posture.
                'email_domain': mapped.email.split('@')[-1],
            },
        )

    audit_record(
        action=AuditLog.Action.CREATE,
        resource_type='zenoti_employees_import_run',
        user=actor,
        tenant=tenant,
        metadata=report.to_summary_dict(),
    )

    return report


# ── Helpers ────────────────────────────────────────────────────────


def _upsert_user(mapped: MappedEmployee) -> tuple[User, bool]:
    """Find-or-create a User by email.

    Existing users keep their name + phone (we don't clobber a real
    person's profile because Zenoti happens to know their email).
    Only the password is set for brand-new users — to an unusable
    placeholder; the operator triggers the staff invitation flow
    (ADR 0019) when they actually want the employee to log in.
    """
    existing = User.objects.filter(email__iexact=mapped.email).first()
    if existing is not None:
        return existing, False
    # Placeholder password — random + unusable in practice. Forces
    # an explicit invitation / password-reset (ADR 0019) before the
    # imported employee can actually log in. `make_random_password`
    # was removed from UserManager in Django 5.0 — use `secrets`
    # directly.
    user = User.objects.create_user(
        email=mapped.email,
        first_name=mapped.first_name,
        last_name=mapped.last_name,
        password=secrets.token_urlsafe(24),
    )
    if mapped.phone:
        user.phone = mapped.phone
        user.save(update_fields=['phone'])
    return user, True


def _resolve_job_title(
    *, tenant: Tenant, name: str,
    cache: dict[str, JobTitle], report: EmployeesImportReport,
) -> JobTitle | None:
    """Find-or-create a JobTitle for this tenant.

    Returns None for blank names. JobTitle is per-tenant
    (unique_together = (tenant, name)), so this is a safe upsert.
    """
    if not name:
        return None
    cached = cache.get(name)
    if cached is not None:
        return cached
    jt, created = JobTitle.objects.get_or_create(tenant=tenant, name=name)
    if created:
        report.job_titles_created += 1
    cache[name] = jt
    return jt


def _upsert_membership(
    *,
    tenant: Tenant, user: User, mapped: MappedEmployee,
    job_title: JobTitle | None,
) -> tuple[TenantMembership, bool]:
    """Find-or-create the (tenant, user) membership.

    Updates non-identifier fields on every run so re-imports
    propagate JOB / hire date / pay changes from Zenoti.
    """
    with transaction.atomic():
        existing = TenantMembership.objects.filter(tenant=tenant, user=user).first()
        defaults = dict(
            role=mapped.role,
            is_bookable=mapped.is_bookable,
            is_active=mapped.is_active,
            job_title=job_title,
            hire_date=mapped.hire_date,
            pay_rate_cents=mapped.pay_rate_cents,
            pay_type=mapped.pay_type,
        )
        if existing is not None:
            for k, v in defaults.items():
                setattr(existing, k, v)
            existing.save()
            return existing, False
        membership = TenantMembership.objects.create(
            tenant=tenant, user=user, **defaults,
        )
        return membership, True


def _ensure_membership_location(
    *, membership: TenantMembership, location: Location,
) -> bool:
    """Assign the membership to the tenant's default location.

    Idempotent — if the assignment already exists, reactivate it
    (covers the operator-removed-then-re-imported case).
    """
    existing = MembershipLocation.objects.filter(
        membership=membership, location=location,
    ).first()
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            existing.save(update_fields=['is_active'])
        return False
    MembershipLocation.objects.create(
        membership=membership, location=location, is_active=True,
    )
    return True
