# apps.customers

The first PHI-bearing app — patient/client records, addresses, medical history, and tags. The pattern established here (model + permissions + serializer + viewset + audit logging) is the template every future PHI feature follows.

## What's in here

- **[models.py](models.py)** — `Customer` (extends `TenantedModel`), `CustomerTag` (per-tenant tag list, M2M to Customer).
- **[permissions.py](permissions.py)** — `CustomerPermission` maps DRF actions to Lumè permission identifiers.
- **[serializers.py](serializers.py)** — `CustomerListSerializer` (no PHI), `CustomerDetailSerializer` (full PHI), `CustomerTagSerializer`.
- **[views.py](views.py)** — `CustomerViewSet` (`ModelViewSet`) with audit logging on every action.
- **[urls.py](urls.py)** — DRF router registering the viewset under `/api/customers/`.
- **[admin.py](admin.py)** — Django admin with grouped fieldsets (Identity, Demographics, Address, Emergency, Medical, etc.).

## API endpoints

| Method | Path | Required permission | Notes |
|---|---|---|---|
| `GET` | `/api/customers/` | `VIEW_CLIENT_LIST` | Search via `?q=` (name, email, phone), filter via `?status=` |
| `POST` | `/api/customers/` | `EDIT_CLIENT_RECORD` | Tenant set automatically from request context |
| `GET` | `/api/customers/{id}/` | `VIEW_CLIENT_LIST` | Returns full PHI (medical history, allergies, etc.) |
| `PATCH` / `PUT` | `/api/customers/{id}/` | `EDIT_CLIENT_RECORD` | |
| `DELETE` | `/api/customers/{id}/` | `DELETE_CLIENT_RECORD` | |

Every action records an `AuditLog` entry. Reads of individual customers log `read customer:{id}`. List calls log `read customer_list` with the search query and result count in metadata. Create / update / delete log the same with `fields_changed` metadata where relevant.

## Customer model field groups

- **Identity:** `first_name`, `last_name`, `preferred_name`, `email`, `phone`
- **Demographics (PHI):** `date_of_birth`, `sex`
- **Address (PHI):** `address_line1`, `address_line2`, `city`, `state`, `zip_code`
- **Emergency contact:** `emergency_name`, `emergency_phone`, `emergency_relationship`
- **Medical (PHI):** `medical_history`, `allergies`, `medications`, `skin_type_fitzpatrick`
- **CRM:** `notes`, `referral_source`
- **Marketing prefs:** `email_opt_in`, `sms_opt_in`
- **Status + tags:** `status`, `tags` (M2M to `CustomerTag`)
- **Provenance (Zenoti migration):** `external_id`, `external_source`, `imported_at`
- **Timestamps:** `created_at`, `updated_at`

Only `first_name`, `last_name`, and `tenant` are required. Walk-ins with partial info can still be saved.

## Provenance

The `external_id` field is indexed per tenant. The Zenoti importer (Phase 1J) will write Zenoti's customer ID here on import and use it as the upsert key on re-runs, so importing the same CSV twice doesn't create duplicates.

## Tags

Tags are tenant-scoped — each tenant defines its own tag list in the admin. Tags are display-only (color + name) and DO NOT grant or restrict permissions.

## What's NOT here yet

- **PHI field hiding for users without `VIEW_CLIENT_PHI`.** Currently the `CustomerDetailSerializer` returns medical fields to anyone with `VIEW_CLIENT_LIST`. Hardening to drop PHI fields when the user lacks `VIEW_CLIENT_PHI` is on the Phase 1A.1 list.
- **Customer notes (provider-only, internal).** Separate model coming with the chart system in Phase 4.
- **Photo / file attachments.** Wait for S3 in Phase 0c.

## Patterns to copy when building the next PHI feature

1. Model inherits from `TenantedModel` (auto `tenant` FK).
2. Add `tenant`-aware indexes (queries always filter by tenant, so prefix every index with it).
3. Two serializers — one minimal for list, one full for detail.
4. Permission class mapping actions → permission strings from `apps.tenants.permissions.P`.
5. ViewSet with audit logging in `list`, `retrieve`, `perform_create`, `perform_update`, `perform_destroy`.
6. Register URLs via `DefaultRouter`, mount under `/api/`.
7. Admin with grouped fieldsets and `autocomplete_fields = ('tenant', ...)`.

See [ADR 0001](../../../docs/decisions/0001-multi-tenancy-strategy.md) for the multi-tenancy rationale and [ADR 0003](../../../docs/decisions/0003-permission-model.md) for the permission model.
