# Lumè backend

Django 5.1 + DRF + Celery (Celery comes online when we add Phase 1 features that need background work — SMS, email, scheduled reminders).

## Prerequisites

- Python 3.12 (`brew install python@3.12`)
- Postgres 16 (`brew install postgresql@16` + `brew services start postgresql@16`)
- A local Postgres database called `lume_crm_dev` (created via `createdb lume_crm_dev`)

## First-time setup

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env       # then fill in SECRET_KEY (generate with manage.py shell)
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
```

## Running

```bash
.venv/bin/python manage.py runserver       # → http://127.0.0.1:8000
```

- **Django admin:** [/admin/](http://127.0.0.1:8000/admin/) — internal back-office, generic styling intentional, never customer-facing.
- **API docs:** [/api/docs/](http://127.0.0.1:8000/api/docs/) — auto-generated Swagger.

## Project structure

```
backend/
├── lume_crm/                Django project config
│   ├── settings.py          Reads .env via django-environ
│   ├── urls.py              Mounts /admin/, /api/auth/, /api/docs/
│   └── wsgi.py / asgi.py
├── apps/                    Each subdirectory is a Django app
│   ├── __init__.py          (apps/ is a Python package)
│   ├── users/               Custom User model + auth API endpoints
│   ├── tenants/             Multi-tenancy primitives — see apps/tenants/README.md
│   └── audit/               HIPAA-aligned append-only audit log
├── manage.py
└── requirements.txt
```

## Conventions

- **Apps are namespaced under `apps/`.** New app: `cd backend/apps && ../.venv/bin/python ../manage.py startapp NAME`. Then edit `apps.py` to set `name = 'apps.NAME'` and `label = 'NAME'`.
- **Every PHI table inherits from `apps.tenants.abstract_models.TenantedModel`.** This forces a `tenant` FK and gives you a `.objects.for_current_tenant()` queryset method. See [apps/tenants/README.md](apps/tenants/README.md).
- **Tenant scoping is read via `apps.tenants.context.get_current_tenant()`.** Set per-request by `TenantMiddleware`. Set explicitly via `tenant_context(tenant)` in scripts and tests.
- **Audit any non-trivial PHI access** by calling `apps.audit.services.record(...)` from the view. Login/logout are already wired via signals.
- **Module docstrings on every file.** Public class/function docstrings. See [the documentation discipline](../README.md#documentation-discipline) in the root README.

## Common commands

```bash
.venv/bin/python manage.py shell                                 # Django shell
.venv/bin/python manage.py makemigrations APP && \
  .venv/bin/python manage.py migrate                              # New migration
.venv/bin/python manage.py createsuperuser                        # New superuser
/opt/homebrew/opt/postgresql@16/bin/psql lume_crm_dev             # raw DB
```

## Env vars (`.env`)

| Var | Purpose |
|---|---|
| `SECRET_KEY` | Django session/CSRF signing — required |
| `DEBUG` | `True` for local dev, `False` in production |
| `ALLOWED_HOSTS` | Comma-separated hostnames Django will accept |
| `DATABASE_URL` | `postgres://USER@HOST:PORT/DB` — read by django-environ |

`.env` is gitignored. `.env.example` is committed as a template.
