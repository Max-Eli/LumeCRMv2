# ADR 0005 — Frontend stack

## Status

Accepted (2026-04-30)

## Context

Lumè needs a customer-facing web app that staff use day-to-day, plus a public booking page customers visit anonymously. The user (a solo dev) wants:

- **Modern, professional, "not AI-generated" look.** Custom-feeling, branded.
- **Fast iteration.** Solo dev, 2-month timeline.
- **Mobile-friendly.** Most online bookings happen on phones.
- **Type safety end-to-end** to catch regressions early as the codebase grows.

## Decision

**Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4 + shadcn/ui (`base-nova` style) + TanStack Query.**

### Stack pieces

| Choice | Why |
|---|---|
| **Next.js 16** | App Router for nested layouts. Server components by default. Route groups for `(auth)` and `(app)` shells. Static export possible for production deploy to S3+CloudFront (no PHI in serverless functions). |
| **React 19** | Bundled with Next.js 16. Stable. |
| **TypeScript** | Type safety across API boundary, fewer regressions, better IDE support. Non-negotiable for a project we expect to grow. |
| **Tailwind v4** | CSS-first config (no `tailwind.config.js`). Smaller, faster, modern CSS variables. Aligns with shadcn/ui's design tokens. |
| **shadcn/ui (`base-nova` style)** | Copy-paste components — we own the source. Modern, composable. The `base-nova` style uses **Base UI** primitives (the Radix successor library) — patterns differ from older shadcn examples; see the dedicated callout below. |
| **TanStack Query** | Server state management. Caching, background refetch, optimistic updates. The `useUser` query becomes the single source of truth for auth state. |
| **react-hook-form + zod** | Form state + validation. Schema-driven, type-safe, minimal re-renders. |
| **sonner** (via shadcn) | Toast notifications. |

### Routing structure

```
src/app/
├── layout.tsx              Root: html/body, Providers, Toaster
├── providers.tsx           QueryClientProvider + Devtools
├── globals.css             Tailwind v4 + shadcn theme
├── page.tsx                / (marketing landing)
├── (auth)/                 Route group: centered-card layout, no auth required
│   └── login/
└── (app)/                  Route group: sidebar shell, auth required
    └── dashboard/
```

Route groups keep URLs clean (no `/auth/login`, just `/login`) while separating layouts. The `(app)` layout includes a client-side route guard via `useUser()` that redirects unauthenticated visitors.

### API integration

- **`src/lib/api.ts`** — single fetch wrapper with `credentials: 'include'`, automatic CSRF token attachment, typed `ApiError`.
- **`src/lib/auth.ts`** — `useUser`, `useLogin`, `useLogout` hooks backed by TanStack Query mutations and queries.
- **`NEXT_PUBLIC_API_URL`** in `.env.local` points at the backend (default `http://localhost:8000`).

### Important callout: Base UI, not Radix

The `base-nova` shadcn style imports from `@base-ui/react`, the next-generation library from the Radix/MUI team. The patterns differ from older Radix-based shadcn examples in subtle but important ways:

```tsx
// WRONG — Radix Slot pattern from older shadcn examples
<Button asChild>
  <Link href="/foo">Click</Link>
</Button>

// RIGHT — Base UI render prop
<Button render={<Link href="/foo" />} nativeButton={false}>
  Click
</Button>
```

When in doubt, read `frontend/node_modules/@base-ui/react/<component>/<Component>.d.ts` for the actual API.

## Consequences

### Pros

- **Modern aesthetic without design work.** shadcn primitives + Tailwind get us 80% of the way to Boulevard-quality UI.
- **Type safety.** TypeScript end-to-end + zod for runtime validation at boundaries. Few classes of bug compile away.
- **Fast iteration.** Next.js HMR, TanStack Query devtools, Tailwind class-based styling — feedback loops are tight.
- **Static-exportable.** When we deploy in Phase 0c, the app exports to static assets and serves from S3+CloudFront — no Node runtime, no PHI in serverless functions, lower attack surface.
- **One language (TypeScript) for frontend + future BFF if we need one.** Backend stays Python — see [ADR 0001](0001-multi-tenancy-strategy.md) for why Django won there.

### Cons

- **Bleeding edge.** Next.js 16, React 19, Tailwind v4, shadcn `base-nova` are all very recent. Documentation lags reality, AI assistants (this one included) have stale knowledge of the new APIs. Mitigation: read bundled docs in `node_modules`, save gotchas to project memory as we hit them.
- **Client-side route guard.** Brief loading flash before unauth redirect. Not great UX. Phase 0c may move to server-rendered auth check via `cookies()` / forward to backend.
- **Heavy initial bundle for a CRM dashboard.** Acceptable for a logged-in app; we'll keep it lean for the public booking page (Phase 1I).
- **TanStack Query state isn't synchronized across tabs.** A user logged in in one tab won't see the change in another tab automatically. Mitigation: BroadcastChannel / Storage events if it becomes a real UX issue. Not blocking.

## References

- [Frontend README](../../frontend/README.md)
- [Next.js 16 release notes](https://nextjs.org/blog/next-16) (replace with actual link if/when accessed)
- [Base UI docs](https://base-ui.com)
- [shadcn/ui](https://ui.shadcn.com)
- [TanStack Query docs](https://tanstack.com/query)
