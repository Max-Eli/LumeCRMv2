# Zenoti tenant import (prod)

Run a Zenoti CSV migration into a prod tenant. Used for onboarding a new spa
that's switching from Zenoti — services, employees, customers, packages,
memberships, appointments.

**Stakes.** This is one of the riskiest operational tasks we run. It writes
thousands of rows directly into the prod RDS. Each importer is idempotent
(re-runs match by `external_id` and update in place), so a failed mid-run is
recoverable — but bad mappings still create bad data that you'll spend hours
unwinding. Read this top to bottom before you start.

**Time:** ~30 min for a small spa (≤2,000 customers, ≤1,000 appointments).
~60 min for Manhattan-sized.

## Preconditions

- [ ] Tenant row exists in prod (`Tenant.objects.create(slug='…', name='…')`
  if not). Includes a default `Location`.
- [ ] All CSV exports from Zenoti are in hand:
  - `serviceswithprices.csv` (NOT `Services.csv` — we need the price columns)
  - `Employees.csv` (use the export with `IsActive` column)
  - `ZenotiActiveGuest.csv`
  - `Packages*.csv` — one file per date range; Zenoti caps each export at
    11 months. Combine all of them.
  - `Memberships*.csv` — same date-range caveat as packages.
  - `appointments*.csv` — one or more files, full date range.
- [ ] CSVs uploaded to `s3://lume-prod-media-<acct>/imports/<tenant-slug>/`.
- [ ] AWS CLI configured with prod profile + `session-manager-plugin` installed
  (`brew install --cask session-manager-plugin` if not).
- [ ] Recent RDS snapshot. If you don't have one in the last hour, create
  one in the console (free, 30 seconds) before you start.

## Step 1 — Open an ECS exec shell into a backend task

```bash
# Pick any running backend task.
TASK_ARN=$(aws ecs list-tasks \
  --cluster lume-prod-cluster \
  --service-name lume-prod-backend \
  --query 'taskArns[0]' \
  --output text)

aws ecs execute-command \
  --cluster lume-prod-cluster \
  --task "$TASK_ARN" \
  --container backend \
  --interactive \
  --command "/bin/sh"
```

Inside the shell, export the DB URL so `manage.py` can talk to RDS:

```sh
export DATABASE_URL="postgres://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
```

## Step 2 — Confirm migrations are current

The importers reference columns added in recent migrations (e.g.
`PurchasedPackage.external_id`). If migrations are behind, every package
insert raises `ProgrammingError: column does not exist`.

```sh
python manage.py showmigrations | grep '\[ \]' || echo "All caught up."
```

If anything shows as unapplied, run it:

```sh
python manage.py migrate
```

The CI workflow `backend-deploy.yml` does this automatically on every push to
`main` — but if the deploy that introduced the migration hasn't run yet
(or failed), the table won't have the column.

## Step 3 — Stream CSVs from S3 (in order, idempotent)

Order matters. Services + employees + customers MUST be in place before
packages / memberships / appointments. Order within each step doesn't.

