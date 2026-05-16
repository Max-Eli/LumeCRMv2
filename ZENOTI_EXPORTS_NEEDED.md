# Zenoti exports needed for Lumè migration

Drop each export into this same folder (next to `Guests.csv`) when ready.

For every report below, choose:
- **Centers**: `All` (we'll merge Florida + Midtown + Brooklyn into the single Florida location in Lumè)
- **Date range**: widest possible (covers all historical data)
- **Format**: `CSV` (Excel works too if CSV isn't offered)

Run each report at the **organization level** so all centers come in one file.

---

## 1. Guest List with Email — `Guests_with_Email.csv`

The `Guests.csv` already provided is missing emails, DOB, and addresses. Re-export from Guest Manager (not from Reports):

**Path:** Guest Manager → filter/segment shows all guests → **Export** button → choose CSV

This produces a file commonly called `User Report.xls/csv` and includes name, email, mobile, DOB, address, loyalty tier, and the guest code.

> The user account doing the export needs the **"Export Guests List"** permission. If the button is greyed out, the spa owner can grant it under Configuration → Security.

---

## 2. Active Memberships with remaining balance — `Memberships.csv`

**Path:** Reports → Marketing → Memberships → **Memberships Report (v2)**

- Filter: **Status = Active** (we don't need expired/cancelled)
- Date range: widest available
- Export: CSV

This gives us per-guest membership name, **remaining credit balance**, expiration date, and frozen/active status.

## 2b. Membership sale prices — `Membership_Sales.csv`

**Path:** Reports → Finance → Sales → **Sales - Membership**

- Date range: widest available (covers every membership ever sold)
- Export: CSV

We need this to know the original sale price of each membership — the status report doesn't include it.

---

## 3. Packages with remaining sessions — `Package_Status.csv`

**Path:** Reports → Marketing → Packages → **Package Status Report**

- Filter: **Status = Active / Open** (skip closed/expired)
- Date range: widest available
- Export: CSV

Gives per-guest package name, **remaining sessions or remaining value**, expiration date, and the category.

## 3b. Package sale prices + custom packages — `Package_Sales.csv`

**Path:** Reports → Finance → Sales → **Sales - Package**

- Date range: widest available
- Export: CSV

This is where **custom (per-guest) packages** show up alongside the catalog ones, with the actual sale amount paid.

---

## 4. Appointment history — `Appointments.csv`

**Path:** Reports → Operational → Appointments → **Appointments Report (v2)**

- Centers: All
- Appointment Status: **All** (include completed, no-shows, cancellations)
- Date range: from the earliest available date → today
- Export: CSV

Gives guest name, service, date/time, provider, status, and invoice total.

> If the file is too large to export in one shot, Zenoti will email it; or split it by year and export `Appointments_2023.csv`, `Appointments_2024.csv`, etc.

---

## Summary checklist

When you drop these into the project folder, we have everything:

- [ ] `Guests_with_Email.csv` — replaces the existing `Guests.csv`
- [ ] `Memberships.csv` — active memberships with remaining credits
- [ ] `Membership_Sales.csv` — original sale prices
- [ ] `Package_Status.csv` — packages with remaining sessions
- [ ] `Package_Sales.csv` — sale prices + custom packages
- [ ] `Appointments.csv` — full appointment history

Once they're here I'll build the CSV importer, run a dry-run to show you a reconciliation (X guests, Y memberships, Z appointments matched), and we commit when the numbers look right.
