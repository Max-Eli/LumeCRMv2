# ADR 0006 — Visual design system

## Status

Accepted (2026-04-30) · Palette swapped twice on 2026-05-02:

  1. Tried the Sherwin-Williams "Snowbound" sage/cream palette
     (rolled back same day — read as too quiet/coastal for the
     intended product personality).
  2. Currently on the **"MP096" fire palette** — vivid orange,
     burgundy, near-white, near-black — bold and editorial. See
     "Palette swap II (2026-05-02)" below.

The system architecture (token-driven CSS variables, serif-display +
sans-body pairing, sparing accent usage, redesign-patterns-not-pages)
is unchanged across all three palettes — only the color values rotate.

## Context

The Lumè frontend was scaffolded with shadcn/ui's `base-nova` style and Tailwind v4's default neutral palette. That stack ships great primitives but a **generic** look — the same color palette every shadcn app starts with. For a CRM that has to compete against Boulevard, Zenoti, and Vagaro and convince premium medspas to switch, "generic" is wrong. The product has to read as **medical AND luxe** at first glance.

The user's feedback: "right now it's feeling a little like it's AI-generated." That's an accurate read of any unmodified shadcn app — every AI codegen produces the same neutral surface, so the look has been associated with low-effort builds.

Three direction options considered:

| Direction | Vibe | Examples |
|---|---|---|
| Cool-clinical | Soft blue + white, minimal, professional | One Medical, Forward, Hims clinic |
| Bold-modern | Vibrant accents, bold sans, edgy | Hers, Roman, Cerebral |
| **Warm-luxe** | Cream + warm charcoal + dusty rose-gold accent, refined serif accents | Aesop, Boulevard, upscale wellness brands |

## Decision

**Warm-luxe minimal.** The design system commits to:

### Color palette (OKLCH)

Lights are cream-tinted, not stark white. Text is a warm charcoal, not pure black. The accent is a dusty rose-gold — visible but never "millennial pink."

| Token | Light value | Role |
|---|---|---|
| `background` | `oklch(0.985 0.008 75)` | Warm cream |
| `foreground` | `oklch(0.18 0.012 50)` | Warm charcoal text |
| `card` | `oklch(1 0.002 75)` | Slightly warmer-than-stark surfaces |
| `primary` | `oklch(0.22 0.014 50)` | Buttons / strong CTAs |
| `accent` | `oklch(0.72 0.075 35)` | Dusty rose-gold — focus, brand chrome |
| `muted` | `oklch(0.95 0.008 75)` | Subtle surface tint |
| `border` | `oklch(0.9 0.01 75)` | Warm light gray |
| `radius` | `0.5rem` | Slightly tighter than shadcn default |

### Typography

- **Body / UI:** Geist Sans (loaded via `next/font/google`). Already present.
- **Display / brand chrome:** Fraunces serif. Used **only** for page titles (`<h1>` in `<PageHeader>`), the "Lumè" wordmark, and one or two intentional accents (stat-card values on dashboard). Never as body text — that defeats the contrast.

The pairing is the visual hook: a refined serif against a clean modern sans says "magazine spread" — premium and editorial — without being precious.

### Iconography

Lucide React (already a shadcn dependency). Default stroke weight. Used in:

- Sidebar nav (one icon per route)
- Section headers on detail pages (Mail, Phone, MapPin, Stethoscope, etc.)
- Empty state illustrations (icon + headline)
- Inline action buttons (Plus, Search)

### Reusable components

- **`<PageHeader>`** — every authenticated page composes its top with this. Title (serif) + description (muted) + optional actions row + optional "back" breadcrumb. Centralizes vertical rhythm and font/spacing decisions.
- **`<StatusBadge>`** — small colored dot + label. Replaces colored "chip" badges for status. Reads faster; feels more refined.
- **`<InitialsAvatar>`** — Avatar with initials fallback + deterministic soft pastel color from the name string. Same person always gets the same chip color.

### Spacing / rhythm

- Page padding: `px-10 py-10` (more generous than shadcn examples)
- Max content width: `max-w-7xl` for indexes, `max-w-2xl` for forms, `max-w-5xl` for detail
- Card spacing: `space-y-2` for tight rows, `gap-4` for grids
- Empty states: full card with centered icon + serif headline + muted description + CTA

