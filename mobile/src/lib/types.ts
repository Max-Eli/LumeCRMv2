/** Shared API types mirrored from the Django serializers. */

/** A spa workspace. */
export interface Tenant {
  id: number;
  name: string;
  slug: string;
}

/** The current user's role + standing at one tenant. */
export interface Membership {
  tenant: Tenant;
  role: string;
  role_display: string;
  is_bookable: boolean;
}

/** The authenticated user. Shape matches `_serialize_user` in the
 *  backend (`apps/users/views.py`). */
export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  is_superuser: boolean;
  is_platform_admin: boolean;
  memberships: Membership[];
}

/** Access + refresh JWT pair from the mobile auth endpoints. */
export interface TokenPair {
  access: string;
  refresh: string;
}

/** Public, unauthenticated tenant identity — returned by
 *  `GET /api/public/branding/`, used to validate a workspace slug
 *  before sign-in. */
export interface TenantBranding {
  slug: string;
  name: string;
  logo_url: string | null;
  primary_color: string | null;
}

/** The workspace the operator has chosen — persisted so the app opens
 *  straight to its branded login next launch. */
export interface Workspace {
  slug: string;
  name: string;
  /** Tenant logo, shown on the login screen. Null when the spa has
   *  not uploaded one. */
  logoUrl: string | null;
}
