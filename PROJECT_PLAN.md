# Lumè CRM — Project Plan

A modern, HIPAA-compliant, multi-tenant CRM for medical spas and salons. Competitor benchmarks: Zenoti, Boulevard (Blvd), Vagaro, Podium.

---

## 1. Core principles

- **HIPAA compliance is non-negotiable.** Every architectural decision must preserve it.
- **Multi-tenant from day one.** Postgres Row-Level Security (RLS) + tenant scoping on every PHI table.
- **Solo dev, cost-conscious.** Free/cheap tiers where possible; pay for what's required for compliance, defer the rest until revenue justifies it.
- **Ship a smaller v1 that 2 spas can run on**, then expand. Don't build everything at once.
- **Modern, professional UI.** Must not feel AI-generated or templated.

---

## 2. Tech stack (locked)

### Backend
- **Language/Framework:** Python 3.12 + Django 5 + Django REST Framework
- **Background jobs:** Celery + Redis (for SMS sends, email sends, form notifications, scheduled reminders)
- **Realtime (later):** Django Channels for live calendar updates (v1 can poll)
- **Multi-tenancy:** `django-tenants` shared schema + Postgres RLS for defense in depth
- **Admin:** Django Admin for super-admin / internal ops

### Frontend
- **Framework:** Next.js 15 + React + TypeScript
- **Styling:** Tailwind CSS + shadcn/ui
- **Calendar:** FullCalendar or `@dnd-kit` for the drag-and-drop scheduler
- **State:** TanStack Query for server state, Zustand for local state
- **Forms:** React Hook Form + Zod
- **Deployment:** Static export to S3 + CloudFront (no PHI in serverless functions)

### Infra (AWS, all under AWS BAA)
- **Compute:** Fargate (containerized Django backend)
- **Database:** RDS Postgres `db.t4g.micro` (encrypted at rest with KMS)
- **Cache/queue:** ElastiCache Redis (or self-hosted on Fargate to start)
- **Auth:** Cognito (covered under AWS BAA)
- **File storage:** S3 with SSE-KMS, signed URLs only
- **Email (transactional):** SES
- **Logging/monitoring:** CloudWatch
- **CDN:** CloudFront in front of frontend
- **Secrets:** AWS Secrets Manager
- **DNS:** Route 53 (subdomain per tenant: `acmespa.lume-crm.com`)

### Third-party (BAA required)
- **SMS:** Twilio (request BAA)
- **Payments:** TBD — user will choose later (NOT Stripe)
- **E-signatures:** Built in-house (canvas + audit trail) to avoid DocuSign cost

### Deferred until revenue justifies
- Sentry HIPAA tier (~$200/mo) — use CloudWatch error logs to start
- Vanta/Drata for compliance automation (~$500/mo) — manual policies to start
- Auth0 — using Cognito instead

---

## 3. HIPAA compliance checklist (foundational, must be done before any PHI lands)

- [ ] Sign AWS BAA (free, in account settings)
- [ ] Sign Twilio BAA (free, request via support)
- [ ] Confirm SES is HIPAA-eligible under our region
- [ ] Designate Privacy Officer + Security Officer (Max)
- [ ] Write & adopt HIPAA policies (templates from Aptible / HHS sample policies)
  - [ ] Access control policy
  - [ ] Audit logging policy
  - [ ] Breach notification procedure
  - [ ] Workforce sanction policy
  - [ ] Incident response plan
- [ ] Initial risk assessment document
- [ ] BAA template that we sign with each spa (we are their Business Associate)
- [ ] Cyber liability insurance quote (~$1–3k/year, defer until first paying client)
- [ ] All PHI tables have `tenant_id` column
- [ ] Postgres RLS policies applied to every PHI table
- [ ] Audit log table (append-only) capturing every PHI read/write with `tenant_id`, `user_id`, `action`, `resource`, `ip`, `timestamp`
- [ ] MFA enforced on all staff accounts
- [ ] 15-min idle session timeout
- [ ] TLS 1.2+ everywhere; no HTTP fallback
- [ ] Encrypted RDS backups, retention policy documented
- [ ] S3 buckets private, KMS-encrypted, no public access
- [ ] CloudTrail enabled on AWS account (audit of infra changes)
- [ ] No PHI in CloudWatch logs (scrub before logging)
- [ ] No PHI in error messages returned to client
- [ ] No PHI in URL query parameters

---

## 4. Phased rollout

### Phase 0g — Marketing site (Session 1 ✅ completed 2026-05-03)
*Goal: a separate Next 16 app at `lumecrm.com` (CRM lives at `<tenant>.lumecrm.com`), editorial / luxury treatment, professional enough to win medspa decision-makers comparing against Boulevard / Zenoti / Podium.*

**Architecture — separate app, mirrored brand**
- [x] **`marketing/` app at the repo root** — Next 16 + React 19 + Tailwind 4, port `:3001` in dev, sibling to `frontend/` (the CRM). Independent `package.json`, deps, build, deployment.
- [x] **MP096 fire palette mirrored verbatim** in `marketing/src/app/globals.css` so the brand reads as one continuous experience (cream → black → burgundy editorial accent → fire emphasis).
- [x] **Brand assets shared** — `favicon.png`, `logosquare.png`, `mainlogo.png` copied to `marketing/public/`. `<BrandMark>` component mirrors the CRM's so any future logo refresh is two file copies.
- [x] **Production deployment shape documented** in [marketing/README.md](marketing/README.md): apex `lumecrm.com` → marketing app, `*.lumecrm.com` wildcard CNAME → CRM, `api.lumecrm.com` → Django backend. `NEXT_PUBLIC_APP_URL` env var points the "Sign in" CTA at the CRM origin.

**Editorial luxury design language (no AI-template tropes)**
- [x] **Custom design utilities** — `.font-display` (Fraunces with `opsz: 144` for hero headlines), `.eyebrow` (small-caps tracked label), `.accent-italic` (italic burgundy phrase inside a serif headline), `.drop-cap` (3-line serif drop cap on opening paragraphs), `.rule` (fine ruled section divider).
- [x] **Anti-patterns explicitly rejected** in [marketing/README.md](marketing/README.md): no gradients, no glassmorphism, no stock-logo strips, no 3-card feature grids, no SaaS boilerplate copy ("Powerful", "Streamline"), no purple/pink illustrations, no accent-colored CTA buttons (burgundy stays editorial).
- [x] **Shared editorial components** — `<TopNav>` (thin top rule, no shadow, restrained nav), `<Footer>` (brand mark + 3-column wayfinding + closing flourish), `<PageHero>` (eyebrow + serif headline + standfirst), `<SectionEyebrow>` (kicker + eyebrow + headline + description for inner sections).

**Six pages live, professionally written copy**
- [x] **`/` Home** — six-section magazine composition: Hero (display headline + numbered "01" pull-out), Manifesto (drop-capped long-form), Capabilities (asymmetric two-column index, NOT a 3-card grid), "The Room" (full-width inverted black/cream atmospheric section), Pull-quote, Closing invitation.
- [x] **`/features`** — magazine-style table of contents; six numbered rows, each linking to its (Session 2) deep-dive page.
- [x] **`/security`** — long-form HIPAA + SOC 2 essay with sticky sidebar of six concrete commitments, each citing the relevant ADR (0001, 0003, 0004, 0011, 0012, 0013). The substantive differentiator on the site.
- [x] **`/pricing`** — request-a-demo model. Names the four real variables (locations, providers, SMS volume, migration depth). Honest about why no public sticker price.
- [x] **`/demo`** — editorial demo request form (bare-bottom-rule inputs, not boxed shadcn fields). 4-step "what happens next" sidebar. Client-side confirmation in v1; backend wiring in Session 2.
- [x] **`/about`** — single-column founder note, drop-capped, with "the standard we work to" + "what we won't build" + "where we are right now" sections.

**Build verified**
- [x] All 6 pages return 200 from the dev server at `localhost:3001`.
- [x] Production build clean (`npm run build` → 8 static routes generated, TypeScript passes).
- [x] Brand assets shared with the CRM — logo, favicon, palette, fonts identical end-to-end.

