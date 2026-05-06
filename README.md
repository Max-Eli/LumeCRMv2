# Lumè CRM

A modern, HIPAA-compliant, multi-tenant CRM for medical spas and salons. Booking, customer charts, e-signed forms, payments, memberships, marketing — built to compete with Zenoti, Boulevard, Vagaro, and Podium.

## Repo layout

```
LumèCRM/
├── PROJECT_PLAN.md          The roadmap. Always current. Start here.
├── docs/                    Architecture decision records and design notes
│   └── decisions/           ADRs (Michael Nygard format)
├── backend/                 Django 5 + DRF API
│   ├── manage.py
│   ├── lume_crm/            project config (settings, urls)
│   ├── apps/                domain apps — each is a Django app
│   │   ├── users/           custom User model
│   │   ├── tenants/         multi-tenancy (Tenant, JobTitle, TenantMembership), permissions, middleware
│   │   └── audit/           HIPAA-aligned append-only audit log
│   └── requirements.txt
└── frontend/                Next.js 16 + React 19 + Tailwind v4 + shadcn/ui
    └── src/
        ├── app/             App Router routes — (auth) for login, (app) for authenticated app
        ├── components/ui/   shadcn primitives (base-nova style — uses Base UI, not Radix)
        └── lib/             API client, auth hooks
```

## Quick start

You need Python 3.12, Postgres 16, and Node 22+ installed. The backend assumes a local Postgres database called `lume_crm_dev`.

```bash
# Backend
cd backend
.venv/bin/python manage.py runserver           # → http://127.0.0.1:8000

# Frontend (separate terminal)
cd frontend
npm run dev                                    # → http://localhost:3000
```

Detailed setup is in [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md).

## API documentation

When the backend is running, visit:

- **[/api/docs/](http://127.0.0.1:8000/api/docs/)** — Swagger UI
- **[/api/redoc/](http://127.0.0.1:8000/api/redoc/)** — ReDoc
- **[/api/schema/](http://127.0.0.1:8000/api/schema/)** — raw OpenAPI YAML

These are auto-generated from DRF view docstrings via `drf-spectacular`. Don't edit by hand.

## Architecture

Read the [ADRs](docs/decisions/) for the why behind each major decision:

- [0001 — Multi-tenancy strategy](docs/decisions/0001-multi-tenancy-strategy.md)
- [0002 — Authentication strategy](docs/decisions/0002-authentication-strategy.md)
- [0003 — Permission model](docs/decisions/0003-permission-model.md)
- [0004 — Audit logging](docs/decisions/0004-audit-logging.md)
- [0005 — Frontend stack](docs/decisions/0005-frontend-stack.md)

## Documentation discipline

Docs are part of the work, not a separate task. Standards:

- **Module docstrings** on every Python file and TypeScript module.
- **Class / function / hook docstrings** on every public export. Bar: "could a future reader understand WHY without reading every line?"
- **ADRs at decision time** — not retroactively. New ADR lands in the same PR as the code change.
- **API docs are auto-generated** from DRF docstrings — never hand-maintained.
- **App READMEs** explain "what's in here, where do I look first."
- **Don't over-document.** No docstrings for trivial accessors. No comments restating what the code obviously does.

## Status

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full roadmap with checkboxes. Phases 0a, 0b, 0d are complete; the build is approaching Phase 1 (vertical-slice features starting with the Customer model).
