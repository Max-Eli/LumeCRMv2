import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Marketing site is intentionally a separate Next deployment from
  // the CRM. In production:
  //   lumècrm.com           → this app (marketing, public)
  //   <tenant>.lumècrm.com  → ../frontend (the CRM, per-tenant)
  //   api.lumècrm.com       → backend Django
  // (Punycode form on the wire: xn--lumcrm-5ua.com — browsers
  // display the accented form to users.)
  // See marketing/README.md for the deployment shape.
};

export default nextConfig;
