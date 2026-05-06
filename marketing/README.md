# marketing

The public marketing site at **lumecrm.com**. Lives separately from
the CRM (`../frontend`) because:

1. **Different deployments at different domains.** `lumecrm.com` is
   one Vercel/Fargate target; `<tenant>.lumecrm.com` is another.
   Co-locating in one Next app would mean serving the auth shell +
   tanstack-query providers on every public page request.
2. **Different release cadence.** Marketing copy ships weekly; the
   CRM ships behind tested feature flags. Separating the deployments
   keeps each release surface honest.
3. **Different SEO posture.** The marketing site is purely public
   and aggressively pre-rendered; the CRM is gated behind auth and
   actively de-indexed.

The brand assets, color palette, and typography are mirrored verbatim
from the CRM so the visual continuity holds end-to-end. A customer
who lands on lumecrm.com, signs in, and arrives in their tenant
subdomain shouldn't notice the seam.

## Local dev

```bash
cd marketing
npm install     # one time
npm run dev     # boots Next on http://localhost:3001
```

The CRM frontend runs on `:3000` (typically already up). Both can
run side by side; only the marketing site is exposed at
`lumecrm.com` in production.

The "Sign in" CTA points at `NEXT_PUBLIC_APP_URL`, which defaults to
`http://localhost:3000` in dev. Set it to `https://app.lumecrm.com`
(or whatever the staff sign-in surface is named) for production.

## Production deployment shape

```
                       ┌──────────────────────────────────┐
   lumecrm.com    ───→ │ marketing/  (this app)           │  Vercel / Fargate
                       └──────────────────────────────────┘

                       ┌──────────────────────────────────┐
   *.lumecrm.com  ───→ │ frontend/   (the CRM)            │  Vercel / Fargate
                       │  resolves tenant from subdomain  │
                       └──────────────────────────────────┘

                       ┌──────────────────────────────────┐
   api.lumecrm.com ──→ │ backend/    (Django + Postgres)  │  Fargate + RDS
                       │  resolves tenant from Origin or  │
                       │  X-Tenant-Slug header            │
                       └──────────────────────────────────┘
```

DNS:
- `lumecrm.com` (apex) — A/ALIAS to the marketing deployment
- `www.lumecrm.com` — 301 → apex
- `*.lumecrm.com` — wildcard CNAME to the CRM frontend deployment
- `api.lumecrm.com` — A/CNAME to the backend ALB

The marketing site links to the CRM via the `NEXT_PUBLIC_APP_URL`
env var. We can either:

- **Single staff sign-in surface**: route every operator through
  `app.lumecrm.com`, which reads the active tenant from the session
  cookie or asks them to pick. Simpler nav.
- **Per-tenant subdomain on first request**: ask the operator to
  visit `<your-spa>.lumecrm.com` directly. Better SEO de-indexing
  isolation, harder for an operator who has lost their slug.

Lean toward the single sign-in surface for v1; revisit when we have
five-plus tenants and the analytics start to pull apart.

## Pages

13 pages live, all written in product-marketing voice:

- `/` — Home (hero with calendar mock + parallax, capability strip
  marquee, six capability rows each paired with a product mockup,
  "Why Lumè" competitive positioning, compliance strip, demo CTA)
- `/features` — Magazine-style index, each row links to a deep-dive
- `/features/booking` — Multi-provider calendar, online booking,
  reminders deep-dive
- `/features/charts` — Client records, provider notes, forms
  surfacing deep-dive
- `/features/forms` — E-sign templates, tokenized fill flow, audit
  trail deep-dive
- `/features/payments` — Invoicing, daily close-out, reopen/void
  deep-dive
- `/features/reports` — 22 reports, permissions, CSV+PHI export
  deep-dive
- `/features/multi-location` — Per-location ops, org rollup,
  pricing deep-dive
- `/medspas` — Vertical positioning. Names competitors directly
  (Mindbody, Vagaro, Boulevard, Zenoti, Athena, Epic) and explains
  what each is built for vs. what Lumè is built for. Plus a
  "day in the front desk's hands" walkthrough with three mocks.
- `/security` — HIPAA + SOC 2 substance with six commitments,
  each citing its ADR
- `/pricing` — Request-a-demo with four pricing variables and
  twelve "included at every level" capabilities
