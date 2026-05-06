import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Marketing site is intentionally a separate Next deployment from
  // the CRM. In production:
  //   lumecrm.com           → this app (marketing, public)
  //   <tenant>.lumecrm.com  → ../frontend (the CRM, per-tenant)
  //   api.lumecrm.com       → backend Django
  // See marketing/README.md for the deployment shape.
};

export default nextConfig;