```sh
TENANT=manhattan-laser-spa  # change per onboard
BUCKET=lume-prod-media-<acct>

# 1. Services + categories (creates Service rows; no FKs to anything else).
python manage.py import_zenoti_services \
  --tenant "$TENANT" \
  --s3-uri "s3://$BUCKET/imports/$TENANT/serviceswithprices.csv"

# 2. Employees (creates User + TenantMembership rows).
python manage.py import_zenoti_employees \
  --tenant "$TENANT" \
  --s3-uri "s3://$BUCKET/imports/$TENANT/Employees.csv"

# 3. Customers / guests (creates Customer rows).
python manage.py import_zenoti_guests \
  --tenant "$TENANT" \
  --s3-uri "s3://$BUCKET/imports/$TENANT/ZenotiActiveGuest.csv"

# 4. Packages (FKs to Customer + Service). One file per date range.
for f in Packages01:01:24-11:30:24.csv Packages01:01:25-11:30:25.csv \
         Packages12:01:24-12:31:24.csv Packages12:01:25-05:16:26.csv; do
  python manage.py import_zenoti_packages \
    --tenant "$TENANT" \
    --s3-uri "s3://$BUCKET/imports/$TENANT/$f"
done

# 5. Memberships (FKs to Customer + Service). Same file-per-range pattern.
for f in Memberships01:01:22-11:30:22.csv Memberships01:01:23-11:30:23.csv \
         Memberships01:01:24-11:30:24.csv Memberships01:01:25-11:30:25.csv \
         Memberships12:01:22-12:31:22.csv Memberships12:01:23-12:31:23.csv \
         Memberships12:01:24-12:31:24.csv Memberships12:01:25-05:16:26.csv; do
  python manage.py import_zenoti_memberships \
    --tenant "$TENANT" \
    --s3-uri "s3://$BUCKET/imports/$TENANT/$f"
done

# 6. Appointments (FKs to Customer + Service + Provider). Auto-creates
#    placeholder customers for any guest that wasn't in step 3.
python manage.py import_zenoti_appointments \
  --tenant "$TENANT" \
  --s3-uri "s3://$BUCKET/imports/$TENANT/appointments2026.csv"
```

Each importer prints a reconciliation report at the end:

- `rows_created`, `rows_updated` — the meaningful numbers
- `rows_failed_mapping` / `db_error_count` — should be 0; if not, stop and
  read the listed errors
- `customer_miss_count` — packages / memberships skipped because the
  customer wasn't in the active-guests file (handled in step 4)

## Step 4 — Customer recovery for missing-customer packages

Packages and memberships are pinned to invoices that name a guest. When that
guest wasn't in the active-guests export (deleted / departed clients with
old balances), the package importer skips the row. We can recover by
auto-creating placeholder customers from the same CSVs.

Inside the same ECS shell:

```sh
python manage.py shell <<'PYEOF'
import csv, re
from pathlib import Path
from django.utils import timezone
from apps.tenants.models import Tenant
from apps.customers.models import Customer
from apps.imports.zenoti.packages_mapper import _split_guest_name, _clean

tenant = Tenant.objects.get(slug='manhattan-laser-spa')
csv_paths = sorted(Path('/tmp').glob('Packages*.csv'))  # adjust if CSVs are elsewhere

existing = {}
for c in Customer.objects.filter(tenant=tenant).only('id', 'first_name', 'last_name'):
    existing.setdefault((c.first_name.lower(), c.last_name.lower()), c)

missing = {}
for f in csv_paths:
    with f.open(newline='', encoding='utf-8-sig') as fp:
        for row in csv.DictReader(fp):
            invoice = _clean(row.get('Invoice No', ''))
            guest = _clean(row.get('Guest Name', ''))
            if not invoice or not guest:
                continue
            first, last = _split_guest_name(guest)
            key = (first.lower(), last.lower())
            if key in existing:
                continue
            # last-name-only fallback mirrors importer policy
            same_last = [k for k in existing if k[1] == last.lower()]
            if len(same_last) == 1:
                continue
            missing.setdefault(key, (first, last, invoice))

created = 0
for (fl, ll), (first, last, invoice) in missing.items():
    slug = re.sub(r'[^a-z0-9]+', '-', f'{first} {last}'.lower()).strip('-') or 'unknown'
    eid = f'zenoti-pkg-placeholder:{slug}'[:100]
    if Customer.objects.filter(
        tenant=tenant, external_source='zenoti', external_id=eid,
    ).exists():
        continue
    Customer.objects.create(
        tenant=tenant,
        first_name=first[:100] or 'Unknown',
        last_name=last[:100],
        external_source='zenoti',
        external_id=eid,
        acquisition_source=Customer.AcquisitionSource.ZENOTI_IMPORT,
        imported_at=timezone.now(),
        notes=f'Auto-created by Zenoti package import recovery — original guest missing from ZenotiActiveGuest.csv. Source invoice: {invoice}',
    )
    created += 1
print(f'Placeholder customers created: {created}')
PYEOF
```

