/**
 * Social-guest merge banner — appears at the top of a customer detail
 * page when the row was auto-created from an inbound social DM (ADR
 * 0027 §6) and hasn't been merged into a real client record yet.
 *
 * The "Merge into existing client" button opens a search dialog. On
 * select, the operator confirms and we POST to
 * /api/customers/{source_id}/merge-into/{target_id}/ — that endpoint:
 *   - Moves SocialThread + SocialMessage rows to the target
 *   - Preserves acquisition_source on the target (never overwrites)
 *   - Soft-deletes the source guest
 *
 * Owner + manager only (mirrors the backend MANAGE_CLIENT_RECORDS gate).
 * Non-managers see no banner; for clarity we still render the
 * "Social guest from {provider}" label so they understand the row
 * shape.
 */

'use client';

import { useMemo, useState } from 'react';
import { Search, UserPlus2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
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
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  type CustomerDetail,
  type CustomerListItem,
  useCustomers,
  useMergeIntoCustomer,
} from '@/lib/customers';

interface Props {
  customer: CustomerDetail;
  /** Owner + manager only; banner button hides for other roles. */
  canManage: boolean;
}

export function SocialGuestMergeBanner({ customer, canManage }: Props) {
  const [open, setOpen] = useState(false);

  if (!customer.is_social_guest) {
    return null;
  }

  const providerLabel =
    customer.acquisition_source === 'instagram'
      ? 'Instagram'
      : customer.acquisition_source === 'facebook'
        ? 'Facebook Messenger'
        : customer.acquisition_source === 'whatsapp'
          ? 'WhatsApp'
          : 'a social DM';

  const handleLabel = customer.instagram_handle
    ? ` (@${customer.instagram_handle.replace(/^@/, '')})`
    : '';

  return (
    <>
      <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-4 py-3 mt-4 mb-4 flex items-start gap-3 dark:bg-amber-950/30 dark:border-amber-900">
        <div className="flex-shrink-0 mt-0.5">
          <UserPlus2 className="size-5 text-amber-700 dark:text-amber-300" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-amber-900 dark:text-amber-100">
            Unmerged social guest from {providerLabel}
            {handleLabel}
          </p>
          <p className="text-xs text-amber-800/80 dark:text-amber-200/80 mt-0.5">
            This client record was created automatically from an inbound
            DM. Merge it into an existing client to consolidate the
            conversation history with their real profile.
          </p>
        </div>
        {canManage ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setOpen(true)}
            className="flex-shrink-0 border-amber-300 hover:bg-amber-100 dark:border-amber-700 dark:hover:bg-amber-900"
          >
            Merge into existing client
          </Button>
        ) : null}
      </div>

      {canManage ? (
        <MergeDialog
          open={open}
          onOpenChange={setOpen}
          sourceCustomer={customer}
        />
      ) : null}
    </>
  );
}

interface MergeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceCustomer: CustomerDetail;
}

function MergeDialog({ open, onOpenChange, sourceCustomer }: MergeDialogProps) {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<CustomerListItem | null>(null);
  const [confirming, setConfirming] = useState(false);

  // Only search when the query is non-trivial. Avoids a list-everyone
  // round-trip the moment the dialog opens.
  const searchActive = query.trim().length >= 2;
  const customersQuery = useCustomers(searchActive ? { q: query } : undefined);

  const merge = useMergeIntoCustomer(sourceCustomer.id);

  // Filter out the source itself + any other social guests (can't merge
  // a guest into another guest — the backend rejects this 400 anyway).
  const candidates = useMemo(() => {
    if (!customersQuery.data) return [];
    return customersQuery.data.filter(
      (c) => c.id !== sourceCustomer.id && !c.is_social_guest,
    );
  }, [customersQuery.data, sourceCustomer.id]);

  const reset = () => {
    setQuery('');
    setSelected(null);
    setConfirming(false);
  };

  const handleClose = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const handleMerge = () => {
    if (!selected) return;
    merge.mutate(
      { targetId: selected.id },
      {
        onSuccess: () => {
          toast.success(
            `Merged into ${selected.full_name}. Conversation history moved.`,
          );
          handleClose(false);
          router.push(`/clients/${selected.id}`);
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            const body = err.body as { detail?: string } | null;
            toast.error(body?.detail ?? 'Merge failed.');
          } else {
            toast.error('Merge failed. Try again.');
          }
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Merge social guest into existing client</DialogTitle>
          <DialogDescription>
            Search for the client this person actually is. The
            conversation history will move to their profile and this
            social-guest row will be archived.
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 py-4 space-y-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground pointer-events-none" />
            <Input
              type="search"
              placeholder="Search by name, email, or phone…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSelected(null);
              }}
              className="pl-9"
              autoFocus
            />
          </div>

          <div className="border border-border rounded-md max-h-72 overflow-y-auto">
            {!searchActive ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                Type at least 2 characters to search.
              </p>
            ) : customersQuery.isLoading ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                Searching…
              </p>
            ) : candidates.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                No matching clients. (Social-guest rows + this same
                client are excluded from results.)
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {candidates.slice(0, 50).map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(c)}
                      className={
                        'w-full text-left px-3 py-2 hover:bg-muted/40 transition ' +
                        (selected?.id === c.id ? 'bg-accent/15' : '')
                      }
                    >
                      <p className="text-sm font-medium">{c.full_name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {[c.email, c.phone].filter(Boolean).join(' · ') || '(no contact)'}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {selected && !confirming ? (
            <div className="text-xs text-muted-foreground">
              About to merge <span className="font-medium text-foreground">{sourceCustomer.full_name}</span>
              {' '}→ <span className="font-medium text-foreground">{selected.full_name}</span>.
              This cannot be undone.
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleClose(false)}
            disabled={merge.isPending}
          >
            Cancel
          </Button>
          {!confirming ? (
            <Button
              onClick={() => setConfirming(true)}
              disabled={!selected || merge.isPending}
            >
              Continue
            </Button>
          ) : (
            <Button
              onClick={handleMerge}
              disabled={merge.isPending}
              className="bg-amber-600 hover:bg-amber-700 text-white"
            >
              {merge.isPending ? 'Merging…' : 'Confirm merge'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
