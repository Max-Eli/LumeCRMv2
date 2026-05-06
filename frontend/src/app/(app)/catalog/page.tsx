/**
 * `/catalog` — bare URL bounces to `/catalog/services`. The Catalog
 * surface is sub-page-driven (Categories / Services / Products /
 * Memberships / Packages); the naked `/catalog` link from the
 * sidebar always lands on the services list.
 */

import { redirect } from 'next/navigation';

export default function CatalogIndex() {
  redirect('/catalog/services');
}
