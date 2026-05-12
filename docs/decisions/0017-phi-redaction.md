# ADR 0017 — PHI field redaction on the customer endpoint (Phase 1A.1 hardening)

## Status

Accepted (2026-05-12).

## Context

The `Customer` model has been the system's first and largest PHI-bearing surface since Phase 1A landed (2026-04-30). The original implementation gated `/api/customers/` actions through `CustomerPermission`, which checked one of three coarse permissions per action:

- `VIEW_CLIENT_LIST` for list + retrieve
- `EDIT_CLIENT_RECORD` for create + update
- `DELETE_CLIENT_RECORD` for delete

That gate is correct at the **action** level — a marketing user can browse customers, a front-desk user can edit a phone number — but it doesn't distinguish between **PHI** fields (medical history, allergies, DOB, address, emergency contact, Fitzpatrick) and **non-PHI** fields (name, email, phone, tags, marketing consent). Any user holding `VIEW_CLIENT_LIST` could retrieve the full record. That violates HIPAA's minimum-necessary rule (45 CFR 164.502(b)) — a front-desk worker booking an appointment does not need to read the customer's medications.

The permission catalog in [apps/tenants/permissions.py](../../backend/apps/tenants/permissions.py) has had `VIEW_CLIENT_PHI` defined since the catalog was first sketched, but it was unenforced on the customer endpoint. This ADR closes that gap.

### HIPAA + SOC 2 framing

HIPAA's minimum-necessary rule requires covered entities and business associates to limit PHI access to what's needed for each role's job function. A front-desk staffer at a medspa needs:

- Customer's name (to greet them by name)
- Email + phone (to call/text about bookings)
- Status (active / inactive)
- Marketing opt-in (when running campaigns)
- Tags (for booking + service routing)

They **do not** need:

- Date of birth (a HIPAA identifier per 45 CFR 164.514(b)(2)(i)(C))
- Address fields (HIPAA identifier per (b)(2)(i)(B))
- Emergency contact (third-party PHI)
- Medical history, allergies, medications, Fitzpatrick skin type (clinical PHI)
- Free-text general notes (commonly contains clinical impressions)

Providers, managers, and owners hold `VIEW_CLIENT_PHI` and see the full record. The matrix is:

| Role         | `VIEW_CLIENT_LIST` | `VIEW_CLIENT_PHI` | Sees PHI fields? |
|--------------|--------------------|--------------------|------------------|
| owner        | yes                | yes                | yes              |
| manager      | yes                | yes                | yes              |
| provider     | yes                | yes                | yes              |
| front_desk   | yes                | no                 | **redacted**     |
| marketing    | yes                | no                 | **redacted**     |
| bookkeeper   | no                 | no                 | n/a (no access)  |

SOC 2 CC6.1 (Logical Access — Restrict Access to Information Assets to Authorized Users) maps to the same control: access decisions are role-based, enforced at the API boundary, and audit-logged on every read.

## Decision

**The `CustomerDetailSerializer` redacts a fixed set of PHI fields when the requesting user's `TenantMembership` does not hold `VIEW_CLIENT_PHI`.**

The redaction is implemented in three places, each acting as defense in depth:

### 1. Read path — omit fields from response

`CustomerDetailSerializer.to_representation` checks `request.tenant_membership.has(P.VIEW_CLIENT_PHI)` and removes the redacted fields from the serialized dict when the permission is missing. Fields are **omitted entirely** (the key is absent from the JSON response), not nulled. Frontend code that conditionally renders sections sees `undefined` and renders the redacted-banner state; legacy code that reads `customer.medical_history` directly would see `undefined` rather than a misleading empty string.

The redacted set (`PHI_FIELDS` constant in `apps/customers/serializers.py`):

- `date_of_birth`, `sex`
- `address_line1`, `address_line2`, `city`, `state`, `zip_code`
- `emergency_name`, `emergency_phone`, `emergency_relationship`
- `medical_history`, `allergies`, `medications`, `skin_type_fitzpatrick`
- `notes` (free-text; routinely contains clinical impressions)

**Not redacted** (deliberately): `email`, `phone`. These are HIPAA identifiers in the abstract, but front-desk staff need them for legitimate operational reasons (calling a customer about a no-show, emailing a reschedule). Treating them as PHI here would break the role's job function. They remain audit-logged on every access; that's the SOC 2 compensating control.

