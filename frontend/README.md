# Lumè frontend

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4 + shadcn/ui (`base-nova` style, which uses [Base UI](https://base-ui.com) primitives — see notes below).

## Prerequisites

- Node 22+
- The Lumè backend running on `http://localhost:8000` ([backend/README.md](../backend/README.md))

## First-time setup

```bash
cd frontend
npm install
cp .env.example .env.local      # if .env.example exists; otherwise see "Env" below
```

## Running

```bash
npm run dev                     # → http://localhost:3000
```

Three routes you can hit immediately:

- **[/](http://localhost:3000)** — marketing landing
- **[/login](http://localhost:3000/login)** — sign-in form (talks to backend)
- **[/dashboard](http://localhost:3000/dashboard)** — authenticated app shell (redirects to /login if no session)

## Project structure

```
frontend/
├── src/
│   ├── app/                    Next.js App Router
│   │   ├── layout.tsx          Root layout — html/body, Providers, Toaster
│   │   ├── providers.tsx       TanStack Query client + Devtools
│   │   ├── globals.css         Tailwind v4 + shadcn theme tokens
│   │   ├── page.tsx            / (marketing landing)
│   │   ├── (auth)/             Route group: centered-card layout for unauth pages
│   │   │   └── login/
│   │   └── (app)/              Route group: sidebar shell for authenticated pages
│   │       ├── layout.tsx      Route guard — redirects to /login if useUser() returns null
│   │       └── dashboard/
│   ├── components/ui/          shadcn primitives — DO NOT replace styling here lightly
│   └── lib/
│       ├── api.ts              Fetch wrapper — credentials: include, attaches X-CSRFToken
│       └── auth.ts             useUser / useLogin / useLogout hooks
├── components.json             shadcn config — style: "base-nova"
└── package.json
```

## Important: Base UI, not Radix

The `base-nova` shadcn style uses `@base-ui/react` primitives, NOT `@radix-ui/react-*`. Most patterns from older shadcn/Radix documentation **don't apply directly**.

Specifically:

```tsx
// WRONG (Radix-era pattern)
<Button asChild>
  <Link href="/login">Sign in</Link>
</Button>

// RIGHT (Base UI render prop)
<Button render={<Link href="/login" />} nativeButton={false}>
  Sign in
</Button>
```

When in doubt, read the type definitions: `frontend/node_modules/@base-ui/react/<component>/<Component>.d.ts`.

## Important: Next.js 16

This repo runs Next.js 16, which has breaking changes from Next.js 15-era patterns. Bundled docs live at `node_modules/next/dist/docs/` — read them when something behaves unexpectedly.

## Env (`.env.local`)

| Var | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend base URL — `http://localhost:8000` for local dev |

## Conventions

- **API calls go through `lib/api.ts`** — never call `fetch` directly. The wrapper handles credentials + CSRF.
- **All hooks/components touching auth use `useUser` / `useLogin` / `useLogout`** from `lib/auth.ts`. Don't duplicate auth logic.
- **`(app)` routes assume an authenticated user.** The route guard in `(app)/layout.tsx` redirects to `/login` otherwise.
- **'use client' on every file that uses hooks or browser APIs.** Server components are the default in App Router.
- **JSDoc on every exported function, hook, type, and component.** See [documentation discipline](../README.md#documentation-discipline).

## Adding shadcn components

```bash
npx shadcn@latest add <component> -y
```

The component lands in `src/components/ui/`. You own the source — edit freely.