**Session 2 (next): Feature deep-dive pages + demo backend wiring**
- [ ] `/features/booking`, `/features/charts`, `/features/forms`, `/features/payments`, `/features/reports`, `/features/multi-location` — six deep-dive pages with screenshots/diagrams of the actual product surface.
- [ ] `/medspas` — vertical positioning page (why a medspa-specific CRM, what we don't try to be).
- [ ] **Demo form backend** — `apps/marketing` Django app with `DemoRequest` model (name/email/spa/locations/providers/current_software/message/created_at), `POST /api/demo-requests/` endpoint, ops Slack notification on submit.
- [ ] SEO meta polish (OpenGraph images per page, structured data for `/about` + `/security`).

**Session 3 (later): Content + visual polish**
- [ ] Blog / journal scaffold (MDX-based, editorial layout matching the rest of the site).
- [ ] Customer story template + the first published story (post-launch with one of the migrating spas).
- [ ] Real spa photography in the home hero + about page (currently using typographic compositions as placeholders).
- [ ] `/privacy`, `/terms`, `/baa` legal pages — written content, footer links already in place.

### Phase 0h — CRM dashboard ✅ (completed 2026-05-04)
*Goal: replace the placeholder "Build status / Phase 1A complete" dashboard with a real role-aware operations surface — the daily entry point for every operator. The single screen everyone sees first should answer "is the day running well" in one glance.*

**Design constraint locked in: dashboard metrics drive action.** Excluded all vanity metrics (total clients ever, all-time revenue, "features used", engagement scores). Every tile is something an operator can act on.

**Architecture — reuses Phase 1G report endpoints**
- [x] **Zero new backend.** Every tile, chart, and panel hits an existing report endpoint (`financial.sales-by-date-range`, `operations.appointments-by-status`, `operations.no-show-rate`, `guests.new-vs-returning`, `financial.ar-aging`, `guests.forms-outstanding`) plus the existing `useAppointmentsForDate` hook. The 22 reports we shipped do double duty as the dashboard data layer — same audit logging, same permission gating, same tenant isolation.
- [x] **Date-window helpers in [`_components/date-windows.ts`](frontend/src/app/(app)/dashboard/_components/date-windows.ts)** — `todayWindow`, `monthToDateWindow`, `last30DaysWindow`, plus comparison-window builders (`todayVsSameDayLastWeek`, `monthToDateVsLastMonth` that caps at last-month's last-day for Mar-31-vs-Feb edge cases). `deltaPct` returns null for divide-by-zero so the UI shows em-dash, not Infinity. `deltaTone()` lets each tile declare whether higher = good (revenue, new clients) or higher = bad (no-show rate).

**Chart primitives — pure SVG, zero animation library**
- [x] **`<Sparkline>`** — 1000-unit viewBox, `vector-effect: non-scaling-stroke` for crispness across container sizes, weekend-day shading bands, accent-tinted fill below the line, hoverable point circles with `<title>` tooltips. ~80 lines. No Recharts / Visx dependency saved ~50KB and one tier of next/turbopack-update breakage risk.
- [x] **`<DeltaArrow>`** — up/down/flat icon (lucide ArrowUpRight / ArrowDownRight / Minus) with tone-aware color (positive = emerald, negative = rose, neutral = muted). Renders em-dash placeholder when `pct=null` (divide-by-zero comparison).
- [x] **`<KpiTile>`** + **`<KpiRow>`** — label + serif tabular-nums value + optional subline + optional delta arrow with hint. Loading state renders skeleton bars at the right heights so the grid doesn't jump on first paint.

**Four KPI tiles wired to live data**
- [x] **Revenue today** vs. same day last week — invoice count subline ("4 paid invoices today" or "No paid invoices yet today"), green/red delta.
- [x] **Appointments today** — total + status breakdown subline ("3 done · 2 upcoming"). No delta because count isn't a goal.
- [x] **New clients this month** vs. equivalent days last month (clamped at last-month's last day). Higher = good.
- [x] **No-show rate this month** vs. same window last month. Higher = BAD — `deltaTone='lower_is_better'` flips the arrow color so a +1.2pp increase reads red.

**Hero revenue chart**
- [x] **`<RevenueChartPanel>`** — 30-day daily revenue sparkline + total + delta vs. previous 30-day window. Header has the headline number in serif tracking-tight tabular-nums + the delta arrow + a "weekend days subtly shaded" hint + an "Open report →" link to the full Sales by date range report.

**Three "needs attention" panels**
- [x] **Today's schedule** — next 6 appointments sorted by relevance (checked-in / upcoming first, completed / no-show / cancelled at the bottom), with time / client name / service / provider / status pill. Click-through to client profile. "+N more on the calendar" link if truncated. Pulls from existing `useAppointmentsForDate(today)` so it's the same data the calendar shows — no duplicate query layer.
- [x] **Overdue invoices** — top 5 from AR aging report, filtered to drop the "current" bucket (current invoices haven't crossed the 30-day chase line yet). Per-bucket color tone (30-60d amber, 60-90d orange, 90+ rose). Headline shows total overdue + count. Click-through to client profile.
- [x] **Pending consent forms** — top 5 from forms-outstanding report. Headline shows total pending + customer count ("8 forms · 3 clients" or "All signed"). Each row click-through to client profile.

**Role-aware composition (mirrors the API gates)**
- [x] **Owner / Manager** — every tile, hero chart, and all 3 panels.
- [x] **Bookkeeper** — Revenue tile + Revenue chart + AR overdue panel only. No operational / guest surfaces (matches their `VIEW_FINANCIAL_REPORTS`-only access).
- [x] **Front desk** — Today's appointments tile + Today's schedule + Forms pending. No financial surfaces (matches their `VIEW_OPERATIONS_REPORTS`-only access).
- [x] **Provider** — Today's appointments tile + Today's schedule. Their day-of-business surface; everything else lives elsewhere.
- [x] **Marketing** — New clients tile only. Their `VIEW_GUEST_REPORTS` gate aligns to the new-clients metric.

**Polish**
- [x] **Time-of-day greeting** ("Good morning, Sarah" / "Good afternoon" / "Good evening") gated behind `useEffect` to avoid SSR hydration mismatch — server renders "morning", client effect swaps the real time on mount.
- [x] **Empty states everywhere** — a brand-new tenant on day one sees "No appointments scheduled" / "All clear" / "All signed" instead of skeleton bars that never resolve.
- [x] **Smoke-tested against real seed data** — all 9 endpoints (today's revenue, last-week comparison, 30-day series, today's appointments, MTD new clients, MTD no-show, AR aging, forms outstanding, today's appointment list) return 200 with expected shapes. Acmespa dev tenant: 17 AR rows, 8 customers, 30 daily revenue points, 3 appointments today.

**Removed**
- [x] The "Build status / Phase 1A complete · Phase 1B next" placeholder card. The dashboard no longer leaks dev status to operators.

### Phase 0f — Visual design system ✅ (completed 2026-04-30)
*Goal: warm-luxe brand identity established as design tokens so every future page inherits a cohesive feel — not "shadcn defaults."*

- [x] **Color palette** — warm cream background, deep warm charcoal text, dusty rose-gold accent (OKLCH-based, see [ADR 0006](docs/decisions/0006-visual-design-system.md))
- [x] **Typography** — Geist Sans for body, Fraunces serif for page titles + brand wordmark
- [x] **Sidebar** — Lucide icons, serif "Lumè" wordmark, active-route highlighting, user avatar in footer
- [x] **Reusable patterns** — `<PageHeader>` (title + description + actions + back), `<StatusBadge>` (colored dot + label), `<InitialsAvatar>` (deterministic color from name)
- [x] **Pages updated** — `/`, `/login`, `/dashboard`, `/clients`, `/clients/[id]`, `/clients/new` all redesigned to use the new patterns

### Phase 0e — Documentation foundation ✅ (completed 2026-04-30)
*Goal: documentation discipline established as part of the workflow, not retroactive cleanup.*

- [x] **Tier 4: API docs** — `drf-spectacular` installed and wired. Swagger UI at `/api/docs/`, ReDoc at `/api/redoc/`, OpenAPI YAML at `/api/schema/`. Auto-generated from DRF view docstrings.
- [x] **Tier 1: Code-level docs** — module docstrings on every Python module and TypeScript file. Public class/function/hook docstrings on all major exports. Audited and gaps filled.
- [x] **Tier 2: READMEs** — top-level `README.md`, `backend/README.md`, `frontend/README.md`, plus per-app READMEs for `apps/users`, `apps/tenants`, `apps/audit`.
- [x] **Tier 3: ADRs** — `docs/decisions/` directory with index README + Michael Nygard format. Five initial ADRs:
  - 0001 — Multi-tenancy strategy
  - 0002 — Authentication strategy (interim; revisited at Cognito migration)
  - 0003 — Permission model
  - 0004 — Audit logging
  - 0005 — Frontend stack
- [x] Documentation discipline codified in `README.md` and saved to project memory — ADRs at decision time, docstrings as you code, API docs auto-generated, READMEs when something is non-obvious. Don't over-document.

### Phase 0d — Frontend skeleton ✅ (completed 2026-04-30)
*Goal: Next.js + Tailwind + shadcn/ui app shell standing, with auth + app route groups, ready for vertical-slice features.*

- [x] Next.js 16.2 + React 19.2 + TypeScript scaffolded in `frontend/`
- [x] Tailwind v4 (CSS-first config) + Geist font wired
- [x] shadcn/ui initialized (base-nova style, neutral palette, lucide icons)
- [x] Base shadcn components installed: Button, Input, Card, Label, Sonner (toasts)
- [x] TanStack Query + Devtools installed and wired via `Providers` in root layout
- [x] API client (`src/lib/api.ts`) with credential-included fetch wrapper, JSON helpers, typed `ApiError`
- [x] App Router structure: `(auth)` group, `(app)` group, marketing route at `/`
- [x] Auth-shell layout (centered card, muted bg) + login placeholder at `/login`
- [x] App-shell layout (sidebar with placeholder nav) + dashboard placeholder at `/dashboard`
- [x] All three routes verified to render (HTTP 200) via `npm run dev`
- [x] `.env.local` with `NEXT_PUBLIC_API_URL` pointing at local Django (`http://localhost:8000`)
- [x] Login form wired to Django auth → session cookie → dashboard redirect (completed 2026-04-30)
- [x] Backend: `/api/auth/csrf/`, `/api/auth/login/`, `/api/auth/logout/`, `/api/auth/me/` endpoints (DRF SessionAuthentication) (completed 2026-04-30)
- [x] django-cors-headers installed; CORS_ALLOWED_ORIGINS + CSRF_TRUSTED_ORIGINS configured for localhost:3000 (completed 2026-04-30)
- [x] Frontend API client attaches `X-CSRFToken` header on POST/PUT/PATCH/DELETE from `csrftoken` cookie (completed 2026-04-30)
- [x] Auth hooks (`useUser`, `useLogin`, `useLogout`) backed by TanStack Query (completed 2026-04-30)
- [x] react-hook-form + zod login form with field-level error display (completed 2026-04-30)
- [x] `(app)` layout route guard — redirects unauthenticated users to `/login` (completed 2026-04-30)
- [x] Dashboard shows authenticated user's email, role, tenant memberships; sign-out button works (completed 2026-04-30)

### Phase 0a — Local development environment ✅ (completed 2026-04-29)
*Goal: Django + Postgres running locally on the dev machine with a clean repo skeleton.*

- [x] Python 3.12 installed via Homebrew
- [x] Postgres 16 installed via Homebrew + running as background service
- [x] `psql` added to PATH via `~/.zshrc`
- [x] Git repo initialized (`main` branch)
- [x] Monorepo folder structure: `backend/` + `frontend/`
- [x] `.gitignore` covering Python, Django, Node, macOS, IDE, env files
- [x] Python 3.12 virtual environment in `backend/.venv`
- [x] Backend dependencies installed: Django 5.1, DRF 3.17, psycopg 3 (binary), django-environ
- [x] `requirements.txt` pinned via `pip freeze`
- [x] Django project skeleton (`lume_crm` config module + `manage.py`)
- [x] Local Postgres database `lume_crm_dev` created
- [x] `settings.py` rewritten to read SECRET_KEY / DEBUG / DATABASE_URL from `.env` (django-environ)
- [x] `.env` (gitignored) + `.env.example` (committed) created
- [x] `rest_framework` added to INSTALLED_APPS
- [x] Initial Django migrations applied (auth, sessions, admin, contenttypes)
- [x] Dev server verified responding HTTP 200 at `http://127.0.0.1:8000`

### Phase 0b — Multi-tenant foundation (in progress)
*Goal: tenant + user models + isolation primitives in place so Phase 1 features can plug into them safely.*

- [x] Custom user model (`apps/users`) — email-as-login, `User` extends `AbstractUser` (completed 2026-04-30)
- [x] `AUTH_USER_MODEL = 'users.User'` wired in settings (completed 2026-04-30)
- [x] User registered in Django admin with `UserAdmin` customization (completed 2026-04-30)
- [x] First Django superuser created (codenestwebstudios@gmail.com) (completed 2026-04-30)
- [x] Tenant model (`apps/tenants`) — name, slug/subdomain, status, timezone, address, branding (completed 2026-04-30)
- [x] Tenant onboarding service (`services.create_tenant_with_defaults`) — creates tenant + seeds job titles + creates Owner membership in one transaction (completed 2026-04-30)
- [x] Subdomain-based tenant resolution middleware (`apps.tenants.middleware.TenantMiddleware`) — attaches `request.tenant` and `request.tenant_membership` (completed 2026-04-30)
- [x] `TenantMembership` model with `role`, `job_title`, `is_bookable`, `is_active`, `extra_permissions`, `revoked_permissions`, `hipaa_training_acknowledged_at` (completed 2026-04-30)
- [x] Role enum (6 roles): **Owner**, **Manager**, **Front Desk**, **Provider**, **Bookkeeper**, **Marketing** (completed 2026-04-30)
- [x] `JobTitle` model (per-tenant, customizable, with `is_clinical` flag) seeded with 9 defaults via `create_tenant_with_defaults` (completed 2026-04-30)
- [x] Permission catalog (`apps.tenants.permissions.P`) covering staff, clients, appointments, charts, financials, marketing, configuration (completed 2026-04-30)
- [x] `ROLE_DEFAULTS` dict mapping each of the 6 roles to its default permission set (completed 2026-04-30)
- [x] Permission resolver: `membership.has(perm) = (ROLE_DEFAULTS[role] ∪ extra) − revoked` with `LOCKED_PERMISSIONS` guardrail (completed 2026-04-30)
- [x] Locked permissions: `DELETE_TENANT` and `MANAGE_BILLING` cannot be granted via per-user override (completed 2026-04-30)
- [x] User can belong to multiple tenants with different roles per tenant (`unique_together` on user+tenant) (completed 2026-04-30)
- [x] Smoke-tested: tenant creation, job title seeding, permission resolution, override grant + revoke, locked-perm rejection (completed 2026-04-30)
- [ ] Per-user permission override UI (in tenant settings → staff management) — Owner can grant/revoke individual permissions per user
- [ ] Guardrail: Owners cannot revoke perms from other Owners (model-level enforcement)
- [ ] HIPAA training acknowledgment flow (collect timestamp on first login for Bookkeeper/Marketing/clinical roles)
- [x] `TenantedModel` abstract base + `TenantedQuerySet` with `for_current_tenant()` / `for_tenant(tenant)` — PHI tables inherit from this (completed 2026-04-30)
- [x] Per-request tenant context via `contextvars` (`apps.tenants.context`) — middleware sets it, app code reads it (completed 2026-04-30)
- [x] `AuditLog` model — append-only (raises `ValidationError` on update/delete), indexed for `(tenant, -timestamp)`, `(user, -timestamp)`, `(resource_type, resource_id)`, `(action, -timestamp)` (completed 2026-04-30)
- [x] `audit.services.record(...)` helper — auto-pulls user/tenant/IP/UA from request (completed 2026-04-30)
- [x] Auth signal wiring — `user_logged_in` / `user_logged_out` / `user_login_failed` → AuditLog (completed 2026-04-30)
- [x] `AuditLog` registered in admin as read-only (no add/change/delete) (completed 2026-04-30)
- [ ] Postgres Row-Level Security (RLS) policies on tenanted tables — deferred to Phase 0c (production needs `lume_app` / `lume_admin` role split)
- [ ] Per-feature audit instrumentation (record reads/writes on customer charts, invoices, etc.) — added as features land in Phase 1
- [ ] Local login + session management (Django built-in for now; Cognito later)
- [ ] MFA stub (TOTP via `django-otp`) — local for now; we'll bridge to Cognito in Phase 0c

### Phase 0c — Production infra (deferred until v1 is feature-complete locally)
*Goal: get the Django app running on AWS under a BAA before any real spa data lands.*

- [ ] Domain registered (`lume-crm.com` or chosen name)
- [ ] AWS account set up, BAA signed, billing alerts configured
- [ ] Backend Dockerfile + Fargate task definition
- [ ] RDS Postgres provisioned (encrypted at rest, automated backups)
- [ ] Cognito user pool configured (replaces local auth)
- [ ] S3 bucket(s) with SSE-KMS for files
- [ ] CloudFront + S3 hosting for frontend (when frontend exists)
- [ ] CI/CD pipeline (GitHub Actions → ECR → Fargate)
- [ ] Subdomain routing wildcard (`*.lume-crm.com` → frontend; resolves tenant from subdomain)
- [ ] CloudWatch logging with PHI-scrubbing filter
- [ ] Secrets Manager wired up (replaces `.env` in production)
- [ ] Production smoke test against fake tenant data

### Phase 1 — Core spa operations (Weeks 3–8) — **v1 target**
*Goal: 2 spas can run their day-to-day on this. Bookings, customers, forms, reminders, invoices.*

#### 1A. Customer management
- [x] Customer model (extends `TenantedModel`) with PHI fields — DOB, sex, address, emergency contact, medical history, allergies, medications, Fitzpatrick skin type (completed 2026-04-30)
- [x] CustomerTag model (per-tenant, customizable) + M2M to Customer (completed 2026-04-30)
- [x] Provenance fields (`external_id`, `external_source`, `imported_at`) for Zenoti migration upsert (completed 2026-04-30)
- [x] DRF API at `/api/customers/` — list (with `?q=` search, `?status=` filter), retrieve, create, update, delete (completed 2026-04-30)
- [x] `CustomerPermission` mapping actions to Lumè permission identifiers (`VIEW_CLIENT_LIST`, `EDIT_CLIENT_RECORD`, etc.) (completed 2026-04-30)
- [x] Audit logging on every endpoint — list, retrieve, create, update, delete (completed 2026-04-30)
- [x] `TenantMiddleware` extended to read `X-Tenant-Slug` header as dev fallback for subdomain (completed 2026-04-30)
- [x] Frontend cookie-based active-tenant plumbing — set on login, cleared on logout, sent as header on every API call (completed 2026-04-30)
- [x] Frontend customer hooks: `useCustomers`, `useCustomer`, `useCreateCustomer` (completed 2026-04-30)
- [x] Frontend `/clients` list page with live search and tag chips (completed 2026-04-30)
- [x] Frontend `/clients/new` create form (RHF + zod, server-side error mapping) (completed 2026-04-30)
- [x] Frontend `/clients/[id]` detail page with grouped sections (Contact, Address, Emergency, Marketing, Medical) (completed 2026-04-30)
- [x] Sidebar Clients link enabled (completed 2026-04-30)
- [x] `apps/customers/README.md` documenting the API + the pattern to copy for future PHI features (completed 2026-04-30)
- [x] Edit mode on detail page — Profile tab is the editable form; Save/Discard with sticky action bar (completed 2026-04-30)
- [x] `useUpdateCustomer` hook + PATCH `/api/customers/{id}/` round-trip (completed 2026-04-30)
- [x] PHI field hiding for users without `VIEW_CLIENT_PHI` (Phase 1A.1 hardening) — shipped 2026-05-12. `CustomerDetailSerializer` redacts PHI on read (omits keys from response) and rejects PHI on write atomically. Frontend `/clients/[id]` Overview + Profile tabs hide PHI sections for non-PHI roles and render a `PhiRedactedBanner`. 8 tests cover both halves. See [ADR 0017](docs/decisions/0017-phi-redaction.md).

#### 1A.3. Tabbed client detail shell ✅ (completed 2026-04-30)
*Customer detail page is structured as a "client 360" view with hero (avatar + name + status + referral code chip) persistent across all tabs. Active tab driven by `?tab=` query param so deep links work.*

- [x] Tabs scaffold rendering 15 tabs total — 3 with content, 12 placeholders that fill in as the underlying features ship (completed 2026-04-30)
- [x] **Working tabs:** Overview (read-only summary), Profile (editable form), Referrals (referral code + share)
- [ ] **Appointments** — placeholder; fills in with Phase 1D (booking calendar)
- [ ] **Notes** — placeholder; fills in with Phase 1A.4 (provider-only timestamped notes thread)
- [ ] **Products** (purchased) — placeholder; fills in with Phase 2A (POS / retail items)
- [ ] **Memberships** — placeholder; fills in with Phase 2C (membership purchases + active status)
- [ ] **Packages** — placeholder; fills in with Phase 2B (package balances + redemption history)
- [ ] **Wallet** (open invoices + credit balance) — placeholder; fills in with Phase 1E (invoicing)
- [ ] **Payments** — placeholder; fills in with Phase 2A (payment processor + transaction history)
- [ ] **Treatment forms** (assigned + signed) — placeholder; fills in with Phase 1D (forms + e-sign)
- [ ] **Prescriptions** — placeholder; fills in with Phase 4D (NEW — Rx tracking, see below)
- [ ] **Campaigns** — placeholder; fills in with Phase 3B (email marketing send log)
- [ ] **Notifications** — placeholder; fills in with Phase 1F (SMS reminder send log)
- [ ] **Gallery** — placeholder; fills in with Phase 4B (before/after photos)

#### 1A.4. Customer notes (provider-only thread) ✅ (completed — shipped as clinical chart notes; scope expanded mid-build)
*Shipped as a clinical chart-notes system rather than a generic notes thread — see [ADR 0015 — Clinical chart notes](docs/decisions/0015-clinical-chart-notes.md). The 5 original items below are subsumed by the expanded scope: addendum-on-locked-note pattern, void-with-reason audit trail, 60-minute edit window with explicit lock badge, clinical-role gate via `canSignCharts` / `canViewCharts`.*

- [x] `ChartNote` model — author + body + parent_note_id (addenda) + voided_at/voided_reason + signed_at + locks 60 min after signing
- [x] DRF API at `/api/customers/{id}/chart-notes/` (list + create + update + void + addendum)
- [x] Permission gating: `VIEW_CHART` / `SIGN_CHART` / `VOID_CHART` permissions; non-clinical roles see explicit "no access" state
- [x] Frontend Notes tab — chronological feed, "Sign note" composer at top, addendum threading, lock badge with minutes-remaining, void confirmation flow
- [x] Audit log on every note read + write (sensitive — clinical impressions and procedure-context data)

#### 1A.2. Customer referrals — capture layer
*Each client gets a unique referral code; new-client form has a "Referred by code" field; admin shows referrer→referred relationships. No reward logic in this phase — that lands with payments in Phase 2H.*

- [x] `referral_code` field on Customer (auto-generated, unique per tenant, indexed) — 8 chars from unambiguous alphabet, partial unique constraint per tenant (completed 2026-04-30)
- [x] Auto-generate referral codes on Customer save (retry on collision, raises if 20 attempts fail) (completed 2026-04-30)
- [x] Data migration backfilled all 7 existing customers with unique codes (completed 2026-04-30)
- [x] Customer detail page: referral code shown in hero chip with copy-to-clipboard button + dedicated Referrals tab (completed 2026-04-30)
- [x] Admin: searchable by `referral_code`; visible in list view and as read-only field (completed 2026-04-30)
- [ ] `referred_by` FK on Customer (Customer → Customer, nullable, self-FK)
- [ ] New-client form: optional "Referred by code" input; resolves to a Customer or shows "code not found"
- [ ] Customer detail Referrals tab: "Referred by" link to the referrer; "People they've referred" list with count
- [ ] Admin: reverse-lookup of referred customers visible on the referrer's admin page

#### 1B. Service catalog
- [x] `Service` model (name, description, category, duration, buffer, price_cents, is_bookable_online, is_active, sort_order) extending `TenantedModel` (completed 2026-04-30)
- [x] `ServiceCategory` model (per-tenant, color + sort_order) (completed 2026-04-30)
- [x] DRF API at `/api/services/` and `/api/service-categories/` with audit logging on every action (completed 2026-04-30)
- [x] `ServicePermission` — read for any authenticated tenant member, write requires `MANAGE_SERVICES` (completed 2026-04-30)
- [x] Admin with grouped fieldsets (Basics / Booking / Pricing) (completed 2026-04-30)
- [x] Seeded 5 categories + 13 sample services (completed 2026-04-30)
- [x] Frontend hooks (`useServices`, `useService`, `useCreateService`, `useUpdateService`, `useServiceCategories`) + `centsFromDollars` / `dollarsFromCents` helpers (completed 2026-04-30)
- [x] Frontend `/services` list page with search, status indicator, category badge, monospace price column (completed 2026-04-30)
- [x] Frontend `/services/new` create form with live preview pane (completed 2026-04-30)
- [x] Frontend `/services/[id]` detail/edit page with hero strip + sticky save bar (completed 2026-04-30)
- [x] Sidebar Services link enabled (completed 2026-04-30)
- [x] `apps/services/README.md` documenting the API + the patterns (completed 2026-04-30)
- [x] **Category-first navigation** — `/services` lands on a categories grid; click a card to drill into services; `?all=1` for the flat view; "Manage categories" via gear icon on each card (completed 2026-04-30)
- [x] **Job-title-level eligibility per category** (replaces per-service per-provider eligibility — 5×9 ≈ 45 mappings instead of 100+) (completed 2026-04-30)
- [x] `eligible_job_titles` M2M on `ServiceCategory` (empty = no restriction; populated = whitelist) (completed 2026-04-30)
- [x] `JobTitle` read-only API at `/api/job-titles/` for the eligibility selector (completed 2026-04-30)
- [x] `<CategoryEligibilitySelector>` reusable component — clinical / non-clinical groups, quick-select chips ("All clinical", "Everyone", "No restriction") (completed 2026-04-30)
- [x] Category create + edit pages at `/services/categories/new` and `/services/categories/[id]` (completed 2026-04-30)
- [x] Eligibility seeded for the 5 sample categories (Injectables → NP/RN/PA; Massage → Massage Therapist only; Body → unrestricted) (completed 2026-04-30)
- [ ] **Eligibility enforcement** at appointment-creation time — booking calendar must filter the provider dropdown to staff whose `TenantMembership.job_title` is in the category's `eligible_job_titles` (Phase 1D)
- [ ] Per-service eligibility override (rare case where one service in a category needs different rules) — defer; add only if a real spa requests it
- [x] **Service code (SKU)** — auto-generated on save (e.g. `BTX20`), user-overridable, unique within tenant via partial constraint (completed 2026-04-30)
- [x] **Tax rate per service** (`tax_rate_percent`, decimal up to 99.999, applied at invoice time) (completed 2026-04-30)
- [x] **Service type** — Regular vs Add-on enum on each service (completed 2026-04-30)
- [x] **Tabbed detail page** mirroring customer detail — General (working), Locations / Inventory / Commissions / Forms (placeholders) (completed 2026-04-30)
- [x] **Service hero strip** sticky on detail — name + code chip + status + category + price + duration (completed 2026-04-30)
- [ ] Add-on attachment rules — which add-ons attach to which regular services (Phase 1D, when booking flow is built)
- [ ] **Locations tab** — pick which locations offer this service (Phase 4E multi-location)
- [ ] **Inventory tab** — products consumed per service performance (Phase 4C inventory)
- [ ] **Commissions tab** — per-role / per-staff commission % on this service (Phase 2F commissions)
- [ ] **Forms tab** — auto-assign one or more consent / intake / treatment forms when booked (Phase 1D forms)
- [ ] Form template requirement on Service (auto-assign on booking) — Phase 1D, ships with forms

#### 1C. Booking calendar (the centerpiece)

**Session 1 — data model + read-only day view ✅ (completed 2026-04-30):**
- [x] `apps.appointments` Django app with `Appointment` model (extends `TenantedModel`); status enum (`booked → confirmed → checked_in → completed`, plus `cancelled` / `no_show`); check constraint enforces `end_time > start_time`; snapshot price; `created_by` provenance; status-transition timestamps (`checked_in_at`, `completed_at`, `cancelled_at`); indexes for the calendar queries
- [x] `AppointmentPermission` — reads open to any tenant member, writes gated by `BOOK_APPOINTMENT` / `RESCHEDULE_*` / `CANCEL_APPOINTMENT`; object-level check enforces "providers reschedule own only" when only `RESCHEDULE_OWN_APPOINTMENT` is granted
- [x] DRF API at `/api/appointments/` with `?date=YYYY-MM-DD` (tenant-tz aware), `?start=&end=`, `?provider=`, `?customer=`, `?status=` filters; nested customer / service / provider summaries on read; audit logging on every action
- [x] `MembershipViewSet` at `/api/memberships/` with `?bookable=true&active=true` filter, used to populate the provider columns
- [x] 3 bookable providers seeded (NP, Aesthetician, Massage Therapist) + 1 non-bookable receptionist; 22 sample appointments across the current week with varied statuses
- [x] **Dedicated calendar workspace** — new `(calendar)` route group sibling to `(app)` and `(auth)`; its own layout (top bar, no left sidebar); auth gate; closes back to `/dashboard`
- [x] `CalendarTopBar` — wordmark + close affordance, today / prev / next + date picker, view toggle (Day enabled, Week / Month stubbed), New appointment button (stub)
- [x] `DayView` — time axis 8 AM–8 PM, provider columns with avatars + job titles, appointment blocks positioned absolutely with category-color left border, status dot, time range, customer + service text; clamp to visible window; cancelled / no-show blocks render dimmed with strike-through
- [x] Sidebar Calendar link wired to `/calendar` (no longer "coming soon")

**Session 2 ✅ (completed 2026-05-02):**
- [x] **New-appointment bottom sheet** — slides up from the bottom edge of the calendar, centered with `max-w-3xl`, so the day-view stays visible above a backdrop. Form fields:
  - Searchable customer typeahead (`useCustomers({ q })`) with an inline "+ Create new customer" mini-form (first / last / phone / email) that auto-selects on success — saves the front desk a tab-switch for walk-ins.
  - Searchable service typeahead (matches name OR code; client-side filter over the active service list).
  - Eligibility-filtered provider Select (recomputes when service changes; clears stale selection if it becomes ineligible).
  - Custom DatePicker + custom TimePicker (5-min snap, 8 AM – 8 PM scope, 12-hr display).
  - Optional notes textarea.
  - Soft same-provider conflict warning on the focus date — surfaces but doesn't block submit.
  Auto-opens an OPEN invoice via the appointment-creation signal (ADR 0007). Opens from the "New appointment" button or from clicking an empty time slot in any provider column (pre-fills date / time / provider).
- [x] **Status-transition actions** — Confirm / Check in / Cancel / No-show as buttons in the appointment popover; "Undo check-in" available when checked in (CHECKED_IN → CONFIRMED, clears `checked_in_at`). Backend audit-logs every transition with `from_status` / `to_status`. **Completion is gated through invoice closure**, not a direct status button (see ADR 0007).
- [x] **Click-and-drag to reschedule** — appointments drag across columns and time. Provider eligibility blocks ineligible drops client-side; backend re-validates.
- [x] **Right-click reschedule** — separate flow: click "Reschedule" in the popover → calendar enters rescheduling mode (URL: `?rescheduling=ID&duration=MIN`, persists across date navigation), source block fades with burgundy ring, banner across the top, right-click any time slot to drop here / cancel via small context menu.
- [ ] Resize handle to extend / shorten — deferred (drag covers the common reschedule case; resize is rarer)
- [x] **Quick-edit popover** — full-featured: customer header (burgundy banner) + service summary + status transitions + Take Payment CTA (opens dedicated invoice page in new tab) + Reschedule + Notes editor + Logs link. Replaces the stub toast.

**Session 2.5 — added beyond original Session 2 plan ✅ (completed 2026-05-02):**
- [x] **Custom DatePicker** (`@/components/ui/date-picker.tsx`) — Popover-anchored, month grid with prev/next nav + 4 quick-pick chips (Today, +2 / +4 / +6 weeks). Replaces the native `<input type="date">` everywhere.
- [x] **Custom TimePicker** (`@/components/ui/time-picker.tsx`) — Popover-anchored, two-column hour/minute grid, 5-min step (matches the calendar's drag-snap), business-hours scope (8 AM – 8 PM), 12-hr display / 24-hr internal. Replaces the native `<input type="time">`.
- [x] **Dialog primitive** (`@/components/ui/dialog.tsx`) — base-ui wrapper for centered modals (terse confirms / quick edits).
- [x] **Sheet primitive** (`@/components/ui/sheet.tsx`) — side-anchored full-height drawer (left or right) using the same base-ui Dialog under the hood as `<Dialog>`. Used for workflow-heavy surfaces like the New Appointment form.
- [x] **Audit metadata enrichment** — `Appointment.perform_update` now captures before/after on `start_time` / `end_time` / `provider_id` whenever they change (`rescheduled: true` + `from_start` / `to_start` keys). Logs page renders these as "Rescheduled May 14 10:00 AM → May 14 11:30 AM" instead of just "Edited start_time, end_time."
- [x] **Activity log page** at `/appointments/[id]/logs` — full per-appointment audit timeline, opened from the popover via a small "Logs" link in a new tab. Renders multi-event PATCHes (status + reschedule + provider change) as stacked phrases.
- [x] **Invoicing pulled forward** — full Phase 1E scaffolding shipped early. See "1E. Invoicing" section below; ADR 0007 documents the appointment-completion gate.

**Session 3 (later):**
- [ ] Week view (7 day columns × time grid)
- [ ] Hard conflict prevention — currently the modal warns on overlap but allows submit; tighten this with respect to `buffer_minutes` (today buffer is ignored).
- [x] **Eligibility enforcement** — both the New Appointment modal provider dropdown and the drag-drop drop-target highlighting filter by `ServiceCategory.eligible_job_titles`. Backend re-validates on every PATCH/POST.

**Session 4 ✅ (completed 2026-05-02): Per-provider weekly scheduler**

*The "professional scheduling system" — visual weekly grid for setting per-employee, per-location working hours, with the calendar's day view dimming non-working hours so the front desk reads "this provider is off here at this time" at a glance.*

- [x] **`ProviderSchedule` model** (1:1 with `MembershipLocation` so the same person has different hours per site) with `weekly_hours` JSON: `{monday: [{start: "09:00", end: "17:00"}], ...}`. Empty array per day = "off." Multiple blocks support split shifts (lunch breaks, double sessions). Migration 0008.
- [x] **`/api/schedules/{membership_location_id}/`** GET + PUT. GET returns the canonical 7-weekday shape even when no row exists (lazy materialization on first PUT). PUT replaces the entire template; full backend validation (HH:MM format, end > start, no overlapping blocks within a day, exact 7-key structure). Owner + manager only via `MANAGE_STAFF`. Audit-logged with day-level diffs.
- [x] **Bookable memberships endpoint embeds `schedule_for_location`** when called with `?location=current|<slug>` so the calendar gets the per-provider schedule in one round-trip — no per-provider fetch storm. The org-wide staff list omits these fields to keep the payload thin.
- [x] **`/staff/schedule` weekly grid** — rows = providers at active location, cols = Mon–Sun. Each cell renders a horizontal timeline bar scaled to the location's business-hours window with accent-tinted segments for working blocks and time labels inline. Clicking a cell opens a popover editor with `<TimePicker>` pairs per shift, +/− to add/remove, client-side validation mirroring the backend. Per-provider weekly-total ("32h / week") shown next to the name. Assign + Remove controls integrated into the same surface so location assignments and scheduling live together.
- [x] **Calendar working-hours overlay** — `<WorkingHoursOverlay>` in `day-view.tsx` reads each provider's `schedule_for_location`, derives the current weekday from the visible date, and dims non-working time as a translucent muted-foreground overlay sitting above the time grid but below appointment blocks. Booked appointments stay readable even when scheduled outside working hours (operator can see exceptions). `pointer-events-none` so the column's right-click context menu still fires on overlay regions.
- [x] **16 new backend tests** covering: empty-shape on first read, PUT creates + overwrites, split shifts, overlap rejection, end-before-start rejection, unknown weekday rejection, invalid HH:MM rejection, front-desk forbidden, audit log shape, cross-tenant 404; bookable embed (membership_location_id, null-when-unset, hours-when-set, omitted-from-org-wide). **134/134 total backend tests passing.** Frontend TS unchanged at 11 pre-existing.

**Out of scope this session (still future):**
- [ ] **`ScheduleException`** for one-off overrides ("Sarah off Christmas Eve") — today's PUT is full-replace and operator handles ad-hoc by editing the day inline. Real exception model lands when calendar consumption needs date-keyed overrides.
- [ ] Drag-drop respects schedules — calendar lets bookings outside working hours today (with the visible overlay showing they're off-schedule). Hard rejection + warning banner when drops land outside working hours is a follow-up.
- [ ] Online booking only offers slots inside provider hours — Phase 1I work; the schedule data is already in shape for it to consume.
- [ ] Block-off slots (lunch / training / personal holds created from the calendar) — leans on `ScheduleException`.
- [ ] Mobile-responsive scheduler grid (front desk on iPad) — works in a pinch today via horizontal scroll; needs proper responsive treatment.

**Calendar workspace command center** — the calendar is the front-desk's primary screen, so all day-to-day tools hang off it via a right-side icon rail with slide-out panels. Some are wired live now; most are placeholders that fill in as the underlying features ship.

- [x] Top-bar **client search** with live results dropdown — typing surfaces matching customers, click to view profile (completed 2026-04-30 session 1.5)
- [x] **Filter row** — provider dropdown + hide cancelled / no-show toggle (completed 2026-04-30 session 1.5)
- [x] **Right tool rail** — 8 tools, active tool persisted in `?tool=` URL state, slide-out panel pushes the calendar (completed 2026-04-30 session 1.5)
- [x] **View Settings panel** (functional) — density (comfortable / compact) and list-view toggle (completed 2026-04-30 session 1.5)
- [x] **Price Check panel** (functional) — quick service lookup with price + category + duration (completed 2026-04-30 session 1.5)
- [ ] **Messages panel** — unified inbox of SMS, Instagram, Facebook, WhatsApp threads (placeholder; lights up with Phase 3A two-way SMS + 3B social DM integrations)
- [ ] **Employee check-in panel** — staff clock in / clock out + today's hours (placeholder; lights up with Phase 2I time tracking)
- [ ] **Waitlist panel** — add a guest to the waitlist when their preferred slot is taken; auto-notify on cancellation (placeholder; lights up with Phase 4F)
- [ ] **Daily reports panel** — for the focus date: summary, sales, collections, tips, prescription orders (placeholder; lights up with Phase 1G + Phase 4D + Phase 2A)
- [ ] **Online bookings panel** — list of appointments booked through the public site for the focus date, with conflict-check call-out (placeholder; lights up with Phase 1I)
- [ ] **Custom packages panel** — build a per-customer package (services + products + memberships, expiration), creates an invoice, opens POS for payment (placeholder; lights up with Phase 2B packages + 2A POS)

#### 1D. Forms & e-signature

*Three-session feature. Session 1 ships the template management surface; Session 2 adds the tokenized public fill flow + auto-assignment; Session 3 wires submissions into the customer chart with PDF generation.*

**Session 1 ✅ (completed 2026-05-02): Template management**
- [x] **`apps.forms` Django app** with `FormTemplate` (tenant-scoped, name, description, `form_type` intake|consent, `recurrence` once|per_visit, `schema` JSON, `version` auto-bump, `is_active`) + `ServiceFormAssignment` (consent ↔ service mapping). Migration applied.
- [x] **`/api/form-templates/`** — full CRUD ModelViewSet. Read open to anyone in the tenant; write gated by `MANAGE_TENANT_SETTINGS` (owner-only). DELETE intentionally not exposed (submissions FK in; soft-delete via `is_active=false`). Hard JSON-schema validation: 6 field types in v1 (`short_text`, `long_text`, `choice_single`, `choice_multiple`, `date`, `signature`), unknown types rejected, choice fields require ≥2 distinct options, duplicate field-ids rejected, unsafe field-id chars rejected.
- [x] **`set_service_ids` PATCH/POST field** for replacing the consent form's service mapping (full-replace, mirrors `set_location_ids`). Cross-tenant guard. Intake forms reject service mappings (auto-assign via "first appointment ever," not service rules) — explicit error.
- [x] **`version` bumps only on actual schema change** — comparing canonical normalized form so cosmetic edits (rename, recurrence change) don't bloat the version count. Audit metadata records before/after version + field count diff.
- [x] **24 new backend tests** covering CRUD + permission gating + tenant scoping + JSON-schema validation (each rejection path) + service-mapping replace + version-bump behavior + DELETE-405. **164/164 total backend tests passing.**
- [x] **`lib/form-templates.ts`** — types (FormType, Recurrence, FormField discriminated union per type, FormTemplate, etc.) + hooks (useFormTemplates, useFormTemplate, useCreateFormTemplate, useUpdateFormTemplate). Display helpers + `defaultField()` factory for the builder.
- [x] **`/org/forms`** list grouped by form type with per-row badges (version, field count, recurrence label, service-mapping count or "Not mapped" warning for consent forms). Empty-state CTAs link to `/org/forms/new?type=...` so the type pre-fills.
- [x] **`/org/forms/new` + `/org/forms/[id]`** share `<FormTemplateBuilder>`: identity section (name/description/form_type/recurrence/active toggle), service multiselect (consent only — auto-clears on switch to intake), and inline schema editor (per-field config, up/down reorder, +/− add/remove, choice-options sub-editor). Client-side validation mirrors backend (disable Save with summary panel of issues). "Will bump to vN+1" hint on the edit page when schema changes are pending.
- [x] **Sidebar Org sub-menu** adds Forms entry (owner+manager visible).

**Sessions 2 + 3 ✅ (completed 2026-05-03): Tokenized fill flow + auto-assignment + chart visibility**

*Combined into one delivery because the workflow needs all of it to be useful (assignment + fill + visibility on the chart). ADR-0011 written at design time before the implementation per the discipline locked in after ADR 0008.*

- [x] **`FormSubmission` model** — tenant-scoped, snapshots `schema_snapshot` (full schema JSONB) and `template_version_at_assignment` so post-assignment template edits don't change in-flight pending submissions OR signed history. Token defaults to `secrets.token_urlsafe(32)` (~256 bits). Status enum: `pending` / `completed` / `voided`. PHI fields: `answers` (JSONB), `signature_data` (base64 PNG). Audit fields: `signed_at`, `ip_address`, `user_agent`, `voided_at`, `voided_by`, `voided_reason`. PROTECT FK on customer + template so submissions outlive retirement. Indexes on `(tenant, customer, status)` + `(tenant, appointment, status)`.
- [x] **`forms.services.assign_forms_for_appointment()`** — explicit service call (NOT a Django signal — see ADR 0011) wired into `AppointmentViewSet.perform_create` after the appointment + audit log are written. Logic: intake auto-assigned on a customer's FIRST appointment ever; consent assigned per `ServiceFormAssignment` mapping for the appointment's service. Recurrence rules respected — `once` skips when a completed submission exists for this customer; `per_visit` always creates a new pending. Pending-duplicate guard prevents two pending intakes when concurrent first-appointments race.
- [x] **`/api/form-submissions/`** tenant-scoped: list (filter by `?customer=`, `?appointment=`, `?status=`), retrieve (PHI; gated). Audit-logged on every detail read for HIPAA §164.312(b). `POST /api/form-submissions/{id}/void/` requires owner+manager + a non-empty reason; double-void rejected.
- [x] **`POST /api/forms/sign/<token>/`** public unauthenticated fill endpoint. CSRF-exempt (token IS the security boundary; ADR 0011 explains the rationale). GET returns the schema snapshot + status; POST validates answers against the snapshot (required fields populated, choice values matching options) and atomically transitions `pending` → `completed`. Captures IP from `X-Forwarded-For` + user-agent server-side; never trusts the client to supply audit data. Subsequent POSTs to a completed submission return 409; voided returns 410.
- [x] **21 new backend tests** covering: auto-assignment rules (intake + consent + recurrence + voided + concurrent-race fence + inactive-template skip), end-to-end booking-creates-submission via the appointment API, list/detail/void with cross-tenant 404, double-void rejection, public GET schema, public POST sign with audit capture, missing-required-answer rejection, invalid-choice-value rejection, double-sign-409, voided-410. **185/185 total backend tests passing.**
- [x] **Frontend `lib/form-submissions.ts`** — `useFormSubmissions` (per-customer / per-appointment / per-status), `useFormSubmission` (detail; PHI), `useVoidSubmission`, `usePublicSubmission` (no auth), `useSubmitPublicForm`. Display helpers (`statusLabel`, `statusTone`).
- [x] **`<SignatureCanvas>` component** — touch + mouse + stylus via `PointerEvents`, device-pixel-ratio scaled for crisp lines on iPad/retina, `touch-action: none` so iOS doesn't intercept the draw as a scroll. Exposes `getSignatureDataUrl()` + `clear()` via ref. Forward-compat with the future Apple-Pencil flow.
- [x] **`/sign/[token]` public route** (outside `(app)` group so no auth gate, no sidebar; mobile-first layout). Renders the schema as a fillable form with type-appropriate controls (short_text, long_text, choice_single, choice_multiple, date, signature). Three states: pending (fill view), completed (read-only signed view), voided (clear "contact the spa" message). Client-side required-field validation mirrors the backend so submission errors are inline before round-trip.
- [x] **Customer profile Forms tab** wired from placeholder to real list. Three groups (Pending / Signed / Voided) with per-row "Open for signing" or "View signed" actions that open the tokenized URL in a new tab — same flow whether the spa shares the link via email (when Phase 1F lands) or hands an iPad to the client.
- [x] **Appointment popover Forms section** — surfaces pending + completed forms relevant to this appointment context (any intake for the customer + appointment-pinned consents). Pending forms get a prominent amber-tinted "Open for signing" button. Hidden entirely when there are no submissions to surface.

**Email follow-up ✅ (completed 2026-05-03): Operator-initiated signed-form copy**

*[ADR 0012](../docs/decisions/0012-email-infrastructure-and-signed-form-copy.md) lays out the full design — BAA path via AWS SES in production, console backend in dev (no accidental real sends), why operator-initiated rather than auto-on-signing (per-customer email-PHI consent isn't built yet), audit logs the recipient's DOMAIN only.*

- [x] **Django email config** — `EMAIL_BACKEND` + `DEFAULT_FROM_EMAIL` + `PUBLIC_BASE_URL` env-driven. Dev defaults to `console.EmailBackend` (prints emails to runserver terminal). Production switches to `django_ses.SESBackend` via env in Phase 0c — no code change.
- [x] **HTML + plain-text email templates** in `apps/forms/templates/forms/email/signed_copy.{html,txt}`. Inline styles for cross-client compatibility; pill+headline+answers+link layout. Plain-text fallback required (accessibility + non-HTML clients).
- [x] **`POST /api/form-submissions/{id}/email/`** endpoint. Owner+manager via `MANAGE_STAFF`. Rejects pending/voided submissions (must be signed); rejects when customer has no email on file. Audit log records `event: 'emailed_to_customer'`, `template_id`, and `recipient_email_domain` ONLY — full address never logged because it'd accumulate PHI in the audit trail.
- [x] **8 new backend tests** covering: HTML + plain-text parts both present, audit log records domain not full address, pending/voided/no-email rejected with clear messages, front-desk forbidden, cross-tenant 404, double-send works (each creates audit entry — bounce dedup is Phase 0c). **193/193 total backend tests passing.**
- [x] **`useEmailSubmission()` hook** in `lib/form-submissions.ts` — minimal POST to the email endpoint.
- [x] **"Email signed copy" button** on completed submissions in two places: customer profile Forms tab (full button with Mail icon) + appointment popover Forms section (compact text button). Both use a two-click confirm pattern ("Email" → "Cancel | Confirm send") so accidental clicks don't fire PHI emails. Toast on success names the recipient.

**What's still future (PHI-email roadmap):**
- [ ] **AWS SES wiring + BAA verification** — Phase 0c: confirm AWS account is BAA-signed, SES domain verification, DKIM/SPF/DMARC, SNS bounce/complaint webhooks.
- [ ] **Per-customer email-PHI consent + auto-on-sign** — intake form gains an "OK to email me PHI" field; signed submissions auto-email when the flag is True. Avoids the operator-confirms-each-time friction once the consent model is in place.
- [ ] **PDF attachment** — server-side render of the signed submission (WeasyPrint). Currently HTML inline + link.
- [ ] **Pending-form invitation emails** — "Hi, you have a form to sign before your appointment, click here." Same template engine; needs the operator-asks-customer-to-fill flow + per-customer consent. Phase 1F.
- [ ] **SMS reminders / form-link delivery** — full Phase 1F territory; needs Twilio + per-tenant phone provisioning + TCPA opt-in/opt-out + scheduled sending.

**Other Forms polish (not email-related):**
- [ ] **PDF generation** for signed submissions (server-side render, WeasyPrint or similar). Customer profile shows "Signed" + read-only view today; downloadable PDF is a follow-up.
- [ ] **Token expiry policy** — v1 tokens live forever until status flips. Polish item: invalidate when the related appointment is cancelled or > N days past.
- [ ] **Minimum-necessary refinement** on the detail endpoint — v1 lets any authenticated tenant member read full PHI (answers + signature). Refines to clinical-only (`VIEW_CLIENT_PHI` permission) when the permission catalog supports it. HIPAA §164.502(b).
- [ ] **Image / file upload field types** — needs S3 in prod (Phase 0c).
- [ ] **Conditional field logic** ("show field B only if answer to A is yes") — polish.
- [ ] **`X-Frame-Options: DENY` + CSP `frame-ancestors 'none'`** on the public sign route to block embedding attacks. Phase 0c middleware.
- [ ] **Re-issue UX** — operator must void + manually trigger a new submission today. Polish: an "Issue another" button on the customer chart.

**Out of scope for the whole feature:**
- [ ] Image / file upload field types — deferred (needs S3 in prod).
- [ ] Conditional logic ("show field B only if answer to A is yes") — polish.
- [ ] Drag-and-drop field reordering — polish (up/down works for v1).
- [ ] Email/SMS delivery of tokenized link — depends on Phase 1F (SES + Twilio).

#### 1E. Invoicing (without payment processor for now)
*Foundations pulled forward during Phase 1C session 2 — the calendar's
"Take Payment" / completion-gate workflow needed something to gate
against. ADR 0007 documents the design (one invoice per appointment;
closing the invoice is the only path to `Appointment.status =
COMPLETED`; owners + managers may reopen within 60 days; locked
permission, full audit trail).*

**Shipped ✅ (2026-05-02):**
- [x] **`apps.invoices` Django app** — `Invoice` (tenant-scoped, FK customer + 1:1 appointment, OPEN/PAID/VOID, money in cents, `closed_at` set on first close and immutable, `reopen_count`, full audit who/when fields) + `InvoiceLineItem` (snapshots service name + price + tax rate at line-create time so historical lines never change when service prices update).
- [x] **Invoice auto-created** when an appointment is booked (post_save signal, atomic with the appointment row).
- [x] **Line items** with snapshot pricing — currently one line per appointment; multi-line / add-ons land with Phase 2A POS.
- [x] **State machine: OPEN → PAID → OPEN (reopen, ≤60d) → PAID; OPEN → VOID** with select_for_update locking on every transition.
- [x] **Mark invoice paid (cash / check / card-external / other)** with optional payment reference. Closing the invoice atomically transitions the linked appointment to `completed`.
- [x] **Permissions** — `PROCESS_PAYMENT` for close (owner/manager/front_desk), `VOID_INVOICE` for void (owner/manager), new `REOPEN_INVOICE` for reopen (owner/manager only, **locked** against per-user override for separation of duties).
- [x] **DB CheckConstraints** for data integrity: `total_cents = subtotal_cents + tax_cents`, PAID requires `closed_at`, VOID requires `voided_at`, line `subtotal = quantity × unit_price`.
- [x] **API surface** at `/api/invoices/` — list/retrieve + `POST /<id>/close/` / `/<id>/reopen/` / `/<id>/void/` actions. Generic `POST/PUT/PATCH/DELETE` on the collection is intentionally rejected so all mutations go through audit-logged paths.
- [x] **Backfill migration** — every pre-existing appointment gets an invoice (PAID for `completed`, VOID for `cancelled`/`no_show`, OPEN otherwise), with audit-log entries tagged `source: backfill_migration_0002` for traceability.
- [x] **Frontend invoice page** at `/appointments/[id]/invoice` — line items table, totals breakdown, payment/lifecycle metadata, Take Payment / Reopen / Void controls (forms expand inline). Opened from the calendar popover's "Take payment" CTA in a new tab; supports `?action=pay` deep-link to auto-focus the payment form.
- [x] **25 backend tests** covering: signal creates invoice, close transitions appointment, double-close rejected, cancelled appointment can't be paid, reopen permission gate, 60-day window enforcement, `closed_at` immutability across re-closes, void rules, tenant isolation, audit entries written.
- [x] **Invoice status pill** visible on the appointment popover (compact: status + total + Take Payment CTA). Invoice status appearing on the calendar block itself is deferred — the popover already surfaces it on click.

**Still to ship for Phase 1E:**
- [x] Invoice number sequencing per tenant — shipped 2026-05-02 (concurrency-safe via `select_for_update` in `apps.invoices.services.generate_invoice_number`; INV-YYYY-NNNN format; resets annually; per-tenant unique constraint).
- [x] Invoice PDF generation — shipped 2026-05-12. Renderer in `apps.invoices.services.render_invoice_pdf` (reportlab platypus, pure Python, ~10ms render). Endpoint `GET /api/invoices/{id}/pdf/` with audit log + tenant scope. Frontend Download button on the invoice page. On-demand projection of the row — no caching. See [ADR 0018](docs/decisions/0018-invoice-pdf-rendering.md). 8 new tests.
- [x] Invoice status badge on the calendar block — shipped 2026-05-12. Small green check pill in the top-right of each block when the linked invoice is `paid`. Backend exposes `invoice_status` on `AppointmentSerializer` via the reverse OneToOne; viewset adds `invoice` to `select_related` (no N+1). Renders for PAID only — OPEN is the default state (showing it everywhere dilutes the signal), VOID already shows as cancelled-styled blocks. Hidden on `tightVertical` blocks to avoid crowding the time text.
- [x] Email invoice to client — shipped 2026-05-12. `send_invoice_email` service renders the PDF via [[0018-invoice-pdf-rendering]] and attaches it to a transactional email through Django's mail backend (django-ses in prod). `POST /api/invoices/{id}/email/` action gated by `PROCESS_PAYMENT`. Confirmation dialog on the invoice page; button disabled with tooltip when the customer has no email on file. 8 new tests including roles, missing-email validation, audit log, cross-tenant isolation, no-dedup-on-repeat-sends.
- [ ] Refund workflow (manual, ledger-tracked) — partially covered by reopen+void; explicit refund flow with negative amounts is Phase 2A territory.

#### 1F. SMS appointment reminders
- [ ] Twilio integration with BAA
- [ ] Reminder schedule: 48h before, 2h before (configurable per tenant)
- [ ] Confirm/cancel via SMS reply (basic)
- [ ] Opt-in/opt-out compliance (TCPA)
- [ ] Per-tenant phone number provisioning

#### 1G. Reporting
*User bar set explicitly: "we are not shipping until we can have all reports on
everything possible." Phase 1G stays open until Sessions 1–3 are all
shipped — Session 1 lands the architecture + a proof report per
category; Sessions 2 + 3 fill out the catalog and add CSV export.*

**Session 1 ✅ (completed 2026-05-03): Architecture + first report per category**
- [x] **ADR 0013** — module architecture (one APIView per report, OLTP not warehouse, category-level permissions, PHI tiers, audit-log shape, session sequencing). Written at design time before any code.
- [x] **`apps.reports` Django app** — `BaseReportView` with date-range parsing + permission gating (via new `ReportPermission`) + audit logging. Each report sets `report_id`, `category`, `permission`, `title`, `description`, `phi_tier` and implements `run()`. No models — thin aggregation layer over OLTP tables.
- [x] **Three new permissions** in `P` — `VIEW_STAFF_REPORTS`, `VIEW_GUEST_REPORTS`, `VIEW_OPERATIONS_REPORTS`. Existing `VIEW_FINANCIAL_REPORTS` and `VIEW_MARKETING_REPORTS` reused. Default role coverage: bookkeeper gets staff (commission reconciliation); marketing gets guests (birthday lists, inactive clients); front_desk gets operations (day-of-business view).
- [x] **Three starter reports — one per starter category:**
  - **Financial · Sales by date range** — daily gross/tax/subtotal/invoice count + payment-method breakdown. Excludes voids and unpaid invoices. Source: PAID invoices closed in window.
  - **Staff · Revenue by provider** — gross + paid-appointment count per provider, ranked. Source: PAID invoices joined to provider via appointment. Standalone POS invoices (no appointment) excluded — they get their own report when Phase 2A POS lands.
  - **Guests · New vs returning** — per-customer classification (`new` if first-ever appointment in window, `returning` if had any appointment before AND in the window). Cancellations + no-shows count as visits for classification (the question is "did they cross the door"). PHI tier: `per_customer`.
- [x] **Catalog endpoint** at `/api/reports/` — returns categories + reports the current user can run. Server-side permission filtering; categories with zero accessible reports omitted entirely. Drives the frontend library page so the UI never duplicates permission logic. Operations + Marketing categories register but have zero reports until Session 2.
- [x] **31 backend tests** covering: envelope shape, date-range parsing + validation, aggregation correctness, void/unpaid exclusion, payment-method breakdown, classification rules, status-agnostic visit counting, catalog filtering by role (owner / front_desk / bookkeeper / marketing), per-report permission gating, tenant isolation across all three reports, audit-log shape with the no-PHI-in-metadata regression guard. **224/224 total backend tests passing.**
- [x] **Frontend reports library** at `/reports` — categorized cards driven by the catalog endpoint. PHI-tier pill on every report card. Empty-state when the user's role gates them out of every category.
- [x] **Three report detail pages** — each composes the same `ReportShell` (back-to-library breadcrumb, date-range picker with 6 presets + custom range, summary tile row, per-report sections). PHI badge on Staff report; PHI banner on Guests report.
- [x] **Sidebar** — Reports flipped from `comingSoon: true` to live.

**Session 2 ✅ (completed 2026-05-03): Fill out the catalog — 18 new reports**
- [x] **Financial (5 new):** Daily close-out (per-day gross + per-payment-method split for cash-drawer reconciliation; refund column blocked on Phase 2A), AR aging (snapshot of OPEN invoices bucketed current/30/60/90/90+, per-customer drill-down — PHI tier per_customer), Revenue by service (sum of PAID line items grouped by service, ranked highest-first), Revenue by location (PAID invoices grouped by appointment.location for multi-location tenants), Tax collected (per-rate breakdown + effective rate, for sales-tax filing prep).
- [x] **Staff (4 new):** Schedule utilization % (delivered ÷ scheduled minutes, walks day-by-day across each provider's `weekly_hours` JSON; cancellations + no-shows excluded from "delivered"), No-show rate by provider (count + rate per provider, ranked), New clients acquired by provider (count of clients whose first-ever appointment was with this provider in the window — marketing/commission attribution), Repeat rate by provider (lifetime metric: of every unique client a provider saw, what share returned for a 2nd+ visit).
- [x] **Guests (5 new):** Top spenders LTV (lifetime PAID-invoice total per customer, top-N with configurable limit, ranked — PHI), Inactive clients (no visit in N days with preset chips 30/60/90/180/365; "never visited" customers anchor on created_at to avoid day-1 staleness — PHI), Birthday list (year-agnostic upcoming birthdays with configurable window 7-90 days, includes opt-in flag — PHI), Visit frequency (lifetime histogram bucketed 1 / 2-5 / 6-10 / 11+ visits; counts only completed/checked-in), Forms outstanding (per-customer count of pending FormSubmission rows — front desk's pre-arrival paperwork chase list — PHI).
- [x] **Operations (6 new):** Appointments by status (counts grouped by booked/confirmed/checked_in/completed/no_show/cancelled), No-show rate overall (rate + per-day breakdown), Cancellation rate (rate + per-day breakdown), Booking lead time (histogram bucketed same-day / 1-3 / 4-7 / 8-14 / 15-30 / 31+ days plus average; backfilled appointments excluded), Service mix (appointment counts per service, all statuses), Busiest hours / days (weekday × hour heatmap with peak-hour and peak-weekday summary tiles).
- [x] **Catalog now serves 22 reports** across 4 populated categories (Financial 6 / Staff 5 / Guests 6 / Operations 6); Marketing remains Phase 3. Per-category permissions unchanged from Session 1.
- [x] **Shared `ReportTable` component** + `controls` slot on `ReportShell` (lets reports surface non-date params like inactive-days threshold, top-spender limit, birthday window) so 18 new pages compose down to ~50 lines each.
- [x] **11 new backend tests** (42 reports tests total): per-endpoint smoke (200 + envelope + audit-log entry across all 18 new reports via subTest), permission gating (front_desk allowed for operations, blocked from top-spenders; marketing allowed for birthday list), input validation (top-spenders limit, inactive-clients days, birthday window), tenant isolation on per-customer-PHI reports (top spenders + AR aging). **235/235 total backend tests passing.**
- [x] **Smoke-tested against real seed data** — all 23 endpoints return 200 with correct row counts (financial 30 days × 4 invoices, 3 providers ranked by revenue, etc.).

**Session 3 ✅ (completed 2026-05-03): CSV export + PHI confirmation**
- [x] **Server-rendered streaming CSV** on every report endpoint via `?download=csv` (single source of truth — never client-built). `BaseReportView._export_csv()` uses `StreamingHttpResponse` so a 100k-row export doesn't load fully into memory. Header row auto-derived from first row's dict keys (title-cased) by default; reports with nested data override `csv_rows()` + `csv_columns()` (daily close-out flattens per-payment-method into individual columns instead of JSON-stringifying the dict).
- [x] **DRF query-param sidestep** — used `?download=csv`, NOT `?format=csv`, because DRF reserves `format` for content negotiation and 404s any value without a registered renderer. Documented in `base.py` so future-me doesn't trip on it again.
- [x] **PHI confirmation gate** — `per_customer` tier reports require `?phi_confirmed=true`; without it the endpoint returns 403 with `{code: 'phi_confirmation_required', phi_tier: 'per_customer'}` so the frontend can detect the specific gate (vs. a generic permission denial). Five truthy values accepted (`true`, `1`, `yes`, `on`, case-insensitive); everything else blocks.
- [x] **EXPORT audit entries** — `AuditLog.action=EXPORT` distinguishes downloads from on-screen reads, with `metadata={category, params, row_count, phi_tier, phi_confirmed}`. The `phi_confirmed` flag answers the SOC 2 reviewer's "did the operator click through the PHI prompt" without re-deriving from the URL. CSV exports never write a duplicate READ entry; one request, one entry.
- [x] **Frontend confirmation modal** — `ExportCsvButton` opens a Base UI Dialog for `per_customer` tier reports with the warning "This export contains client names, contact info, and treatment data… By downloading, you confirm this access is necessary for spa operations." Includes a soft-tinted note that the download will be logged with the operator's name. For `none`/`aggregated` tiers the button downloads immediately.
- [x] **Fetch + Blob download path** (not `<a href>`) — browser-initiated navigation skips our custom `X-Tenant-Slug` header which the dev backend needs to resolve the tenant. Frontend fetches with `credentials: 'include'` + the header, turns the streaming response into a Blob, then triggers a programmatic anchor click against the object URL. End-user UX is identical (OS download dialog).
- [x] **Wired across all 22 report pages** via `ReportShell`'s new `exportPath` + `exportParams` props. The shell stitches the date range and any non-date params into the export URL automatically; per-page wiring is one prop per page.
- [x] **12 new backend tests** covering: no-PHI report downloads CSV with right Content-Type + filename; aggregated-PHI downloads without confirm; per-customer blocked without confirm (with the `phi_confirmation_required` code); per-customer allowed with confirm; truthy/falsy phi_confirmed values; EXPORT audit entry written with full metadata; per-customer audit records `phi_confirmed: True`; CSV does NOT also write a READ entry; daily-close-out custom columns (4 payment methods break out, no `by_method` JSON column); filename includes the date range; category permission still gates the export. **54 reports tests, 247/247 total backend tests passing.**

**Phase 1G ✅ COMPLETE (2026-05-03)** — 22 reports across 4 categories, full CSV export with PHI gate, audit-logged top-to-bottom. The user's "all reports on everything possible" bar met for the launch cut. Polish backlog (Session 4) below is post-launch.

**Session 4 (post-launch polish — deferred):**
- [ ] Saved report views (per-tenant + per-user; stores report ID + frozen params).
- [ ] Scheduled email delivery (depends on Celery beat — Phase 1F — and SES wiring).
- [ ] Drill-down navigation between related reports (e.g. provider card → that provider's appointments).
- [ ] Per-tenant timezone bucketing for `closed_at__date` filters (currently UTC; ≤2-day boundary drift acceptable at launch).
- [ ] Materialized views for any report that exceeds 2s at p95 in production.

#### 1H. Tenant settings

**Session 1 ✅ (completed 2026-05-02):**
- [x] **Tenant model** gained `logo_url` (URLField, blank ok); `primary_color` help text clarifies "client-facing surfaces only" (login + booking page; staff CRM keeps the consistent Lumè look). Migration applied.
- [x] **`GET/PATCH /api/tenant/`** — singleton endpoint for the *current* tenant (resolved by subdomain / X-Tenant-Slug). Edit gated by `MANAGE_TENANT_SETTINGS` (owner-only by default). Audit-logged with `fields_changed`.
- [x] **`PATCH /api/memberships/{id}/`** — staff role / `is_active` / `is_bookable` / `job_title_id` editable. Gated by `MANAGE_STAFF`. Audit-logged with before/after on each changed field. Create + destroy explicitly disallowed (member additions go through future invite flow; deactivation via `is_active=false` preserves audit trail).
- [x] **Last-active-owner guardrail** — cannot demote or deactivate the only remaining active owner. Backend enforces via 403; frontend mirrors as a disabled control + tooltip so the destructive button never tempts a click in that state.
- [x] **16 backend tests** covering tenant read/update + permission gating + slug read-only + cross-tenant blocked + membership PATCH + last-owner guardrail + audit metadata + create/destroy disallowed (41/41 total backend tests passing).
- [x] **`/settings/business` page** — owner-editable business profile + branding form. Includes a "Your portal: `{slug}`.lumecrm.com" read-only banner so the owner knows what URL to share with their team. Address fields tucked behind an "Add address details" expander (auto-opens if any field is populated). Branding section has an explicit explainer that logo + color show on login + booking page only, not the staff CRM.
- [x] **`/settings/staff` page** — staff list with inline role Select, bookable toggle, deactivate (with inline confirm), and reactivate. "Show inactive" toggle in the page-header actions slot. Search bar over name + email. Owners get a special chip + role-change is locked out from the inline dropdown (would need a deliberate flow). Last-active-owner guardrail mirrored client-side.
- [x] **Sidebar Settings entry** — enabled with sub-menu (Business / Staff). Sub-links visible only when on a `/settings` route, indented under the parent with a left rule + accent border on the active child. Each sub-link is role-gated (Business → owner only, Staff → owner + manager) so users only see entries they can actually use.

**Session 2 ✅ (completed 2026-05-02):**
*Staff is now its own top-level menu (Employees / Schedule / Check-in / Payroll). Adding + editing employees is fully wired end-to-end so onboarding a new spa no longer needs Django admin.*
- [x] **`User` model** gained personal contact fields: `phone`, `address_line1/2`, `city`, `state`, `zip_code`. These live on User (not membership) so the same person at multiple spas keeps one canonical contact record. Migration applied.
- [x] **`TenantMembership` model** gained employment + payroll fields: `employment_type` (full-time / part-time / contractor), `pay_type` (hourly / salary / commission_only), `pay_rate_cents` (integer to dodge float rounding), `hire_date`, `employment_notes`. Per-tenant because the same person can have different terms at each center. Migration applied.
- [x] **`POST /api/memberships/`** — owner + manager (`MANAGE_STAFF`) can add a new employee. Looks up by email case-insensitively: existing User → attached as a new membership (no password churn); brand-new User → created with a `secrets.token_urlsafe(12)` temp password returned **once** in the response. Race-safe via `transaction.atomic` + `IntegrityError` → 409 on duplicate. Audit-logged with `attached_existing_user` flag.
- [x] **`MembershipDetailSerializer`** — full read/write for the per-employee page. Nested user updates (e.g. `user_first_name`) handled via `source='user.field'` + a custom `update()` that pops `validated_data['user']` and saves the User in the same transaction. `user_email` is read-only on PATCH (changing identity needs a re-verification flow, polish backlog). The compact `MembershipSerializer` used by the calendar is unchanged so payroll never leaks into provider-column responses.
- [x] **11 new backend tests** covering: add brand-new employee returns temp password, attach existing user returns no password, email lookup case-insensitive, duplicate membership rejected with 409, front-desk forbidden, cross-tenant `other_memberships` read works (slated for replacement by real multi-location assignments in Phase 4E session 5), owner can update user contact + payroll in one PATCH, email read-only on PATCH. **52/52 total backend tests passing.**
- [x] **Business hours editor** — `business_open_time` + `business_close_time` `TimeField`s on Tenant with a `TimePicker` editor on `/settings/business`. The calendar's `DayView` now reads these via props (`dayStartHour` / `dayEndHour`) instead of hard-coded `DAY_START_HOUR` / `DAY_END_HOUR` constants, so each tenant's day axis matches their actual hours. Threaded through `ProviderColumn` → `AppointmentBlock`.
- [x] **Sidebar restructure** — Staff promoted out of Settings into its own top-level menu with sub-items (Employees / Schedule / Check-in / Payroll). Settings sub-menu trimmed to just Business (owner only). Members renamed to Employees per user feedback.
- [x] **`/staff/employees` Add employee button** — owner + manager only. Opens a bottom sheet (`AddEmployeeSheet`) with first/last/email/role/optional job title/bookable. On success: brand-new user → swap to a "share these credentials" panel with one-click copy; existing user → toast + close.
- [x] **`/staff/employees/[id]` profile page** — five sections: Role & access · Personal contact · Employment · Payroll · Multi-center · Notes. Two-column layout matching `/settings/business`. All fields edit-gated to owner + manager (non-managers see read-only). Pay rate UI is dollars; the wire format is cents. `commission_only` zeroes out the rate. **Note (2026-05-02 follow-up):** the Multi-center section currently lists cross-tenant memberships, which is the wrong concept for "spas with multiple physical locations." Phase 4E session 5 swaps it for real per-location assignments scoped to this tenant.

**Session 3 (later):**
- [ ] Cancellation policy text
- [ ] Notification templates (SMS reminder copy, etc.) — lights up with Phase 1F (SMS / email plumbing)
- [ ] Job title inline edit on `/staff/employees/[id]` — currently the field is read-only on the profile page; new-employee flow already accepts it. Lift into a small Select once tenants start customizing job-title lists.
- [ ] Staff invitation flow (email tokenized link → set password → join tenant) — replaces the temp-password reveal panel once SES lands (Phase 1F).
- [ ] Logo upload (S3 in prod, local FS in dev) — currently URL paste only; tracked in polish backlog

#### 1J. Zenoti migration tooling
*One of the two launch spas is migrating from Zenoti with 7,000+ clients, package balances, service history, and forms. Migration must be precise — lost package balances or service-history gaps are real liability.*

- [ ] New `apps/imports` Django app
- [ ] `zenoti.py` importer module — maps Zenoti CSV/API exports to our models
- [ ] Provenance fields on Customer, Package, Membership, Appointment, etc.: `external_id`, `external_source`, `imported_at`
- [ ] Dry-run mode — counts and validation without writes
- [ ] Idempotent — re-running on the same export is safe (upsert on `external_id`)
- [ ] Two-pass: full validation, then writes only if validation passes
- [ ] Per-row error log surfaced to spa staff for manual cleanup
- [ ] `AuditLog` entries tagged `metadata.source='zenoti_import'`
- [ ] Photo/document import for consent forms and before/after galleries (S3 once Phase 0c lands; local for dev)
- [ ] Reconciliation report: counts of clients / packages / service-history rows imported vs. expected
- [ ] **Action:** ask migrating spa to open Zenoti support ticket for full export; get a 30-day sample first to lock down the schema

#### 1K. Messaging integrations (Meta channels — paused on external dependency)
*Unified inbox for Facebook Page Messenger, Instagram Business DMs, and WhatsApp Business so customer messages land in Lumè and the spa can book directly from a conversation. Modeled on Podium's pattern — single OAuth grant from Meta, webhooks deliver messages, replies route back to the originating channel.*

**Session 1 ✅ (completed 2026-05-04): Foundation — model + permissions + settings page**
- [x] **`apps.integrations` Django app** — `Connection` model (tenant + provider + status + auth_data + external_id + last_synced_at + last_error_*), partial unique constraint per (tenant, provider). Tokens are placeholder JSON until Session 2 wires real OAuth; field-level encryption via `cryptography.fernet` lands at the Phase 0c production lift (one-line model swap).
- [x] **`MANAGE_INTEGRATIONS` permission** added to the catalog. Owner + manager by default. Locked against per-user override (broad OAuth scopes are role-level, not casual grants).
- [x] **Provider registry** in `providers.py` — single source of truth for display name, what-this-enables copy, OAuth scopes per provider (Meta App review submission uses the exact same scope list).
- [x] **3 endpoints** — `GET /api/integrations/` (list providers + connection state), `POST /<provider>/connect/begin/` (501 with `code='oauth_not_ready'` until Session 2), `POST /<id>/disconnect/` (fully wired today). Audit-logged with `resource_type='integration_connection'`.
- [x] **14 backend tests** covering permission gating, list shape, connect-begin placeholder, disconnect lifecycle, tenant isolation. **301/301 total backend tests passing.**
- [x] **`/org/integrations` page** in Organization sidebar (owner+manager only) — three provider cards with status pill, "what this enables" bullets, Connect button (currently triggers friendly "awaiting Meta App approval" toast), two-click confirm on Disconnect.

**External work — paused on Meta App approval pipeline (paused 2026-05-04)**

User started Meta App registration. Status as of pause:
- ✅ Meta App created with type "Business"
- ✅ Messenger product added (webhook config skipped — Meta allows it)
- ⏸ Instagram + WhatsApp products NOT yet added — Meta's UX requires a working webhook URL upfront for these two, which we don't have until production deployment (Phase 0c) or a sustained ngrok tunnel
- ⏸ Business Verification not yet submitted
- ⏸ Privacy Policy + Terms URLs not yet on Meta App settings (depend on `/privacy`, `/terms` pages on the marketing site, which are themselves still placeholder routes)
- ⏸ App Review for `pages_messaging`, `instagram_business_*`, `whatsapp_business_*` scopes — blocked on the above

**To resume (probably after Phase 0c production deployment):**
1. Production backend deployed at `https://api.lumecrm.com` so Meta has a real callback URL to point at
2. Build webhook receiver: `POST /api/integrations/webhooks/meta/` with hub-challenge verification + signed-payload validation
3. Add Instagram + WhatsApp products to the Meta App with the real callback URL
4. Submit Business Verification + Privacy Policy / Terms URLs (these depend on `marketing/` legal pages being filled in)
5. App Review for the messaging scopes (2-6 weeks each)
6. Wire OAuth flow + token storage with field-level encryption
7. Build unified inbox UI

**Why we paused:** Pushing ahead would require either (a) deploying production prematurely just to satisfy Meta's webhook URL requirement, or (b) running an ngrok tunnel for the duration of Meta's 2-6 week review pipeline. Both are wasteful when the underlying webhook receiver code doesn't exist yet. Cleaner to come back when production is deployed and we have all three products' webhook URLs ready in one shot.

#### 1I. Online booking — hosted page (client-facing)
*Public-facing booking page per tenant. No login required for customers. URL like `acmespa.lume-crm.com/book` — tenants share it from Instagram bio, email signature, business cards, anywhere. This is the v1 customer-facing booking experience.*

- [x] Public booking route per tenant (no authentication required) — `/book/<slug>` route group, no auth gate
- [x] Tenant-branded landing (logo, primary color, business info, address, hours)
- [x] Service catalog browse (only services flagged "bookable online")
- [x] "Any available provider" + specific-provider selection
- [x] Real-time availability calculation (provider working hours − booked − blocked-off, respecting service duration)
- [x] Date + time slot picker
- [x] New customer flow (collect name, email, phone) — with backend matching to existing customers by email/phone (no "welcome back" leak)
- [x] Booking confirmation page with reschedule/cancel link (tokenized, no login) — `/book/manage/<token>`
- [x] Confirmation email to customer (text + HTML, per-tenant brand color, manage link inline)
- [x] Auto-create appointment in staff calendar with `source='online'`
- [x] Auto-create invoice via existing post-save signal (Phase 1E)
- [x] Auto-assign forms via existing service-mapping (Phase 1D forms)
- [x] Public cancellation via tokenized link
- [x] Per-service buffer time respected by availability calculator
- [x] Mobile-first responsive design (most online bookings happen on phone)
- [ ] **Reschedule** via tokenized link (today: customer cancels then re-books; self-serve reschedule UI deferred)
- [ ] **SMS confirmation** — depends on 1L SMS marketing infra (Twilio + per-tenant phone provisioning)
- [ ] **Returning customer flow** — email/SMS confirmation code (today: every email+phone combo creates/matches silently; verification code is a polish item)
- [ ] **"Phone only" services** — UI surfacing already there via `is_bookable_online=False`; needs the staff catalog UI to expose the toggle (already exposed)
- [ ] **Per-tenant timezone** for slot rendering — today server-tz is used; ProviderSchedule "09:00" should resolve in `Location.timezone` (availability.py:222 polish item)
- [ ] **IP-based rate limiting** on the public POST /book/ endpoint (PublicBookingPermission has the hook ready)

---

#### 1L. Email + SMS marketing
*Tenant-driven marketing campaigns to their customer base — birthday wishes, "we miss you" win-back, treatment plan reminders, promo blasts. Distinct from 1F transactional reminders (those are auto-triggered system messages tied to a specific appointment); 1L is operator-composed, segmentable, and opt-in driven.*

**Why this is its own phase**: HIPAA + TCPA + CAN-SPAM compliance is non-trivial. Customers must opt in (TCPA for SMS, marketing opt-in for email), opt-outs must be one-click and instant, every send needs an audit trail, suppression lists must persist forever. Trying to bolt this onto 1F transactional plumbing would conflate "I have to send this" (the appointment is in 24 hours) with "I want to send this" (nudge clients to rebook) — the failure modes and gates are completely different.

**Core surface (operator-facing)**
- [ ] **Audiences** — saved customer segments. Filters: tag, last-visit recency, service history, lifetime spend, membership status, marketing opt-in flag. Live preview of count + sample customers.
- [ ] **Templates** — per-tenant template library. Plain text + simple block editor (heading, paragraph, button, image). Personalization tokens ({first_name}, {last_appointment_service}, {next_appointment_date}). HTML+text email render; SMS is plain-text-only with character counter + segment count.
- [ ] **Campaigns** — one-shot or scheduled send. Audience × template × channel (email or SMS) × send time. Send-now or schedule-future. Cancellable while pending.
- [ ] **Automations** — trigger-based: "client tagged Postpartum" → 1 day later send X; "no appointment in 90 days" → send win-back; "birthday this month" → send birthday email on the 1st. Editable per-tenant; opt-in respected.
- [ ] **Sends log + analytics** — per campaign: queued, sent, delivered, opened (email), clicked (email), replied (SMS), bounced, unsubscribed. Per customer: full list of all marketing sends ever received.

**Customer-facing (compliance critical)**
- [ ] **Opt-in capture** — booking flow + customer creation forms add explicit "Yes, I want to hear about offers from {tenant}." Stored per-channel (email opt-in vs SMS opt-in are independent). Default OFF.
- [ ] **Per-customer marketing prefs** — Customer profile gains a "Marketing" section: email subscribed yes/no, SMS subscribed yes/no, last-changed timestamp + actor. Granular by topic later (promotions, newsletters, treatment reminders), one toggle for v1.
- [ ] **One-click unsubscribe** — every email has List-Unsubscribe header (RFC 8058) + footer link → tokenized URL → toggles off + records the source. SMS replies STOP / UNSUB / END / QUIT auto-suppress (Twilio handles).
- [ ] **Suppression list (forever)** — once a customer opts out, that opt-out persists across re-imports, profile edits, etc. Suppression beats explicit opt-in unless the customer explicitly re-subscribes.

**Infrastructure**
- [ ] **Email**: AWS SES with per-tenant from-domain (DKIM/SPF/DMARC verification flow). Reputation-isolated by tenant — one tenant's spam complaints don't blacklist the others.
- [ ] **SMS**: Twilio with per-tenant 10DLC long-code or short-code. A2P 10DLC registration flow per tenant (brand + campaign approval); without it, US carriers throttle/block.
- [ ] **Send queue + worker** — Celery beat for scheduled campaigns; Celery worker for the actual send loop (paced under SES/Twilio rate limits). Failed sends retry with exponential backoff; persistent failures log + alert.
- [ ] **Webhook handlers** — SES bounce/complaint webhooks → suppression. Twilio status callbacks → delivery records. Inbound SMS webhook → STOP handling + reply routing (replies route to a tenant-defined inbox channel, ties into 1K when that resumes).

**Compliance + audit**
- [ ] **Audit log** — every send, every opt-in/out, every suppression. HIPAA: PHI never in subject lines; TCPA: written consent record per customer per channel.
- [ ] **Quiet hours** — SMS sends respect TCPA quiet hours (8 AM – 9 PM in customer's local time). Email is exempt; some tenants may want quiet hours anyway as a UX choice.
- [ ] **Per-tenant content review** — owner-only gate on sending to >100 customers (cheap check against accidental blast).
- [ ] **HIPAA framing** — the marketing surface itself doesn't carry PHI in send copy by default. Personalization tokens render at send time; allowed token set excludes any clinical/diagnostic field. ADR for the boundary between "permitted marketing" and "treatment communication."

**Out of scope for v1 of 1L**
- A/B testing campaigns
- Drip / multi-step campaigns (the trigger fires one message; sequences land later)
- In-app push notifications (no native app yet)
- Inbound reply threading (basic STOP only; full conversation routing → 1K Meta channels work)

---

### Phase 2 — Revenue features (Months 3–4)

#### 2A. Payments / POS
- [ ] Payment processor selected (TBD — not Stripe)
- [ ] Take payment from invoice
- [ ] Card-on-file (tokenized, never stored locally)
- [ ] In-person card reader integration
- [ ] Tipping flow at checkout
- [ ] Receipt email/SMS
- [ ] Daily close-out / batch report
- [ ] Refund through processor
- [ ] Auto-charge no-show fees per cancellation policy

#### 2B. Packages
- [ ] Package builder: bundle X services with custom price
- [ ] Per-package service quantities (e.g. "5 facials")
- [ ] Sell package as line item on invoice
- [ ] Track package consumption (each redemption decrements remaining)
- [ ] Package expiry dates
- [ ] Package balance visible on client profile

#### 2C. Memberships
- [ ] Membership plan builder (monthly/annual recurring)
- [ ] Included services with quantities (e.g. "1 facial/month")
- [ ] Member-only discounts on other services
- [ ] Auto-bill membership (recurring through payment processor)
- [ ] Redeem included service at booking
- [ ] Membership status on client profile (active/paused/cancelled)
- [ ] Rollover rules (use it or lose it)

#### 2D. Gift cards
- [ ] Sell gift card (digital + physical SKU)
- [ ] Gift card balance lookup
- [ ] Redeem gift card at checkout
- [ ] Gift card liability report

#### 2H. Referral program — reward redemption
*Builds on Phase 1A.2. Per-tenant config for what referrers and referred customers receive; engine that tracks credit balance and auto-applies rewards at checkout. Requires payments (Phase 2A) to redeem.*

- [ ] `ReferralProgram` model — per-tenant config: `is_active`, referrer reward (type + amount), referred reward (type + amount), expiration days, per-referrer cap
- [ ] Reward types: percent off next service, flat dollar credit, free service add-on
- [ ] `ReferralEvent` model — links referrer + referred + timestamp + status (pending / redeemed / expired); created when a referred customer books or pays for the first time
- [ ] Customer credit ledger — per-customer balance (in cents) drawn from referral rewards, gift cards, and any future credit source
- [ ] Auto-apply available credit at checkout (Phase 2A integration); reverse on refund
- [ ] Owner UI: enable/disable referrals, configure rewards, see top referrers report
- [ ] Audit log: every credit grant + redemption + expiration

#### 2F. Commissions
*Track who sold what to whom so business owners can pay providers / front-desk / sales staff accurately. NOT a payroll processor — just the source-of-truth for amounts owed.*

- [ ] `CommissionRule` model — per-tenant, per-staff (or per-job-title default) % rates
- [ ] Service-specific overrides (e.g., Sarah gets 20% on Botox, 10% on facials)
- [ ] Product / retail item commission % (different from service commission)
- [ ] Tiered commission rates (10% under $5k revenue/period, 15% over)
- [ ] Sales attribution model — who **performed** the service vs. who **sold** the package/membership; both can earn commission on the same transaction
- [ ] Per-membership / per-package commission rules — earned on signup vs. earned on each redemption (configurable)
- [ ] `CommissionEntry` model — one row per earning event, references the source (Invoice / InvoiceLine / Membership / Package), the staff member, the calculated amount, and the rule applied
- [ ] Commission accrued at invoice paid time (not booking time) so refunds reverse the entry
- [ ] Commission view per staff member: this period, last period, lifetime
- [ ] Tenant-wide commission report by date range, by staff, by service category
- [ ] Adjustments / overrides UI — Owner can add/remove commission entries with a reason (audit-logged)

#### 2G. Payroll export & summary reports
*We are NOT a payroll processor (Gusto/ADP/Rippling do that). We give the tenant everything they need to run payroll elsewhere.*

- [ ] Hourly time tracking (clock-in / clock-out per shift) — optional per tenant
- [ ] Per-staff per-period summary: hours worked, commission earned, tips received, adjustments
- [ ] CSV export per pay period — formats compatible with QuickBooks, Gusto, ADP
- [ ] Pay-period configuration (weekly / bi-weekly / semi-monthly / monthly)
- [ ] Per-staff payroll snapshot: "Sarah, May 1–15: 72 hrs × $20 + $1,840 commissions + $310 tips = $4,310 gross"
- [ ] Optional: PDF pay stub per staff member (for hand-off to staff before final processing)
- [ ] Year-to-date summary (for tax prep)
- [ ] Tip pooling / tip-out rules per tenant (front desk receives X% of provider tips, etc.)

#### 2E. Embeddable booking widget
*Wraps the Phase 1I hosted booking page as a JS snippet tenants paste into their own website (e.g. `acmespa.com/book`). Most spas live with just the hosted URL, but this matters for tenants with branded sites who don't want to send customers off-site.*

- [ ] JS snippet that tenants paste into their own website
- [ ] Iframe-based embed with auto-resize
- [ ] Inline embed option (renders into a target div)
- [ ] Allowed-origins config per tenant (CORS)
- [ ] Branding inheritance from tenant settings
- [ ] Pre-select service / provider via URL params
- [ ] Conversion event for tenant's analytics (postMessage)

#### 2I. Time tracking & punches
*Surfaced through the calendar's right-rail "Check-in" panel. Front desk can clock other staff in/out; staff can punch themselves; payroll exports (Phase 2G) read the resulting time totals.*

- [ ] `TimeEntry` model — FK to `TenantMembership`, `clock_in_at`, `clock_out_at` (nullable while open), `notes`, `source` (manual / kiosk / mobile / front-desk)
- [ ] `apps.timetracking` Django app (model + serializer + viewset + audit)
- [ ] Permission gating: anyone with `MANAGE_STAFF` can punch others in/out; staff can punch themselves
- [ ] Calendar right-rail Check-in panel — list of bookable staff with current state (clocked-in / clocked-out / on-break), one-click punch action, today's running total per person
- [ ] Daily / weekly / pay-period totals API (consumed by Phase 2G payroll exports)
- [ ] Audit log on every punch (with IP, source) — required for FLSA compliance posture
- [ ] Optional: forgot-to-punch correction flow with manager approval
- [ ] Optional: break tracking (paid vs unpaid) — defer until a real client requests it

---

### Phase 3 — Engagement & marketing (Months 5–6)

#### 3A. Two-way SMS inbox
- [ ] Conversation thread per client
- [ ] Staff inbox (assigned, unassigned)
- [ ] Templated quick replies
- [ ] MMS (photos)

#### 3B. Email marketing
- [ ] Campaign builder
- [ ] Audience segments (tags, last visit, spend tier)
- [ ] Templates with tenant branding
- [ ] Open/click tracking (consent-aware)
- [ ] Drip sequences (welcome, reactivation)

#### 3C. Reviews capture
- [ ] Post-visit SMS asking for review
- [ ] If 5-star → redirect to Google review link
- [ ] If lower → internal feedback form
- [ ] Review dashboard

#### 3D. Marketing channel integrations
- [ ] Meta Lead Ads → auto-create lead in CRM
- [ ] Google Ads → conversion tracking back to bookings
- [ ] UTM tracking through to booking → revenue attribution
- [ ] Pixel/conversion API integrations (Meta CAPI, Google Enhanced Conversions)

#### 3E. Client portal
- [ ] Self-service login (magic link)
- [ ] View upcoming + past appointments
- [ ] Self-reschedule / cancel (within policy)
- [ ] View completed forms
- [ ] View invoices + receipts
- [ ] Rebook last service

#### 3F. Tenant connected accounts (social + ads hub)
Per-tenant OAuth plumbing so each spa can link the platforms they actually run their business on. Surfaces under **Settings → Integrations**, scoped per tenant. Each connection stores refresh tokens in Secrets Manager (KMS-encrypted), not in Postgres. PHI must never be transmitted to any of these platforms — only marketing/identity data the client has consented to.

- [ ] Connection framework: OAuth flow, token storage in Secrets Manager, per-tenant scoping, revocation, health checks
- [ ] **Instagram** (Business account via Meta Graph API): DM inbox → unified inbox with SMS (3A), post-scheduling deferred
- [ ] **Facebook** (Page): Page Messenger DM inbox → unified inbox, Lead Ads ingestion (overlaps 3D)
- [ ] **WhatsApp Business** (Cloud API via Meta): customer DMs → unified inbox, opt-in template sends (booking confirms, reminders)
- [ ] **Google Business Profile**: reviews sync into 3C reviews dashboard, business info parity
- [ ] **Google Ads**: account linking + conversion upload (overlaps 3D, but this is the per-tenant linking UX)
- [ ] **TikTok / TikTok Ads**: lead-form ingestion, Pixel/Events API (modern medspa acquisition channel)
- [ ] Connection-status dashboard per tenant (token expiring, scope drift, last sync)

**HIPAA note:** Meta, Google, TikTok do not sign BAAs. Anything sent to these platforms must be marketing-context only (consented), never PHI. Per-tenant connector + per-message audit log of what data was transmitted.

**Pull-forward trigger:** if a spa's acquisition pipeline depends on a specific channel (e.g. all leads come through IG DMs), promote that channel's connector to Phase 1 polish without waiting for full 3F scope.

---

### Phase 4 — Advanced clinical & ops (Months 7+)

#### 4A. Charting / treatment notes
- [ ] Treatment note templates per service
- [ ] Injection site mapping (face/body diagram)
- [ ] Units / lot numbers / expiry tracking
- [ ] Provider sign-off on chart
- [ ] Chart PDF export

#### 4B. Photo capture
- [ ] Before/after photo upload tied to chart
- [ ] In-app photo capture (mobile)
- [ ] Side-by-side comparison
- [ ] Photo consent enforcement
- [ ] Annotations / measurements

#### 4C. Inventory
- [ ] Product/SKU catalog
- [ ] Stock counts per location
- [ ] Lot/expiry tracking (regulatory requirement for injectables)
- [ ] Auto-decrement on service performed
- [ ] Low-stock alerts
- [ ] Vendor / PO tracking
- [ ] Retail product sales at POS

#### 4D. Prescriptions
*Common at medical spas — NPs and PAs prescribe weight-loss medications, hormone therapy, ED meds, etc. Treat this as charting-adjacent data, not a fully integrated e-prescription system. Real e-prescribing (DoseSpot, Surescripts, NewCrop) requires per-state DEA registration and significant compliance overhead — that's a Phase 5 / partner-integration question.*

- [ ] `Prescription` model (extends `TenantedModel`) — FK to Customer, FK to prescribing User (must be clinical job title), drug name, dosage, route, frequency, quantity, refills, written_at, valid_until
- [ ] `PrescriptionStatus` (active / discontinued / expired / cancelled)
- [ ] Permission gating: only users with clinical `job_title` and `SIGN_CHART` permission can create prescriptions
- [ ] Audit log on every read/write (this is sensitive PHI even by HIPAA standards)
- [ ] Customer detail Prescriptions tab — chronological list, filter by status, "New prescription" composer
- [ ] PDF generation for printable / faxable Rx (template per tenant)
- [ ] Out-of-scope for v1: e-prescribing API integration, state-specific PDMP queries, controlled substance handling — partner integration in a later phase

#### 4E. Multi-location

**Pulled forward from Phase 4** so the per-employee profile's "Multi-center" section can be the real thing instead of a misleading cross-tenant placeholder. Built incrementally across 5 sessions; everything ships forward in pieces with green tests at each step rather than as a big-bang rewrite.

**Upfront decisions (committed 2026-05-02):**
- **Customers stay tenant-wide** (one client record across all locations of the same business). Most spas treat clients this way; avoids duplicate records when a customer visits the other site.
- **Services stay tenant-wide for v1**, with per-location availability flags deferred to a later session.
- **Tenant keeps duplicate per-site fields** (address, hours, phone) until Session 2 makes Location the source of truth — this avoids a half-broken `/settings/business` page mid-rollout. A small cleanup migration drops the duplicates after Session 2.

**Session 1 ✅ (completed 2026-05-02): Data model foundation**
- [x] **`Location` model** — tenant FK, name, slug, `is_default`, `is_active`, timezone, address fields, business hours, phone, email. Per-site fields live here (different sites of the same business can have different addresses, hours, and timezones).
- [x] **DB-level constraints**: per-tenant unique (tenant, slug); partial unique index on (tenant, is_default=True) so exactly one location per tenant is the default fallback. Both enforced at the Postgres layer, not application code.
- [x] **`MembershipLocation` join model** — assigns a TenantMembership to one or more Locations within its tenant, with per-site `is_active`. Allows the same person to work at the Manhattan + Brooklyn sites while keeping a single role/job-title/payroll record. Future-proofed for per-location overrides without a schema rewrite.
- [x] **Schema migration 0005** — creates Location + MembershipLocation tables + constraints.
- [x] **Data migration 0006** — for every existing Tenant, seeds one default `"Main"` Location copying timezone/phone/email/address/hours from the Tenant; for every existing TenantMembership, creates a MembershipLocation assigning it to that default location. Idempotent (safe to rerun); reverse migration deletes seeded defaults cleanly.
- [x] **`LocationMiddleware`** — runs after `TenantMiddleware`. Resolves `request.location` from `lume_active_location` cookie → falls back to tenant default → None. Cross-tenant cookie values are ignored (cookie matching a slug in tenant B never resolves when the request is on tenant A). Inactive locations are ignored.
- [x] **`get_current_location()` + `location_context()`** — parallel context helpers to the existing tenant ones, contextvars-backed for sync + async safety.
- [x] **`create_tenant_with_defaults`** — onboarding now creates the default Location (copying address/hours from tenant kwargs) and links the owner's membership to it in the same transaction.
- [x] **Django admin** — Location + MembershipLocation registered; Location shown as an inline on Tenant; MembershipLocation as an inline on TenantMembership.
- [x] **13 new backend tests** covering: default-location seeded on onboarding, owner auto-linked, only-one-default-per-tenant constraint fires, slug uniqueness scoped to tenant, middleware resolution paths (cookie → default → none, cross-tenant rejected, inactive ignored, no-tenant case), data-migration shape invariants. **65/65 total backend tests passing.**

**Session 2 ✅ (completed 2026-05-02): Locations management UI + Org IA split**

*Two-tier dashboard model decided this session: org-level (business as a whole — settings, locations, future booking-portal/integrations/cross-location reports) vs per-location (calendar, scheduling, this-site reports). Single-location tenants don't see the split — the IA expands the moment a second location is added. URL scheme: `/org/*` for org-level surfaces; bare paths for the active location (cookie-driven from Session 1's `LocationMiddleware`). Per-location manager scope (a manager who can only manage Manhattan, not Brooklyn) intentionally deferred — `MANAGE_STAFF` stays tenant-wide for v1.*

- [x] **`/api/locations/`** — full ModelViewSet with list / retrieve / create / update. Read open to anyone in the tenant (front-desk needs the location switcher); write gated by `MANAGE_TENANT_SETTINGS` (owner-only). Hard delete intentionally not exposed (Location FK lands on Appointment + payroll in later sessions; soft-delete via `is_active=false` preserves audit + referential integrity).
- [x] **Slug auto-derivation** — `name` → `slug` via Django's `slugify` when the caller omits slug. Editable on PATCH (cookie falls back gracefully when slug changes).
- [x] **Three application-side guardrails mirroring DB invariants** — friendly 400 instead of 500: (a) cannot deactivate the only active location, (b) cannot deactivate the current default, (c) cannot un-set `is_default=True` on the current default. Promoting another location to default atomically demotes the previous one in the same transaction.
- [x] **Audit logged** — CREATE / READ / UPDATE on `resource_type='location'` with `from_is_default` / `to_is_default` / `from_is_active` / `to_is_active` deltas in metadata.
- [x] **24 new backend tests** covering: list (owner + front-desk + cross-tenant isolation), create (explicit slug, auto-slug, slug uniqueness, atomic default-swap, front-desk forbidden, audit log shape), update (rename, state uppercase, hours validation, default promotion, all three guardrails fire correctly, slug uniqueness on rename, cross-tenant 404, front-desk forbidden, audit metadata), retrieve (audit log + cross-tenant 404), DELETE returns 405. **89/89 total backend tests passing.**
- [x] **Frontend `lib/locations.ts`** — `useLocations`, `useLocation`, `useCreateLocation`, `useUpdateLocation` hooks. `hasMultipleLocations()` helper for the future conditional sidebar (Session 3).
- [x] **`/org/locations`** — list page with Add Location button (owner only), per-row default + inactive chips, address + hours + timezone summary, stretched-link to detail. Show-inactive toggle.
- [x] **`/org/locations/new` + `/org/locations/[id]`** — share a `LocationForm` component (Identity / Operations / Contact / Address / Business hours sections, two-column layout matching `/org/business`). Edit page mirrors backend guardrails: default toggle disabled when this IS the default, active toggle disabled when this is the default OR the only active location.
- [x] **`/org/business`** — slimmed to Identity (read-only name + portal URL) + Branding (primary color + logo). Per-location fields no longer surfaced — those moved to per-location editing.
- [x] **Sidebar IA** — renamed "Settings" → "Organization" (Building2 icon). Sub-items: Business profile, Locations (both owner-only). The org/location *visible* split (Session 3) doesn't exist yet — for now Org just hosts these two pages.
- [x] **Legacy redirects** — `/settings`, `/settings/business` → `/org/business` for old bookmarks.

**Calendar partial-refactor pulled forward (2026-05-02 follow-up):** A user-visible regression — editing a location's business hours didn't update the calendar's day-window — forced part of Session 4 forward. The day-window timezone and visible-hours bounds now read from the active location (cookie → tenant default fallback) on both ends:
- Backend: `apps/appointments/views.py` resolves the day-window timezone via `get_current_location()` (preferred) → `tenant.timezone` (fallback) → `'UTC'` (last resort). 4 new tests in `apps/appointments/tests.py` (LA cookie shifts the May-2 window into Pacific time, default location uses NY time, unknown cookie falls back, etc.). **93/93 backend tests passing.**
- Frontend: new `useActiveLocation()` hook in `lib/locations.ts` (mirrors backend resolution: cookie → tenant default → undefined). Calendar reads `business_open_time`/`business_close_time`/`timezone` from the resolved active location instead of `useTenantSettings()`. Editing hours at `/org/locations/[id]` invalidates the locations list, which re-renders the calendar with the new bounds — no reload.

**What's still Session 4's job:** `Appointment.location` FK + migration; calendar provider scoping (only show providers assigned to active location); per-location provider working hours; and the **cleanup migration** that drops `phone`, `email`, address fields, `business_open_time`, `business_close_time`, and `timezone` from `Tenant`. The Tenant fields stay as the harmless fallback today (no UI writes them anymore; the migration in 0006 keeps them in sync at onboarding); they get removed once the appointment-creation paths and any other readers are also migrated to read from Location.

**Session 3 ✅ (completed 2026-05-02): Location switcher + dashboards**

*The visible org/location split lands. Single-location tenants (the 80% case) see no UI changes; multi-location tenants get a switcher in the sidebar header, distinct "Location · {name}" / "Organization" group headers in the nav, and a dedicated `/org/dashboard` rollup view.*

- [x] **`useSwitchLocation()`** — writes the `lume_active_location` cookie via `document.cookie`, then notifies all subscribers + invalidates the appointments query (its day-window timezone shifts per site). Future location-scoped queries register here as they land.
- [x] **Reactive `useActiveLocation()`** — switched from a non-reactive cookie read to `useSyncExternalStore` over a tiny module-level pub/sub. Switching sites now re-renders every consumer (calendar, dashboard chip, switcher itself) instantly without a reload.
- [x] **`<LocationSwitcher>` component** — popover anchored under the tenant name in the sidebar header. Renders only when `hasMultipleLocations(locations)` returns true. Shows the active location with a default-star indicator; the popover lists all active sites with city/state subtitle, current selection check-marked. Collapsed sidebar gets the icon-only variant in the icon rail.
- [x] **Conditional sidebar IA** — when 2+ active locations, the nav splits into two visual groups via thin uppercase headers: "Location · {name}" above day-to-day surfaces (Dashboard/Calendar/Clients/Services/Staff/Forms/Reports) and "Organization" above the cross-cutting parent (Org Dashboard/Business profile/Locations). Single-location tenants keep the existing flat list — no IA tax for a feature they can't use. Collapsed icon rail shows a thin divider between groups.
- [x] **`/dashboard`** — page header gets an active-location chip (only when 2+ sites) so the operator always knows which site they're viewing without scanning the sidebar.
- [x] **`/org/dashboard`** — new owner+manager page. SummaryRow with active/inactive location counts + a placeholder "cross-location reports" card flagged for Phase 1G. Locations grid with per-site cards (name + default flag + slug + address + hours + timezone + phone), stretched-link to the location's edit page (owner-only). Inactive locations are summarized as a footer card with a manage link. A "Coming next" hint surfaces the future work (revenue rollup, online booking config, integrations) so owners know the page will grow.
- [x] **Org sub-menu** — adds Dashboard entry pointing at `/org/dashboard` (owner+manager visible). `/org` index now redirects to `/org/dashboard` instead of `/org/business` — Dashboard is the natural landing because both roles can see it; Business profile + Locations are owner-gated.
- [x] **Verification**: backend 93/93 still green (no backend changes this session — pure frontend); frontend TS error count holds at 11 pre-existing (services + calendar-filter-bar resolver issues unrelated to this work).

**Session 4 ✅ (completed 2026-05-02): Calendar scoped to location + Tenant cleanup migration**

*Each location now has its own calendar — the LA day view never shows Manhattan's bookings, the bookable-providers list at LA only includes providers assigned to LA, and bookings created from a calendar are pinned to that calendar's location. Same UTC time can sit on different days depending on each location's timezone (the May-2/May-3 boundary problem solved earlier extends to the queryset itself).*

- [x] **`Appointment.location` FK** — `PROTECT` on delete to keep financial / audit history from being orphaned. Hot-path composite index `(tenant, location, start_time)` for the day-view query. Three-phase rollout: 0002 adds nullable, 0003 backfills every existing appointment with its tenant's default location, 0004 alters to NOT NULL (hand-written to skip the interactive `makemigrations` default prompt).
- [x] **Appointments queryset filtered by `request.location`** — `LocationMiddleware`'s resolved location naturally narrows what the calendar sees. Falls back to no extra filter when location is None (non-tenant context — tests/scripts) so the existing tenant scoping isn't accidentally widened.
- [x] **`AppointmentSerializer.location_id`** — writable on create (defaulted from `request.location` in `perform_create` if omitted), readable on every response. `validate_location_id` cross-tenant guard (location must belong to this tenant) + active-only guard (can't book at a deactivated site).
- [x] **Provider-at-location validation** — `validate()` now checks every booking's provider has an active `MembershipLocation` for the appointment's location. Defense in depth: the FE only shows location-eligible providers via `?location=current`, but the API rejects mismatched payloads with a friendly error naming both the provider and the location.
- [x] **`/api/memberships/?location=`** — opt-in scoping. `?location=current` uses the active location (cookie / tenant default); `?location=<slug>` uses a specific site within the tenant. Unknown slug returns empty queryset (safer than silently widening). Omitted (today's behavior) returns all matching tenant memberships — the staff list at /staff/employees still uses this org-wide variant.
- [x] **Frontend `useBookableMemberships()`** — passes `?location=current` and embeds the active-location slug in the query key so switching sites flips the cache cleanly. `useSwitchLocation()` also explicitly invalidates `['memberships']` for safety.
- [x] **Cleanup migration 0007** — dropped `phone`, `email`, `address_line1/2`, `city`, `state`, `zip_code`, `business_open_time`, `business_close_time`, `timezone` from `Tenant`. `TenantSettingsSerializer` slimmed to identity + branding only; `TenantSettingsUpdateTests` rewritten to cover the new shape (including a "stale clients posting old field names are silently ignored" guard so Phase 0c-deployed clients don't 500). Tenant admin fieldsets cleaned up. Dead `tenant.timezone` fallback in `apps/appointments/views.py` removed (LocationMiddleware always resolves to default; UTC is the only sensible last-resort). `lib/tenant.ts` interface trimmed to match.
- [x] **18 new appointments tests** covering: location-scoping (default returns only default's appointments, LA cookie returns only LA's), timezone shifting (LA window for May 2 includes the 04:00 UTC May 3 appointment because it's 21:00 PDT May 2; NY window correctly excludes it; mirror invariant for May 3), edge cases (unknown cookie falls back to default), create-defaults-from-active-location, explicit location_id overrides cookie, cross-tenant location_id rejected, inactive location rejected, provider-at-location enforcement, and `?location=` filter on bookable memberships (current + slug + unknown + inactive-assignment cases). **107/107 total backend tests passing.**

**What's NOT in scope (still future):**
- Per-provider per-location working hours — e.g. "Sarah works 9-3 at Manhattan but 4-8 at Brooklyn." Today every provider assigned to a location is bookable across that location's full business-hours window. True provider schedules require the `ProviderSchedule` model from Phase 1C session 4.
- Per-location service availability flags (services stay tenant-wide for v1).
- Per-location reporting (lights up with Phase 1G when reports are built anyway).

**Session 5 ✅ (completed 2026-05-02): Per-location staff assignments end-to-end**

*Pulled forward from the original roadmap because the user surfaced a real workflow gap: after Session 4 made the calendar location-scoped, every existing employee was assigned only to the tenant default — so non-default locations showed "no bookable staff" with no UI to fix it. This session adds the assignment surfaces (per-employee on the profile page; cross-location matrix on /org/dashboard) and auto-assigns new employees to the active location at create time so the common Add-from-/staff/employees flow doesn't silently create unassigned memberships.*

**Backend (11 new tests, 118/118 passing):**
- [x] **`MembershipViewSet.create()` auto-assigns new employees to the active location** when `location_ids` is omitted from the payload. Three precedence levels: explicit `location_ids` in the payload (assigns those, with cross-tenant validation), explicit `[]` (opt-out — employee created with no assignments), or omitted (active-location auto-assign). Audit metadata records the resolved `location_ids`.
- [x] **`MembershipDetailSerializer` accepts `set_location_ids`** (write-only) and returns `location_ids` (read-only, active assignments only). Full-replace semantics with soft-delete: removed assignments get `is_active=False` (preserving the audit trail of "Sarah used to work at Brooklyn"); re-adding a previously-removed location reactivates the existing row rather than violating the `(membership, location)` unique constraint.
- [x] **Cross-tenant guard** on both create + update: a malicious or buggy client can't assign an employee to another tenant's location; the serializer's `validate_set_location_ids` rejects it.
- [x] **Audit metadata enriched** with `location_assignments: {created_location_ids, reactivated_location_ids, deactivated_location_ids}` so SOC 2 reviews answer "who moved Sarah from Brooklyn to Manhattan and when" without diffing rows.

**Frontend:**
- [x] **`useAllMemberships()` accepts `scope: 'current' | 'all'`** option. `/staff/employees` uses `'current'` (location-scoped roster matching the sidebar's "Location · {name}" group); `/org/dashboard`'s assignment matrix uses `'all'` (org-wide editor). Active-location slug is embedded in the `'current'` cache key for clean cache invalidation on switch.
- [x] **`/staff/employees`** page header copy updated for multi-location tenants ("Employees · {location}") with a hint pointing to /org/dashboard for cross-location management.
- [x] **`/staff/employees/[id]` Locations section** — replaces the misleading "Multi-center" cross-tenant block with a real per-location assignment editor: checkbox row per active tenant location, default flag indicator, address subtitle, inline warning if the operator tries to save zero locations (would make the employee invisible to every site). Cross-tenant memberships moved into a collapsible footnote so the data is still discoverable but the primary section is the right concept.
- [x] **`/org/dashboard` Staff & locations section** — initially built as the cross-location matrix; **moved to `/staff/schedule` in a follow-up** based on UX feedback (the operator's mental model is "schedule this employee here," and Staff → Schedule is the natural place to look). Org dashboard is now back to locations-overview only.
- [x] **`/staff/schedule`** is now the primary assignment surface — location-scoped: shows assigned staff at the active location with per-row Remove + a sheet picker (search by name/email; click a row to assign immediately) for adding from the org-wide pool. Lives under the "Location · {name}" sidebar group so the location context is visible at all times. Owner+manager only for edits; read-only otherwise. Future: per-day working-hours editor lands on top of this surface in Phase 1C session 4.
- [x] **`useEmployee` per-row fetch** for the picker + assigned list — explicit trade-off documented: keeps the list payload thin for the staff page (which doesn't need location_ids); revisit if a tenant routinely has 50+ employees and the per-row fetch becomes noticeable.

**Out of scope (still future):**
- [ ] Per-employee per-location overrides (different role / pay rate at different sites). Today every assignment is just "yes/no"; role + payroll are tenant-wide.
- [ ] Bulk operations on the matrix (assign all employees to a new location at once). Single-employee-at-a-time toggle is enough for v1.
- [ ] Removal of the cross-tenant `other_memberships` API. Kept for now because some flows still consume it; deprecate when no caller remains.

**Out of scope until later:**
- [ ] Per-location service availability flags (services stay tenant-wide for v1).
- [ ] Per-location reporting (lights up with Phase 1G when reports are built anyway).
- [ ] Customer "primary location" / "transfer between locations" (customers stay tenant-wide for v1).

#### 4F. Waitlist
- [ ] Add client to waitlist for service / provider / window
- [ ] Auto-notify on cancellation
- [ ] First-come or priority order

#### 4G. Provider credentials
- [ ] License number + state + expiry tracking
- [ ] Expiry alerts
- [ ] CE credit tracking

#### 4H. Advanced reporting
- [ ] Client lifetime value (LTV)
- [ ] Retention cohorts
- [ ] Staff productivity / utilization
- [ ] Service profitability (incl. product cost)
- [ ] Membership churn
- [ ] Forecasting

#### 4I. Accounting integrations
- [ ] QuickBooks export
- [ ] Xero export
- [ ] Tax reports per jurisdiction

---

### Platform admin portal — tenant provisioning & lifecycle

The platform-admin-facing portal (`platform.lumècrm.com`) currently does the basics: list tenants, create a tenant + Owner via `services.create_tenant_with_defaults`. To onboard a new spa cleanly without manual AWS/Twilio console work, the create-tenant flow needs to fan out into the per-tenant infrastructure each spa requires.

#### P1. Twilio provisioning per tenant
- [ ] **Subaccount creation** — one Twilio subaccount per tenant on tenant create. Isolated billing, separate auth tokens stored in Secrets Manager under `lume/tenants/<slug>/twilio/*`. Prevents cross-tenant data leakage and lets us see per-tenant Twilio cost.
- [ ] **A2P 10DLC brand registration** — required to send SMS to US numbers. Brand is per legal entity (the spa's LLC). Admin portal collects EIN, legal name, address, vertical → submits to Twilio Brand API. Brand approval is automated but takes ~minutes to ~hours.
- [ ] **A2P 10DLC campaign registration** — per messaging use case (appointment reminders, marketing). Carrier review takes 1–3 business days. Admin portal tracks status, surfaces blockers.
- [ ] **Phone number purchase** — auto-search + provision a local number matching the spa's area code; fallback to admin-pick if unavailable. Attach to messaging service for the campaign.
- [ ] **Messaging service** — one per tenant, wired to the approved campaign. Inbound webhooks scoped to the tenant.
- [ ] **Verify service** (separate from messaging) — for OTPs / phone-verification flows.
- [ ] **Cleanup on tenant suspend/delete** — release number, suspend subaccount, archive audit trail.
- [ ] **Admin UI**: provisioning status dashboard (brand: pending/approved, campaign: pending/approved/rejected, number: provisioned, webhooks: healthy). One-glance "is this tenant ready to send SMS yet?"

#### P2. SES per-tenant identity (optional)
- [ ] **Default**: shared `noreply@lumècrm.com` From address (works in SES sandbox until exit).
- [ ] **Tenant-branded sending**: optionally provision a tenant subdomain (`mail.<tenant>.lumècrm.com`) with DKIM keys per tenant, so emails From the spa's own brand. Adds DNS automation (Route 53 records per tenant) and SES configuration sets. Defer until a spa actually asks.

#### P3. Tenant lifecycle controls
- [ ] **Status transitions** — Trial → Active → Suspended → Deleted (with grace period). Currently status is set manually; admin portal exposes the transitions with audit log.
- [ ] **Impersonation** — platform admin can "view as" a tenant user for support, with explicit audit log entry on every session. Required for support at scale.
- [ ] **Bulk operations** — re-seed demo data, force password reset, broadcast announcement banner.
- [ ] **Per-tenant feature flags** — gate beta features (e.g. WhatsApp connector, dark mode) per tenant from the admin portal.
- [ ] **Per-tenant cost visibility** — pull from Twilio subaccount + RDS query stats + S3 usage to surface "this tenant costs $X/mo" so pricing decisions are data-driven.

#### P4. Onboarding automation
- [ ] **Self-serve trial signup** (vs admin-driven only): public marketing site → trial signup → auto-provision tenant + redirect to onboarding wizard. Gates: prove the manual path works for the first 10–20 spas first.
- [ ] **Onboarding wizard** (tenant-facing, but triggered by platform admin tenant creation): collect business info, hours, providers, services, hours, branding colors/logo → seeds tenant with realistic defaults so they're not staring at an empty dashboard.
- [ ] **CSV imports** — staff list, customer list, services. Hand-rolled tooling is fine for first 10 spas; build a UI when the same import is requested 3+ times.

---

## 4.5 Polish backlog (pre-launch sweep)

We're building forward through Phase 1 features and **deliberately deferring polish** until before the first real-spa launch. Everything in this section is known and intentionally not blocking — we'll close it out in a polish sweep right before going live. Add to this list as new items surface; review top-to-bottom before launch.

### Calendar (Phase 1C)

- [ ] **Week view** — currently the toggle button is stubbed-disabled. Decide UX: week-by-provider (single provider × 7 days) vs. day-by-providers-condensed (7 mini day views).
- [ ] **Month view** — currently stubbed-disabled. Standard 5/6-row × 7-col grid; cells show summary (count + status dots); click drills into day view.
- [ ] **Hide-or-stub the week/month buttons** in the meantime — they currently render greyed-out which draws the eye.
- [ ] **Resize handle** on appointment blocks (extend / shorten by dragging the bottom edge). Today the only resize path is editing duration via the popover (which itself is deferred).
- [ ] **Hard conflict prevention** — currently a soft warning. Tighten to respect `Service.buffer_minutes` and require explicit "book anyway" confirmation. Backend should also enforce.
- [x] **Provider working-hours overlay** — shipped with Phase 1C session 4. Non-working hours render as a translucent muted overlay per provider column.
- [x] **Drag-drop respects provider schedules** *(2026-05-02 follow-up)* — backend `AppointmentSerializer.validate` now rejects appointments that don't fit within a working block (off day = empty array; outside a block = mismatch; partially outside a block = mismatch). The error surfaces as a toast on drop with the actionable copy (`"Time falls outside Sarah's working hours (09:00–12:00, 13:00–17:00) at Manhattan. Adjust the time or update the schedule at /staff/schedule."`) and the optimistic update rolls back automatically. Cancellations + no-show transitions skip the check (closing out an existing booking shouldn't fight a later schedule change). 6 new backend tests; 140/140 total.
- [x] **Calendar day-summary stats footer** *(2026-05-02 user request)* — `<DayStatsFooter>` strip at the bottom of the day view: bookings count (excludes cancelled), total $ (sum of `quoted_price_cents` for non-cancelled appointments — includes no-shows since the spa typically still bills them), no-shows (with destructive accent when > 0), utilization % (booked minutes / scheduled-provider minutes for the day). Computed entirely client-side from data the calendar already fetched; refreshes automatically when the cache changes. Falls back to business-hours window for utilization when a provider has no schedule. Display-caps utilization at 100% but tooltips show the raw value so over-booking is visible.
- [ ] **Block-off slots** (lunch, training, personal holds) — created on the calendar, reuses a future `ScheduleException` model.
- [ ] **Mobile / tablet responsive view** — front desk often runs the calendar on an iPad.
- [ ] **Right-click context-menu animations** — currently snap-in; smooth fade/scale would feel more refined.
- [ ] **Keyboard navigation** in the right-click context menus (arrow keys + Enter to confirm).
- [ ] **Edit / Reschedule / Message-client placeholder buttons** were removed from the popover; if they come back as part of Session 2 polish, design the layout to fit them.
- [ ] **Calendar filter row visual cleanup** — current row (Today / prev/next / date picker / long headline / provider filter / Hide cancelled / display-mode toggle / view toggle) has grown organically; revisit grouping, spacing, and which controls belong here vs. in View Settings panel. Disabled Week / Month buttons in particular look unfinished.

### Invoicing (Phase 1E)

- [ ] **Per-tenant invoice number sequencing** — currently invoices are identified by their PK; need a human-readable invoice number scheme (e.g. `INV-2026-0001`) that's unique per tenant.
- [ ] **Invoice PDF generation** (server-side render → S3 → signed URL).
- [ ] **Invoice status badge on the calendar block** — small pill (paid / open / void) so the front desk can see invoice state without opening the popover.
- [ ] **Email invoice to client** (requires SES + Phase 1F email plumbing).
- [ ] **Refund workflow** with negative-amount line items, ledger-tracked.
- [ ] **Multi-line invoices** (add-ons, retail) — Phase 2A POS scope.

### New Appointment sheet

- [ ] **Pagination / "load more"** on customer search results (currently capped at 8).
- [ ] **Server-side search** for the service typeahead — current client-side filter doesn't scale past ~100 services.
- [ ] **Walk-in / unknown customer** flow — for now requires creating a customer first.
- [ ] **Past-date booking guard** — no client-side check that the picked time is in the future. Backend doesn't reject either; should add validation.
- [ ] **Inline customer create** captures only first/last/phone/email — the rest of the chart needs separate edit. Could expand the inline form, or surface a "complete chart" prompt after create.

### Customer profile

- [ ] **2-character minimum** on the customer search input — typing one character returns nothing. Could show recent customers as a default list.
- [ ] **Customer "Other actions"** (Message client, Edit details, Reschedule) were removed from the popover; revisit which belong on the customer profile page itself.

### Right tool rail

- [ ] **6 of 8 tool panels are placeholders** — Messages, Employee check-in, Online bookings, Waitlist, Custom packages, Reports. Only Price Check + View Settings are functional. They light up as the underlying features land.

### Sidebar / Information architecture

- [ ] **Group catalog items under a "Catalog" parent** with sub-menu — currently "Services" is a top-level link and Categories live as a sub-route of `/services`. Restructure to:

  ```
  Catalog
    ├── Services
    ├── Categories       (currently /services/categories)
    ├── Packages         (Phase 2B — placeholder until built)
    ├── Memberships      (Phase 2C — placeholder)
    └── Products         (Phase 2A — placeholder)
  ```

  Reuses the same sub-menu pattern Staff + Settings already use (role-gated children, indented under the parent when active, accent border on the active child). Categories needs a dedicated `/catalog/categories` index page since today there's no list view — only the per-category edit page exists.

- [x] **Staff promoted to a top-level surface** ✅ (2026-05-02) — moved out of `Settings` and given its own sub-menu (Employees / Schedule / Check-in / Payroll). The Employees tab is the existing roster (functional today); Schedule, Check-in, Payroll are placeholder pages with "Coming with Phase X" copy until their underlying features land:

  ```
  Staff
    ├── Employees        ✅ (was /settings/staff — now /staff/employees)
    ├── Schedule         (placeholder — Phase 1C session 4)
    ├── Check-in         (placeholder — Phase 2I time tracking)
    └── Payroll          (placeholder — Phase 2 payroll)
  ```

  Naming note: the underlying data model is `TenantMembership` (the User-to-Tenant join table); the user-facing label is **Employees** because that matches how a spa owner thinks about who works there. The model name stays "membership" since renaming the join would cascade through migrations / serializers / FK names.

- [ ] **DRY the `ComingSoonCard` component** — currently duplicated 3× across `/staff/schedule`, `/staff/check-in`, `/staff/payroll`. Extract to `@/components/coming-soon-card.tsx` when a fourth caller appears (or now if it bothers you).

### Tenant subdomains + branding application

The CRM is multi-tenant via subdomain (`acmespa.lumecrm.com`); the
backend already resolves the tenant from the host. Tenant branding
(logo + primary color) is collected in tenant settings but **only
applied to client-facing surfaces** — the staff CRM stays on the
consistent Lumè design system.

- [ ] **Brand color + logo on the staff login page** — needs a public
  unauthenticated `GET /api/public/tenant-branding/?slug=…` endpoint
  (or middleware-resolved variant) returning safe info: tenant name,
  logo URL, primary color. Login page renders the tenant's brand so
  the owner's staff see "their" workspace at first sight. ~half a session.
- [ ] **Brand color + logo on the public online booking page** — Phase 1I.
- [ ] **Logo upload + storage** — needs S3 + signed URLs in prod, local
  filesystem in dev. The tenant settings form will collect the URL
  manually (`logo_url` text field) for v1; the proper upload widget is
  polish.
- [ ] **Subdomain routing in production** — DNS wildcard + frontend
  reads `window.location.hostname` to set the active-tenant cookie
  automatically (no more X-Tenant-Slug header). Phase 0c deployment.

### Business settings (Phase 1H expansion)

The current `/settings/business` page covers the minimum viable
profile (name, timezone, contact, address, brand color, logo URL).
Real-world spas will want richer configuration:

- [ ] **Hours of operation** — weekly schedule (Mon–Sun, open/close per day, optional split shift). Couples to provider working-hours overlay (Phase 1C session 4) and the public booking page (Phase 1I).
- [ ] **Cancellation policy text** — free-form rich text shown on confirmations + invoices. Phase 1F territory.
- [ ] **Booking lead time + window** — "earliest a customer can book" (e.g. 2 hours) + "latest" (e.g. 90 days out). Phase 1I.
- [ ] **Tax settings** — primary jurisdiction tax rate(s), tax ID number for invoices.
- [ ] **Tip presets** — preset tip percentages for the POS flow (Phase 2A).
- [ ] **Default appointment buffer** — applied to services that don't override.
- [ ] **Late / no-show fee** — default amount + auto-charge toggle.
- [ ] **Notification preferences** — confirmation, reminder, follow-up timing per channel (SMS/email). Couples to Phase 1F.
- [ ] **Currency + locale** — defaults to USD / en-US today; multi-currency lands when we expand beyond US (Phase 0c+).
- [ ] **Profile completeness indicator** on the settings page — the form is currently a flat list; a small "X of Y fields complete" reads better as the surface grows.

### Auth / Account

- [ ] **Password reset flow** — not built.
- [ ] **MFA stub** (TOTP via `django-otp`) — local for now per Phase 0b plan.
- [ ] **Cognito migration** — Phase 0c.
- [ ] **Replace temp-password reveal in Add Employee with email invite** — Today the Add Employee sheet shows a one-time generated password the owner must copy and hand off. When SES + Phase 1F email plumbing lands, swap this for a tokenized invite link → "set your password" page. The reveal-panel UI in `add-employee-sheet.tsx#ShareCredentialsPanel` becomes dead code; remove it then.
- [ ] **Owner promotion / demotion flow** — `ASSIGNABLE_ROLES` intentionally excludes `owner`, so neither the inline role Select nor the Add Employee sheet can mint owners. Build a deliberate "promote to owner" confirmation flow before any spa needs to designate a co-owner without DB access.

### Backend / SOC 2 / HIPAA

- [ ] **Postgres triggers for audit-log immutability** — application layer enforces today; DB-level trigger is Phase 0c.
- [ ] **Row-Level Security policies** on tenanted tables — Phase 0c (needs `lume_app` / `lume_admin` role split).
- [ ] **Audit log archival / partitioning** — rolling monthly partitions, archive partitions older than 7 years to cold S3.
- [ ] **PHI field hiding** for users without `VIEW_CLIENT_PHI` (Phase 1A.1 hardening).

### Documentation

- [ ] **Frontend README** is out of date; needs to reflect calendar / invoicing / sheet primitives.
- [ ] **API docs annotations** — drf-spectacular auto-generates but custom `@extend_schema` annotations would improve example payloads / response types per endpoint.
- [ ] **ADR for Sheet vs Dialog choice** if we add a third overlay variant later.
- [x] **Backfill ADRs for shipped major features** *(filed 2026-05-03)* — [ADR 0009 — Multi-location architecture](../docs/decisions/0009-multi-location-architecture.md) covers Phase 4E sessions 1-5; [ADR 0010 — Per-provider scheduling](../docs/decisions/0010-per-provider-scheduling.md) covers Phase 1C session 4. Both follow the ADR 0008 format with explicit HIPAA + SOC 2 framing in the Context section. Cross-linked from `apps/tenants/README.md` + `apps/appointments/README.md`. Going forward, ADRs are written **at decision time** for any feature that touches the data model, permission model, or PHI surface — not retroactively.

### Accessibility / contrast

- [ ] **Sauce Piquante destructive button** — Chef's Hat text on the destructive bg ≈ 4.46:1 (just AA, fails AAA). Acceptable but documented.
- [ ] **muted-foreground** is a derived `color-mix(Smoky Black 60%, Chef's Hat)` ≈ ~6:1 — fine but flagged as a deviation from "exact palette only."
- [ ] **Keyboard navigation audit** — date/time pickers, customer search, context menus.

### Dark mode

- [ ] **Dark mode tokens** — currently shadcn defaults; needs a parallel pass to match the MP096 palette if dark mode becomes a real product requirement.

---

## 4.55 Week-1 post-launch hardening (must finish within 7 days of first production send)

Short-fuse items committed to during launch. Each one is something we either claimed to AWS / customers / ourselves as "done" or that risks an incident if left unbuilt. These belong above §4.5 polish in priority — they are launch-debt, not polish.

- [ ] **SES bounce/complaint → SNS pipeline**. Currently the SES Account dashboard is checked manually. We told AWS in the production-access request that this will be wired up "within one week of going live." Implementation: SNS topic + `aws_sesv2_configuration_set` with event destination + Django webhook receiver (verify X.509 signature) + `Suppression` model + suppression check in the send path. **Risk if not done:** bounced-address loops degrade sender reputation; complaints aren't honored as global unsubscribes.
- [ ] **Set the SES configuration set on every outbound message.** Even after the pipeline exists, the Django `send_mail` call must reference the config set name (`ConfigurationSetName` parameter on SES SendEmail) or events don't get published.
- [ ] **Database backup restore drill**. Take an RDS snapshot, restore it into a new instance, confirm the app can run against it. Untested backups aren't backups. Schedule first drill at the 30-day mark, quarterly after.
- [ ] **CloudWatch alarm on SES bounce rate** at 3% (warning) and 5% (critical). 5% is where SES starts threatening account pauses.
- [ ] **Tighten DMARC alignment to strict** (`aspf=s; adkim=s`) after 30 days of clean DMARC reports. MAIL FROM and DKIM are both aligned today; relaxed mode is the safety belt while we watch for false positives in the reports.

---

## 4.6 Scale-readiness gate (before opening sales to ~100+ tenants)

The current production stack runs comfortably for the first ~10–20 tenants on minimum-size resources. Before hiring a sales team and pushing toward 1000s of users, these need to be in place — most are not feature work, they're hardening, capacity, and operational maturity. Treat this as a **gate before paid acquisition**, not a phase that runs in parallel with feature work.

### Capacity
- [ ] **RDS upgrade path** — current `db.t4g.micro` tops out fast. Move to `db.t4g.medium`/`db.t4g.large` (or `db.m7g.large` for production) before crossing ~50 active tenants. Enable PIE.
- [ ] **RDS Proxy** in front of Postgres — Django opens connections fast; under load Fargate tasks exhaust the connection pool. RDS Proxy multiplexes.
- [ ] **Read replica** for reporting + analytics queries (Phase 4H, Phase 2 reports) so heavy read load doesn't starve the booking write path.
- [ ] **ECS service autoscaling** — target tracking on CPU + memory + ALB requests-per-target. Scale 2 → N tasks, with cooldown to prevent thrash.
- [ ] **ElastiCache Redis** for: Django cache, Celery broker, Channels (if we add real-time), session storage. Single-AZ replication group is fine to start.
- [ ] **Background job tier** — Celery worker pool on Fargate (separate service), Celery Beat for scheduled jobs. SMS/email sends, batch reports, webhook retries all move off the request path.
- [ ] **CloudFront** in front of the frontend ALB target. Currently every page load round-trips to Fargate; CDN-cache the static Next chunks at minimum.

### Tenant isolation under load
- [ ] **Per-tenant rate limits** (DRF throttling keyed on tenant + IP) so a single noisy tenant can't degrade the platform. Currently no rate limits at all.
- [ ] **Database query timeouts** — short timeout for OLTP queries (5s), longer for explicit report endpoints (30s).
- [ ] **Async background jobs scoped per tenant** — Celery queues partitioned per tenant, or use prioritization so a tenant doing a 50k-customer CSV import doesn't starve another tenant's appointment reminders.
- [ ] **Per-tenant Twilio + SES quota dashboards** — see [Platform admin P3] cost visibility; same data drives "this tenant is hammering reminders, alert the success team."

### Observability at scale
- [ ] **Drop CloudWatch Logs for structured logging to OpenSearch or DataDog** — CloudWatch ingestion costs explode past ~5GB/day. Either ship logs to OpenSearch Service or DataDog with HIPAA BAA.
- [ ] **APM**: Sentry Performance or DataDog APM for trace-level visibility per tenant.
- [ ] **Synthetic monitoring** — Route 53 health checks + a CloudWatch Synthetics canary that exercises login + appointment create + payment flow every 5 min.
- [ ] **Per-tenant SLO dashboards** — request success rate, p95 latency, error rate. Used by support before a tenant calls in.

### Compliance + trust
- [ ] **SOC 2 Type II audit** — Drata or Vanta + auditor (~$500/mo platform + ~$15–25k one-time audit). Required for selling to spa groups, dermatology chains, anyone with a procurement team.
- [ ] **HIPAA risk assessment + ongoing review** — annual.
- [ ] **Penetration test** — annual third-party pentest. Required for SOC 2 and many enterprise procurement checklists.
- [ ] **Disaster recovery drill** — actually restore from backup quarterly. Document RPO/RTO. Untested backups are not backups.
- [ ] **Business continuity plan** — what happens if AWS us-east-1 goes down; what happens if the founder is hit by a bus.

### Billing + revenue ops
- [ ] **Billing infrastructure** — Stripe (or competitor) integration: per-tenant subscription, per-seat or per-tenant pricing, usage-based add-ons (SMS overage, additional locations). Currently no Stripe at all (deliberate for Phase 0–1).
- [ ] **Invoicing for failed payments + dunning** — automated retries, grace periods, tenant-status transitions on persistent failure.
- [ ] **Tax handling** — sales tax for SaaS where applicable. TaxJar / Stripe Tax integration when crossing nexus.

### Operational maturity
- [ ] **On-call rotation + paging** — PagerDuty or Opsgenie tied to CloudWatch alarms. Today the alarm email goes to `codenestwebstudios@gmail.com`; that doesn't survive once there's a team.
- [ ] **Runbooks for every alarm** — every alarm has a linked runbook. Currently only 4 runbooks exist.
- [ ] **Customer support tooling** — ticketing (Linear / Help Scout / Plain.com with BAA), impersonation [Platform admin P3], audit-log searchability.
- [ ] **Status page** — public status page (Atlassian Statuspage or Instatus). Required for enterprise sale conversations.
- [ ] **Documentation site** — customer-facing help docs, API docs (drf-spectacular output published).

### Team hiring (parallel to gate)
- [ ] **Hire 1: Senior backend engineer** — owns scale-readiness implementation above. Need someone who has run Django at scale.
- [ ] **Hire 2: Customer success + onboarding** — manual handholding for first 50 spas. Drives the onboarding wizard product spec.
- [ ] **Hire 3: Sales** — once unit economics are validated by first 10–20 paying spas.
- [ ] **Hire 4: Frontend engineer** — once the polish backlog (§4.5) is more work than one person can ship per quarter.
- [ ] **Founder role transition** — at ~10 paying spas, founder time is best spent on product strategy + key customer conversations, not infra debugging. The gate above is the runway to that transition.

**Definition of done for this gate**: the platform can take a new tenant from signup → onboarded → sending real customer SMS/email in <30 min with zero founder intervention, and a sustained 1000-tenant load test passes with p95 < 500ms on the booking flow.

---

## 5. Cost projection

### Monthly infra (frugal mode, before revenue)
| Service | Cost |
|---|---|
| RDS Postgres `db.t4g.micro` | ~$15 |
| Fargate (1 small task) | ~$15–25 |
| S3 + CloudFront | ~$1–5 |
| SES email | ~$0 (free tier) |
| Cognito | $0 (under 50k MAU) |
| CloudWatch | ~$5–10 |
| Twilio (1 number, low volume) | ~$5–15 |
| Route 53 | ~$1 |
| **Total floor** | **~$45–75/mo** |

### Once revenue starts (2+ spas paying)
- Add Sentry HIPAA (~$200/mo) when error volume justifies
- Add Vanta or Drata (~$500/mo) when pursuing SOC 2 or larger clients
- Cyber liability insurance (~$100–200/mo amortized)

---

## 6. Open questions / decisions to make

- [ ] Final product/domain name (Lumè CRM?)
- [ ] Payment processor selection (Square? Authorize.net? CardConnect?) — needs HIPAA BAA
- [ ] Are the 2 launch spas medical (injectables) or aesthetic-only?
- [ ] Names + size of the 2 launch spas (provider count, monthly appointment volume)
- [ ] Pricing model for our SaaS (per location/mo? per provider/mo? flat?)
- [ ] Custom domain per tenant later, or subdomain forever?

---

## 7. Working agreement

- We work through this checklist top-to-bottom, one item at a time.
- Each item ships behind a feature flag where possible; nothing half-built in main.
- No PHI touches the codebase until the foundational HIPAA checklist (section 3) is green.
- Phase 1 scope is locked. Anything else is "after v1" — write it down, don't build it.
- We test in a sandbox tenant before either real spa sees it.
