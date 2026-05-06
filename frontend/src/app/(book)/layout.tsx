/**
 * `(book)` route group — public, no-auth booking surface.
 *
 * Lives outside the `(app)` group so it inherits no auth gate, no
 * sidebar, no staff chrome. The CRM design system stays out of the
 * way; per-tenant branding (logo + primary color) is rendered by the
 * inner `[slug]` layout once the tenant is resolved.
 *
 * Structure:
 *   /book/[slug]                       service catalog
 *   /book/[slug]/[serviceId]            provider + slot picker
 *   /book/[slug]/[serviceId]/details    customer info form
 *   /book/confirmed/[token]             post-submit confirmation
 *   /book/manage/[token]                manage existing booking
 *
 * The wrapper is intentionally minimal — just a clean page background
 * + max-width container. The brand layer lives in the inner pages
 * because `confirmed/[token]` and `manage/[token]` resolve their
 * tenant from the token (not the URL path).
 */

export default function BookingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-stone-50 text-stone-900 antialiased">
      {children}
    </div>
  );
}
