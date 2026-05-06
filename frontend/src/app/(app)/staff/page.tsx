/**
 * `/staff` — bare URL bounces to `/staff/employees`. The Staff surface
 * is sub-page-driven (Employees / Schedule / Check-in / Payroll); the
 * naked `/staff` link from the sidebar always lands on the roster.
 */

import { redirect } from 'next/navigation';

export default function StaffIndex() {
  redirect('/staff/employees');
}
