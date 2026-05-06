/**
 * "Download CSV" button for a report. For `none` and `aggregated`
 * PHI tiers, clicking the button triggers an immediate download. For
 * `per_customer` reports it opens a confirmation modal ("This export
 * contains client names…") and downloads only after the operator
 * clicks Download.
 *
 * The actual CSV streaming is server-side (`?download=csv` on the
 * report endpoint, see ADR 0013). The frontend fetches with the
 * standard `api` wrapper (which forwards the X-Tenant-Slug header
 * needed in dev) and turns the response into a Blob → object URL →
 * temporary anchor click. We can't use a plain `<a href>` because
 * the browser navigation skips our custom auth header and the
 * backend would 404 in dev (prod subdomains would still work).
 */

'use client';

import { Download, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ACTIVE_TENANT_COOKIE } from '@/lib/api';
import type { PhiTier } from '@/lib/reports';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface ExportCsvButtonProps {
  /** Path of the report endpoint, e.g. `/api/reports/financial/sales-by-date-range/`. */
  reportPath: string;
  /** PHI sensitivity — drives whether the confirmation modal fires. */
  phiTier: PhiTier;
  /** All current report params (date_from, date_to, days, etc.). Forwarded
   *  as query string on the export URL so the CSV reflects the on-screen view. */
  params: Record<string, string | undefined>;
  /** Disabled while the report itself is loading — no point exporting nothing. */
  disabled?: boolean;
}

export function ExportCsvButton({
  reportPath,
  phiTier,
  params,
  disabled = false,
}: ExportCsvButtonProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const requiresConfirm = phiTier === 'per_customer';

  const runDownload = async (phiConfirmed: boolean) => {
    setDownloading(true);
    try {
      await downloadCsv(reportPath, params, phiConfirmed);
    } catch (err) {
      console.error('CSV export failed', err);
      toast.error('Could not download CSV. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

  const handleClick = () => {
    if (requiresConfirm) {
      setConfirmOpen(true);
      return;
    }
    void runDownload(false);
  };

  const handleConfirm = () => {
    setConfirmOpen(false);
    void runDownload(true);
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={handleClick}
        disabled={disabled || downloading}
        className="gap-1.5"
      >
        <Download className="size-3.5" aria-hidden />
        {downloading ? 'Downloading…' : 'Download CSV'}
      </Button>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 font-serif">
              <ShieldCheck className="size-4 text-amber-700 dark:text-amber-400" aria-hidden />
              Confirm PHI export
            </DialogTitle>
            <DialogDescription>
              This export contains <strong>client names, contact info, and
              treatment data</strong>. By downloading, you confirm this access
              is necessary for spa operations and that the file will be
              handled per HIPAA minimum-necessary requirements.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            The download will be logged in the audit trail with your name,
            the report, and a confirmation flag.
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleConfirm} className="gap-1.5">
              <Download className="size-3.5" aria-hidden />
              Download
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

async function downloadCsv(
  reportPath: string,
  params: Record<string, string | undefined>,
  phiConfirmed: boolean,
): Promise<void> {
  const usp = new URLSearchParams();
  usp.set('download', 'csv');
  if (phiConfirmed) usp.set('phi_confirmed', 'true');
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') usp.set(k, v);
  }

  // Browser navigation (`<a href>`) skips our custom X-Tenant-Slug
  // header, which the dev backend needs to resolve the tenant. So
  // we fetch with credentials + the header, then turn the streamed
  // response into a Blob and trigger an anchor click against an
  // object URL. The end-user UX is identical (file download via the
  // OS dialog).
  const tenantSlug = readCookie(ACTIVE_TENANT_COOKIE);
  const headers: Record<string, string> = {
    Accept: 'text/csv',
  };
  if (tenantSlug) headers['X-Tenant-Slug'] = tenantSlug;

  const res = await fetch(`${API_URL}${reportPath}?${usp.toString()}`, {
    credentials: 'include',
    headers,
  });
  if (!res.ok) {
    throw new Error(`CSV export failed (${res.status})`);
  }

  const blob = await res.blob();
  const filename = parseFilename(res.headers.get('Content-Disposition'))
    ?? `${reportPath.split('/').filter(Boolean).slice(-1)[0]}.csv`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Free the blob memory after the browser has had a moment to
  // start the download. Same idiom every download-via-blob uses.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/** Pull `filename="..."` out of a Content-Disposition header. */
function parseFilename(header: string | null): string | null {
  if (!header) return null;
  const m = /filename\*?=(?:UTF-8''|")?([^";]+)"?/i.exec(header);
  return m ? decodeURIComponent(m[1]) : null;
}