### Where the accent gets used

Sparingly, on purpose:

- Primary "Sign in" button border-glow on focus
- Avatar circle background (variant)
- Border accent on Medical PHI section card (accent/30 + accent/4 bg) to visually mark it as the most sensitive area
- Sidebar active-route ring
- `text-accent` on critical-section icons (Stethoscope on PHI)

Not on every chip and badge — those stay neutral. The rule: accent for emphasis, not decoration.

## Consequences

### Pros

- **Distinctive.** No longer reads as a generic shadcn app. Looks like an intentional product.
- **Cohesive.** Every page inherits the system; tokens are central. Changing one token ripples across the whole app.
- **Editorial feel.** The serif/sans pairing reads "premium" without screaming.
- **Spa-appropriate.** Warm cream is the visual language of every nice spa interior.
- **Legible PHI.** Medical sections get the accent treatment so they're visually marked as more sensitive.
- **Reusable patterns.** `<PageHeader>`, `<StatusBadge>`, `<InitialsAvatar>` get used on every future page with no per-page styling decisions.

### Cons

- **Less neutral than the default.** A spa with a strong existing brand may want to override. Mitigation: tenant `primary_color` field already exists; per-tenant theming UI is on the Phase 1H roadmap.
- **Two fonts loaded.** Slight extra page weight. `next/font` self-hosts and subsets so the cost is small (~50KB).
- **Dark mode pending.** Existing dark mode tokens in `globals.css` carry over from the shadcn default and don't yet match the warm-luxe palette. If dark mode becomes a real requirement, those values need a parallel pass.
- **Fraunces is opinionated.** It's a very particular kind of serif (variable, expressive). If we ever decide we want a quieter look, Newsreader or Lora are drop-in replacements.

### Per-page redesign vs. per-pattern redesign

This ADR commits to redesigning **patterns**, not individual pages. Future feature work copies the pattern. We don't bespoke-design the calendar page or the invoice page — they should look like Clients, just with a calendar / invoice list inside the same shell.

## Implementation notes

- All tokens live in `src/app/globals.css` under `:root` (light) and `.dark` (kept untouched for now).
- Components live in `src/components/` (patterns) and `src/components/ui/` (shadcn primitives).
- The Fraunces font is loaded in `src/app/layout.tsx` via `next/font/google` with axes `opsz` and `SOFT` for variable rendering; exposed as `--font-serif` and surfaced through Tailwind v4's `font-serif` utility.

## Palette swap (2026-05-02)

The original "warm cream + dusty rose-gold" palette was replaced with a
Sherwin-Williams paint palette specified by the user. Snowbound becomes
the page background; the other seven colors fill the remaining tokens.

### Source colors

| SW # | Name | Hex | Role |
|---|---|---|---|
| 7004 | Snowbound | `#EDEAE5` | `--background`, `--primary-foreground` |
| 6258 | Tricorn Black | `#2F2F30` | `--foreground`, `--primary`, button text |
| 7570 | Egret White | `#DFD9CF` | `--card`, `--popover`, `--sidebar` |
| 7057 | Silver Strand | `#C8CBC4` | `--border`, `--input` |
| 6028 | Cultured Pearl | `#E5DCD6` | `--secondary`, `--muted`, `--sidebar-accent` |
| 9643 | Eventide | `#A6B1AF` | `--accent`, `--ring` (focus + brand chrome) |
| 9644 | Portsmouth | `#768482` | `--muted-foreground`, `--chart-2` |
| 9611 | Minimalist | `#CBBFAF` | `--chart-3` |

### Rationale for specific assignments

- **Snowbound = bg, Egret White = cards.** The SW palette has nothing
  brighter than Snowbound, so cards become a touch *warmer/darker* than
  the page rather than the conventional "elevated brighter card." This
  reads as deliberate warm-luxe layering (Aesop, Le Labo) rather than
  flat — and keeps every surface in the named palette.
- **Cultured Pearl = muted/secondary.** Sits between Snowbound and
  Egret White in lightness; gives a subtle blush surface for status
  rows, hover states, sidebar active-route highlights without competing
  with cards.
