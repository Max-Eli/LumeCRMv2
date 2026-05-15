/**
 * Saved-replies surfaces — picker popover + manage dialog.
 *
 * Used by the inbox composer:
 *   - **Picker**: small popover anchored to a button next to Send;
 *     click a reply to insert into the textarea, or click "Manage"
 *     to open the dialog.
 *   - **Manage dialog**: full CRUD list — create / rename / edit body /
 *     delete. Tenant-shared, mirrors Front / Boulevard / Slack.
 *
 * Saved replies are NOT PHI (they're tenant brand-voice templates) so
 * the operator-facing UI doesn't need an "are you sure?" double-check
 * for delete — single confirm is fine.
 */

'use client';

import {
  Check,
  ChevronRight,
  Edit3,
  Loader2,
  MessageSquareQuote,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { ApiError } from '@/lib/api';
import {
  type SavedReply,
  useCreateSavedReply,
  useDeleteSavedReply,
  useSavedReplies,
  useUpdateSavedReply,
} from '@/lib/messaging';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

// ── Picker ──────────────────────────────────────────────────────────


export interface SavedRepliesPopoverProps {
  /** Inserts the chosen reply body into the composer. */
  onInsert: (body: string) => void;
  /** Opens the full manage-replies dialog. */
  onManage: () => void;
  /** Composer is disabled — disable the trigger too so the button
   *  doesn't suggest the operator can act. */
  disabled?: boolean;
}

export function SavedRepliesPopover({
  onInsert,
  onManage,
  disabled,
}: SavedRepliesPopoverProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const { data: replies, isLoading } = useSavedReplies();

  // Reset query each time the popover closes so reopening starts fresh.
  useEffect(() => {
    if (!open) setSearch('');
  }, [open]);

  const filtered = useMemo(() => {
    if (!replies) return [];
    if (!search.trim()) return replies;
    const q = search.toLowerCase();
    return replies.filter(
      (r) =>
        r.name.toLowerCase().includes(q) || r.body.toLowerCase().includes(q),
    );
  }, [replies, search]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={disabled}
            aria-label="Insert saved reply"
            title="Insert saved reply"
          >
            <MessageSquareQuote className="size-4" />
          </Button>
        }
        nativeButton={false}
      />
      <PopoverContent
        align="end"
        side="top"
        sideOffset={8}
        className="w-80 p-0 overflow-hidden"
      >
        <div className="border-b px-3 py-2">
          <Input
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search saved replies…"
            className="h-8 text-sm"
          />
        </div>
        <div className="max-h-72 overflow-y-auto">
          {isLoading ? (
            <p className="px-3 py-6 text-xs text-muted-foreground text-center">
              Loading…
            </p>
          ) : (replies?.length ?? 0) === 0 ? (
            <div className="px-3 py-5 text-center">
              <p className="text-xs text-muted-foreground mb-2">
                No saved replies yet.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setOpen(false);
                  onManage();
                }}
              >
                <Plus className="size-3.5" />
                Create your first
              </Button>
            </div>
          ) : filtered.length === 0 ? (
            <p className="px-3 py-6 text-xs text-muted-foreground text-center">
              No replies matching “{search}”.
            </p>
          ) : (
            <ul className="py-1">
              {filtered.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onInsert(r.body);
                      setOpen(false);
                    }}
                    className="w-full text-left px-3 py-2 hover:bg-muted transition-colors group"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium truncate">{r.name}</span>
                      <ChevronRight className="size-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                    <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
                      {r.body}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="border-t px-2 py-2">
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onManage();
            }}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            <Edit3 className="size-3" />
            Manage saved replies
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

// ── Manage dialog ───────────────────────────────────────────────────