Then re-run the packages importer (and memberships if it had any
`NoCustomer` rows). It's idempotent — already-created packages get
`Updated` rather than duplicated, and the newly-placeholder-backed ones
finally land:

```sh
for f in Packages01:01:24-11:30:24.csv ...; do
  python manage.py import_zenoti_packages --tenant "$TENANT" --s3-uri "s3://$BUCKET/imports/$TENANT/$f"
done
```

Look for `NoCustomer=0` across all four files. That confirms recovery is
complete.

## Step 5 — Verify

```sh
python manage.py shell <<'EOF'
from apps.tenants.models import Tenant
from apps.customers.models import Customer
from apps.services.models import Service
from apps.tenants.models import TenantMembership
from apps.appointments.models import Appointment
from apps.packages.models import PurchasedPackage
from apps.memberships.models import Subscription

t = Tenant.objects.get(slug='manhattan-laser-spa')
print(f'Customers:    {Customer.objects.filter(tenant=t).count():>6,}')
print(f'Services:     {Service.objects.filter(tenant=t).count():>6,}')
print(f'Staff:        {TenantMembership.objects.filter(tenant=t).count():>6,}')
print(f'Packages:     {PurchasedPackage.objects.filter(tenant=t).count():>6,}')
print(f'Memberships:  {Subscription.objects.filter(tenant=t).count():>6,}')
print(f'Appointments: {Appointment.objects.filter(tenant=t).count():>6,}')
EOF
```

Reference counts from the demo run for Manhattan (May 19, 2026):

| Table | Expected |
|---|---|
| Customers | ~7,474 (active + placeholders) |
| Services | 328 |
| Staff | 17 |
| Packages | 1,675 |
| Memberships | 2,226 |
| Appointments | 2,150 (650 dropped — see "Known data gaps") |

## Step 6 — Confirm SMS is still suppressed

The appointments importer marks `source = 'zenoti_import'`, which the
`SuppressAutomatedSMS` signal handler in `apps/appointments/signals.py`
checks before sending. Verify the safety:

```sh
# Should print 0 — no migration-imported appointment should be in a
# pending-SMS state.
python manage.py shell <<'EOF'
from apps.appointments.models import Appointment
qs = Appointment.objects.filter(source__endswith='_import')
print(f'Imported appointments: {qs.count()}')
print(f'With null reminder_sent_at: {qs.filter(reminder_sent_at__isnull=True).count()}')
EOF
```

Both numbers should be the same (the importer pre-fills `reminder_sent_at`
and `confirmation_sent_at` to NOW on insert so even if a code path tries to
send, the schedule sees "already sent" and skips).

If those numbers diverge, **stop and ask before re-enabling EventBridge**.

## Known data gaps

These come up on every Zenoti onboard. None require runbook changes; just
note them on the kickoff call with the spa.

- **Customer-match misses on packages / memberships.** Guests that were in
  Zenoti's old data but not the active-guests export. Step 4 recovers them
  by creating placeholders.
- **Service-match misses on appointments.** Services that the spa added in
  Zenoti but didn't export in the services CSV. Common offenders: nail
  services (mani / pedi / gel) at a spa whose main service catalog is
  injectables. Fix: add the missing services in the Lumè UI, then re-run
  `import_zenoti_appointments` — idempotent.
- **Unmatched service names on package items.** Same root cause. The
  package still imports, but the line item is `service=NULL`. Per
  [ADR 0030](../decisions/0030-zenoti-customer-importer.md), the snapshot
  name is preserved so the operator can see what was on the original
  package.

## Rollback

Since every import is idempotent and the row counts climb monotonically, an
abort mid-run is recoverable by re-running the failed importer. A full
"undo" requires a DB restore from the snapshot you took in step 0.