- **Eventide = accent / ring.** Replaces the prior dusty rose-gold.
  Sage teal at ~67% luminance against cream surfaces — visible as
  brand chrome (focus rings, sidebar active marker, PHI-section borders)
  without the visual "softness" of the original rose-gold. Brand
  identity shifts from *warm spa* toward *coastal-modern spa*.
- **Tricorn Black = primary buttons.** Strong CTAs are pure-black,
  paired with Snowbound text — 12.7:1 contrast (AAA).
- **Silver Strand = borders.** The faintest sage-gray in the palette;
  gives surfaces a quiet edge without graying the canvas.
- **Portsmouth = muted-foreground.** The only mid-luminance member that
  reads as readable text without losing visual hierarchy.
- **Minimalist** lands in `--chart-3` so all eight palette colors have
  a named role.

### Accessibility trade-offs

- **`--muted-foreground` (Portsmouth on Snowbound) ≈ 3.2:1.** Above
  WCAG AA-large (3:1) for UI text and labels, below AA-body (4.5:1).
  Acceptable because shadcn's convention is to use `muted-foreground`
  for captions, secondary metadata, and form-helper text — not body
  paragraphs. Body paragraphs use `--foreground` (Tricorn Black on
  Snowbound, ≈12.7:1, AAA). If we ever style a long-form paragraph
  with `text-muted-foreground`, swap to `text-foreground` or layer a
  darker `color-mix()` for that surface.
- All other text/surface combinations are AAA. Verified pairs:
  Tricorn Black on Snowbound (12.7:1), on Egret White (11.5:1), on
  Cultured Pearl (11.9:1), on Silver Strand (~9.5:1); Snowbound on
  Tricorn Black (12.7:1).

### Out of scope for this swap

- Dark mode tokens. Per the original ADR, dark mode is on hold until a
  real product requirement exists. The shadcn defaults remain.
- Tenant-customizable category colors. Service categories carry their
  own per-tenant hex colors (set on the category form); those are
  stored data, not part of the design system, and remain whatever the
  tenant configured.
- The destructive token. None of the eight SW colors carry the
  urgency a destructive state needs; we keep the desaturated brick
  red so error / cancel paths read as such without clashing with
  warm-cream surfaces.

## Palette swap II — "MP096" fire palette (2026-05-02)

The Sherwin-Williams palette tried earlier the same day was rolled back
because the cool sage/cream tones read as too quiet for the product's
intended personality. The replacement is bolder: editorial, high-energy,
restaurant-adjacent in tone. Six colors, each with a defined role.

### Source colors

| Name | Hex | LRV-ish role |
|---|---|---|
| Chef's Hat | `#F3F4F5` | Lightest — page bg, button text on dark |
| Drifting Cloud | `#DBE0E1` | Light gray — borders, inputs, muted/secondary |
| Smoky Black | `#100C08` | Darkest — body text, primary buttons |
| Bacchic Burgundy | `#95122C` | Deep wine — brand accent + focus ring |
| Sauce Piquante | `#CA3F16` | Red-orange — destructive |
| Merin's Fire | `#FF9408` | Vivid orange — chart-2 + reserved high-energy emphasis |

### Role assignments