export function ManageSavedRepliesDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { data: replies, isLoading } = useSavedReplies();
  const [editingId, setEditingId] = useState<number | 'new' | null>(null);

  // Reset editor each time the dialog closes so reopening starts at
  // the list view.
  useEffect(() => {
    if (!open) setEditingId(null);
  }, [open]);

  const editingReply =
    editingId === 'new'
      ? undefined
      : editingId !== null
        ? replies?.find((r) => r.id === editingId)
        : undefined;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Saved replies</DialogTitle>
        </DialogHeader>
        <DialogBody className="p-0">
          {editingId !== null ? (
            <ReplyEditor
              reply={editingReply}
              onDone={() => setEditingId(null)}
            />
          ) : (
            <ReplyList
              replies={replies ?? []}
              loading={isLoading}
              onEdit={(id) => setEditingId(id)}
              onNew={() => setEditingId('new')}
            />
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

function ReplyList({
  replies,
  loading,
  onEdit,
  onNew,
}: {
  replies: SavedReply[];
  loading: boolean;
  onEdit: (id: number) => void;
  onNew: () => void;
}) {
  const del = useDeleteSavedReply();

  return (
    <div className="flex flex-col">
      <div className="px-6 py-3 border-b flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Reusable snippets for common questions — staff can insert into any reply.
        </p>
        <Button size="sm" onClick={onNew}>
          <Plus className="size-3.5" />
          New reply
        </Button>
      </div>
      <div className="max-h-[60vh] overflow-y-auto">
        {loading ? (
          <p className="px-6 py-10 text-sm text-muted-foreground text-center">Loading…</p>
        ) : replies.length === 0 ? (
          <div className="px-6 py-10 text-center">
            <MessageSquareQuote className="size-8 mx-auto mb-3 text-muted-foreground" />
            <p className="text-sm font-medium">No saved replies yet</p>
            <p className="text-xs text-muted-foreground mt-1 max-w-xs mx-auto">
              Create your first one — try “Address”, “Parking”, or “Running late?”
            </p>
            <Button size="sm" onClick={onNew} className="mt-4">
              <Plus className="size-3.5" />
              New reply
            </Button>
          </div>
        ) : (
          <ul className="divide-y">
            {replies.map((r) => (
              <li key={r.id} className="px-6 py-3 flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{r.name}</p>
                  <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
                    {r.body}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => onEdit(r.id)}
                    aria-label={`Edit ${r.name}`}
                    title="Edit"
                  >
                    <Pencil className="size-3.5" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      if (window.confirm(`Delete "${r.name}"?`)) {
                        del.mutate(r.id);
                      }
                    }}
                    aria-label={`Delete ${r.name}`}
                    title="Delete"
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ReplyEditor({
  reply,
  onDone,
}: {
  reply: SavedReply | undefined;
  onDone: () => void;
}) {
  const isNew = reply === undefined;
  const [name, setName] = useState(reply?.name ?? '');
  const [body, setBody] = useState(reply?.body ?? '');
  const [error, setError] = useState<string | null>(null);
  const create = useCreateSavedReply();
  const update = useUpdateSavedReply(reply?.id ?? 0);
  const pending = create.isPending || update.isPending;

  const onSave = async () => {
    setError(null);
    const trimmedName = name.trim();
    const trimmedBody = body.trim();
    if (!trimmedName || !trimmedBody) {
      setError('Both name and body are required.');
      return;
    }
    try {
      if (isNew) {
        await create.mutateAsync({ name: trimmedName, body: trimmedBody });
      } else {
        await update.mutateAsync({ name: trimmedName, body: trimmedBody });
      }
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const b = err.body as Record<string, string | string[]>;
        const firstError =
          (Array.isArray(b.name) ? b.name[0] : b.name) ??
          (Array.isArray(b.body) ? b.body[0] : b.body) ??
          (Array.isArray(b.detail) ? b.detail[0] : b.detail);
        setError(typeof firstError === 'string' ? firstError : 'Could not save.');
      } else {
        setError('Could not save.');
      }
    }
  };

  return (
    <>
      <div className="px-6 py-4 space-y-3">
        <div>
          <label htmlFor="reply-name" className="text-xs font-medium mb-1.5 block">
            Name
          </label>
          <Input
            id="reply-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Address"
            maxLength={80}
            autoFocus={isNew}
          />
        </div>
        <div>
          <label htmlFor="reply-body" className="text-xs font-medium mb-1.5 block">
            Message
          </label>
          <textarea
            id="reply-body"
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Type the reply text…"
            maxLength={1600}
            className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none resize-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <p className="mt-1 text-[10px] text-muted-foreground">
            {body.length}/1600 chars
          </p>
        </div>
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone} disabled={pending}>
          Cancel
        </Button>
        <Button type="button" onClick={onSave} disabled={pending}>
          {pending ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
          {isNew ? 'Create' : 'Save'}
        </Button>
      </DialogFooter>
    </>
  );
}