- `/demo` — Editorial form with the 4-step "what happens next"
  sidebar (client-side only in v1; backend wiring in Session 2)
- `/about` — Concrete why-we-exist, what-we-believe, where-we-are

Motion: every page uses `<ScrollReveal>` for stagger-fade-up on
sections + lists, `<Parallax>` on the home hero mock, and a
horizontal capability marquee on the home page. All pure CSS +
IntersectionObserver — no animation library dependencies.

## What's next

Session 2 (next):
- `POST /api/demo-requests/` Django endpoint + `DemoRequest` model
  + Slack notification on submit (replaces the client-side stub).
- SEO meta polish (OpenGraph images per page, structured data).
- Replace some product mocks with real screenshots from a polished
  tenant once we have one to capture from.

Session 3 (later):
- Blog / journal scaffold (MDX-based, editorial layout).
- Customer story template + the first published story (post-launch
  with one of the migrating spas).
- Real spa photography in the home hero + about page.
- `/privacy`, `/terms`, `/baa` legal pages — copy needed; the footer
  links are already in place.

## Design constraints (for any future contributor)

This site is competing for attention with Boulevard, Zenoti, and
Podium. Read those sites before you write a word here. The bar is
**professional product marketing** — not literary fiction.

### Writing voice

A short list of things we **don't** do in copy:

- **No literary affectation.** "Considered", "unhurried", "in your
  own time", "the room stays the room", "built for the chair, not
  the boardroom" — every one of these reads as AI-generated. If
  the line sounds like an art-gallery wall card, rewrite it.
- **No metaphor-driven word salad.** "Software that respects the
  room." What does that actually mean? Cut it. Replace with what
  the software does.
- **No fake origin stories.** "Built by people who've actually
  stood behind the front desk" — be specific or stay silent.
- **No SaaS boilerplate.** "Powerful", "Streamline", "Take your
  business to the next level", "Unlock", "Empower". Cut on sight.
- **No emoji-clustered headlines.**
- **No vague aspirational claims.** Replace with specific
  numbers, specific features, specific outcomes ("22 reports",
  "0 platform fee on card volume", "60-day reopen window").

Things we **do** in copy:

- **Lead with the value prop in 6 words or fewer.** "Run your
  medspa from one platform." Direct. Claims the category.
- **Name competitors when contrasting.** Mindbody, Vagaro,
  Boulevard, Zenoti — say what they're built for and how Lumè is
  different. Vague "other platforms" is hand-waving.
- **Use real numbers.** "22 reports", "60-day reopen window",
  "256-bit URL tokens", "30-50% no-show reduction with reminders".
- **Reference the real product.** Capability copy should map to
  features in the actual CRM. Don't market what doesn't exist.
- **Cite the architecture.** On the Security page, every
  commitment cites its ADR. Substance is defensible.

### Visual constraints

- No gradient backgrounds or glassmorphism.
- No "trusted by [stock logo strip]" until we can name actual
  customers.
- No 3-card feature grids — long form, alternating asymmetric
  layouts, or numbered indexes only.
- No purple/pink gradient blob illustrations.
- No accent-colored CTA buttons. Burgundy is the editorial accent
  (italic phrases, drop caps, fine rules); buttons are foreground
  black.
- No newsletter signup form. The CTA is the demo request — once.

### Shared components

Palette + type system live in `globals.css`. The shared components:

- `<BrandMark variant="lockup|icon" size={n}>` — the logo lockup.
- `<TopNav>` and `<Footer>` — site chrome, on every page.
- `<PageHero>` — eyebrow + serif headline + standfirst, used at
  the top of every inner page.
- `<SectionEyebrow>` — kicker + eyebrow + headline + description
  for inner sections on the home / vertical pages.
- `<FeaturePage>` — reusable feature deep-dive template (hero +
  hero mock + 3 highlights + N detail sections + related
  features + CTA). All six `/features/<slug>` pages use this.
- `<ProductFrame>` + the mocks in `<ProductMocks>` — browser-
  framed inline product UI. Use these instead of stock
  illustrations.
- `<ScrollReveal>` and `<Parallax>` — motion primitives.
- `<Marquee>` — slow editorial ticker, use sparingly.

New pages should compose these before reaching for novel chrome.