| Token | Color | Why |
|---|---|---|
| `--background` | Chef's Hat | The "canvas" |
| `--foreground` | Smoky Black | 19.06:1 (AAA) body text |
| `--card`, `--popover` | Chef's Hat | Flush with bg; the **border** defines the surface (no color in the palette is brighter than Chef's Hat) |
| `--primary` | Smoky Black | Universal CTAs — premium, unambiguous, AAA against `--primary-foreground` |
| `--primary-foreground` | Chef's Hat | Button text on dark |
| `--secondary`, `--muted` | Drifting Cloud | Subtle gray surface for hover, status rows, helper sections |
| `--muted-foreground` | derived (Smoky Black 60% + Chef's Hat) | The palette has no neutral mid-gray; this stays *inside* the palette as a function of two named colors and lands at ~6:1 on the bg (AA-body). Strict "no derived colors" would force `muted-foreground = Smoky Black` and destroy the visual hierarchy. |
| `--accent`, `--ring` | Bacchic Burgundy | Brand chrome — focus rings, sidebar active marker, PHI-section emphasis, drag-target highlights. Used at low opacity (`bg-accent/15`) for dusty-pink tints, full opacity for active/selected states. Reads as premium-spa rather than playful |
| `--accent-foreground` | Chef's Hat | White on burgundy = 8.6:1 (AAA). (Smoky Black on burgundy fails at 2.2:1 — must be Chef's Hat.) |
| `--destructive` | Sauce Piquante | Replaces the prior generic red — fits the palette and reads as urgency without clashing |
| `--border`, `--input` | Drifting Cloud | Quiet gray edge |
| `--chart-1..5` | Burgundy / Fire / Sauce Piquante / Smoky Black / Drifting Cloud | All six colors get at least one slot |
| `--sidebar` | Chef's Hat | Same canvas as main, distinguished by border |
| `--sidebar-accent` | Drifting Cloud | Active route bg — subtle gray highlight |
| `--sidebar-ring` | Bacchic Burgundy | Active marker / focus |

### Why Smoky Black for primary, Burgundy for accent, Fire reserved

Three vivid candidates, three roles:

- **Smoky Black (primary).** Universal "save / submit / confirm" works
  on every page; AAA contrast; reads as premium without forcing every
  click to feel "fiery." Matches Aesop / Boulevard convention.
- **Bacchic Burgundy (accent).** Brand chrome — focus rings, sidebar
  active marker, PHI-section emphasis, drag-target highlights. At low
  opacity it's a dusty-pink tint (`bg-accent/15`), at full opacity a
  rich premium-spa wine. Reads as Hermès / Cartier / luxury — the
  identity hook for the product.
- **Merin's Fire (reserved emphasis).** Vivid orange — too saturated
  to live as accent (would tire the eye on every focus / hover state
  across the app). Lives in `--chart-2` and is the natural pick for:
  - Promotion / sale banners
  - Highlighted call-outs in marketing collateral
  - A `<Button variant="cta">` for a one-click "Book now" / "Subscribe"
    moment if needed
  - Limited-time event chips on the calendar (Phase 1H)

  Reserving it keeps it meaningful — when the user sees Merin's Fire,
  it always means "look here right now," never just "this is a button."

### Accessibility trade-offs

- **`--muted-foreground` is derived** via `color-mix(in oklab, Smoky
  Black 60%, Chef's Hat)` ≈ ~#5C595A. ~6:1 on bg (AA-body). Inside the
  palette as a function of two named colors.
- **Destructive button (Chef's Hat on Sauce Piquante) ≈ 4.46:1.** Just
  passes WCAG AA-body, fails AAA. Standard for destructive UI; matches
  most production design systems (Material's red-500 lands similarly).
- All other text/surface combos are AAA. Verified pairs:
  Smoky Black on Chef's Hat (19.06:1), on Drifting Cloud (15.76:1);
  Chef's Hat on Smoky Black (19.06:1), on Bacchic Burgundy (8.6:1);
  Bacchic Burgundy on Chef's Hat (8.74:1).
- **Critical accent-foreground rule:** Smoky Black on Bacchic Burgundy
  is only 2.2:1 — fails WCAG. Always pair burgundy backgrounds with
  Chef's Hat text. The `--accent-foreground` token already does this;
  any future component that puts custom text on `bg-accent` must use
  `text-accent-foreground`, not `text-foreground`.

### Out of scope for this swap

- Dark mode tokens — kept on shadcn defaults, same as before.
- Tenant-customizable category colors — stored data, not part of the
  design system.
- Bespoke per-page styling — the wordmark, page headers, etc. continue
  to inherit `--foreground`. Per the "redesign patterns not pages"
  principle, the palette swap is a token-level change; component
  classes are unchanged. If we later want a `<BrandWordmark>` that
  uses Bacchic Burgundy, that's a deliberate component decision.

## References

- [Frontend README](../../frontend/README.md)
- [shadcn/ui base-nova style notes](../../frontend/components.json)
- ADR 0005 — [Frontend stack](0005-frontend-stack.md)
- Inspiration: Boulevard ([blvd.co](https://blvd.co)), Aesop site treatment, One Medical's typographic restraint