### 2. Write path — reject PHI writes for non-PHI roles

`CustomerDetailSerializer.validate` checks the same permission. If a non-PHI user sends a `PATCH` containing any field in `PHI_FIELDS`, the **entire request is rejected** with HTTP 400 and a per-field error. Atomicity is intentional: silently dropping the PHI field while writing the rest would mean a front-desk user could submit `{phone: '555-9999', medical_history: ''}` and have the phone update succeed while the medical history is silently blocked — a leak about the gate's existence with no clear UX signal. Rejecting atomically surfaces the boundary.

### 3. Frontend — hide PHI sections in the UI

The customer detail page (`frontend/src/app/(app)/clients/[id]/page.tsx`) renders both the Overview tab (read view) and the Profile tab (edit form). Both check `canViewClientPHI(membership.role)` and conditionally render the PHI sections. When redaction applies, a `PhiRedactedBanner` component renders in place of the hidden sections, explicitly naming the rule ("HIPAA minimum-necessary access — by design"). The frontend gate is **purely UX**; the server is the security boundary.

The form's `onSubmit` further strips PHI keys from the payload when the user lacks the permission, to avoid the user seeing a 400 on a save they thought was for a non-PHI change (e.g., updating the phone number).

## Consequences

### Positive

- Front-desk and marketing roles are now correctly gated for PHI access — closing the open Phase 1A.1 hardening item and making the customer endpoint defensible in a HIPAA audit.
- The pattern (PHI_FIELDS constant + `to_representation` + `validate`) is reusable. The forms app already references `VIEW_CLIENT_PHI` and can adopt the same pattern when its serializer-level redaction lands.
- Frontend banner explicitly names the rule, so staff don't think there's a bug — they see "your role doesn't include PHI access" and can ask their owner if it's a misclassification.
- 8 tests in `apps/customers/tests.py` cover both halves: owner/provider see PHI, front-desk/marketing don't; PHI writes from non-PHI roles are rejected atomically with no partial writes.

### Negative

- One more place where the frontend-side role map must stay in sync with the backend `ROLE_DEFAULTS`. We mitigate via a comment on `canViewClientPHI` and the same on `canViewCharts` (the existing precedent). A future investment could be a generated TypeScript file produced from `apps/tenants/permissions.py`, but that's premature today (one role-gate file per domain is manageable).
- A spa owner who modifies role permissions via the `extra_permissions` / `revoked_permissions` mechanism on a `TenantMembership` (granting `VIEW_CLIENT_PHI` to a specific front-desk user) sees the backend honor the grant immediately, but the frontend role-based gate would still hide the sections in the UI — because the frontend check is `role`-based, not `effective-permission`-based. This is a known limitation. A follow-up is to surface the effective-permission set in the `/auth/me` payload and gate on that. For now, the documented escape hatch is to promote the user to `provider` if they need clinical access.
- Redacted fields are absent from the response JSON. Older frontend code paths that destructure `customer.medical_history` would see `undefined`. We checked and the existing read view (lines 320-393 of `page.tsx`) gracefully handles undefined; the edit form does not render PHI inputs at all under the gate.

### Risks accepted

- Email and phone are not redacted. If a future audit surfaces a need to redact them too (e.g., a spa serves high-risk clients where the phone number itself is sensitive), we add them to `PHI_FIELDS` — a one-line change. The current omission is documented and justified.
- The redaction is applied per-role on the FRONTEND. A determined adversary running the app from devtools could not see the PHI (server omits the keys) but might be able to extract the fact that PHI exists for a given customer. We treat this as acceptable — knowing a customer is on file is not PHI.

## Implementation references

- Serializer constant + redaction logic: [apps/customers/serializers.py](../../backend/apps/customers/serializers.py)
- Tests: [apps/customers/tests.py](../../backend/apps/customers/tests.py) — `CustomerPHIRedactionTests`
- Frontend gate: [frontend/src/lib/customers.ts](../../frontend/src/lib/customers.ts) — `canViewClientPHI`
- Frontend UI: [frontend/src/app/(app)/clients/[id]/page.tsx](../../frontend/src/app/(app)/clients/[id]/page.tsx) — `PhiRedactedBanner`, `OverviewTab`, `ProfileTab`
- Permission catalog: [apps/tenants/permissions.py](../../backend/apps/tenants/permissions.py) — `VIEW_CLIENT_PHI`
