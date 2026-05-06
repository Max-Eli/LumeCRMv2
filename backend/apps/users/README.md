# apps.users

Custom `User` model + auth API endpoints.

## What's in here

- **[models.py](models.py)** — `User` extending `AbstractUser` with email-as-username, no `username` field. `UserManager` adapts Django's default manager for the missing username.
- **[views.py](views.py)** — DRF auth API: `LoginView`, `LogoutView`, `MeView`, `CSRFView`. Mounted at `/api/auth/`.
- **[urls.py](urls.py)** — URL patterns for the auth views.
- **[admin.py](admin.py)** — `UserAdmin` registered in Django admin with email-aware fieldsets.

## Why a custom User model

Django's default `User` uses `username` as the login key. We use email. Switching after users exist is painful (data migration + every FK update), so the model was customized on day one.

Tenant-scoped role and permissions are NOT on this model — see [apps/tenants](../tenants/) for `TenantMembership`. A user can belong to multiple tenants with different roles per tenant.

## Auth endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/auth/csrf/` | Sets the `csrftoken` cookie. Frontend hits this once before any login attempt. |
| `POST` | `/api/auth/login/` | `{ email, password }` → 200 `{ user }` on success, 401 on bad credentials. |
| `POST` | `/api/auth/logout/` | Clears session. Returns 204. |
| `GET` | `/api/auth/me/` | Returns `{ user }` with memberships, or 403 if not authenticated. |

Auth backend: Django's session framework + DRF `SessionAuthentication`. CSRF is enforced on POST/PUT/PATCH/DELETE.

Audit log entries for `login`, `logout`, and `login_failed` are recorded automatically — see [apps/audit/signals.py](../audit/signals.py).

## Adding a user manually (dev)

```bash
.venv/bin/python manage.py shell -c "
from apps.users.models import User
User.objects.create_user(email='alice@example.com', password='temp-password-123!', first_name='Alice')
"
```

For a tenant-scoped user, use [`apps.tenants.services.create_tenant_with_defaults`](../tenants/services.py) (which creates the user's first Owner membership) or create a `TenantMembership` directly in the admin.
