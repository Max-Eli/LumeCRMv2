/**
 * `NotesTab` — clinical chart notes for a customer.
 *
 * The provider-facing surface for the customer's chart record.
 * Front desk + bookkeeper + marketing roles get a "no access"
 * state instead of the form (matches the backend gate; the
 * server is the security boundary, this is the UX hint).
 *
 * Layout:
 *   - **New note form** at the top (only for roles with
 *     SIGN_CHART). Textarea + "Sign note" button. On submit,
 *     prepends the new note to the thread.
 *   - **Thread** below — newest first. Each entry shows the
 *     author + timestamp + body. Within the 60-min edit window
 *     and only for the original author, an inline "Edit" button
 *     appears. After lock, body is read-only.
 *
 * See [ADR 0015 — Clinical chart notes](../../../docs/decisions/0015-clinical-chart-notes.md)
 * for the design rationale (edit-window semantics, immutability,
 * audit posture).
 */

'use client';

import {
  Ban,
  CheckCircle2,
  ClipboardList,
  Clock,
  CornerDownRight,
  Edit3,
  Lock,
  MessageSquarePlus,
  Pencil,
  ShieldCheck,
  Stethoscope,
  X,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { ApiError } from '@/lib/api';
import { useCurrentMembership, useUser } from '@/lib/auth';
import {
  type ChartNote,
  canSignCharts,
  canViewCharts,
  canVoidCharts,
  chartAuthorName,
  chartEditMinutesRemaining,
  useAddAddendum,
  useCreateChartNote,
  useCustomerChartNotes,
  useUpdateChartNote,
  useVoidChartNote,
} from '@/lib/charts';
import { cn } from '@/lib/utils';

export function NotesTab({ customerId }: { customerId: number }) {
  const me = useCurrentMembership();
  const { data: user } = useUser();
  const canRead = canViewCharts(me?.role);
  const canSign = canSignCharts(me?.role);
  const canVoid = canVoidCharts(me?.role);

  if (!canRead) {
    return <NoAccessState />;
  }

  // Identify "my notes" by email match against the note's
  // `author_email`. The Membership type doesn't expose an id, so
  // email is the cleanest cross-reference. The notes API is tenant-
  // scoped, so cross-tenant collision via shared email isn't a
  // concern — a single user belonging to two tenants only sees the
  // notes of the tenant they're currently active in.
  return (
    <NotesTabBody
      customerId={customerId}
      canSign={canSign}
      canVoid={canVoid}
      myEmail={user?.email ?? ''}
    />
  );
}

function NoAccessState() {
  return (
    <div className="rounded-lg border border-dashed bg-muted/20 p-8 text-center max-w-2xl">
      <div className="inline-flex size-10 items-center justify-center rounded-full bg-card text-muted-foreground border mb-3">
        <Lock className="size-4" />
      </div>
      <h3 className="font-serif text-base font-semibold tracking-tight">
        Chart notes are clinical-only
      </h3>
      <p className="text-xs text-muted-foreground mt-2 leading-relaxed max-w-md mx-auto">
        Provider, manager, and owner roles can read and sign clinical chart
        notes here. Your role doesn&rsquo;t include chart access — this is by
        design (HIPAA minimum-necessary disclosure).
      </p>
    </div>
  );
}

function NotesTabBody({
  customerId,
  canSign,
  canVoid,
  myEmail,
}: {
  customerId: number;
  canSign: boolean;
  canVoid: boolean;
  myEmail: string;
}) {
  const { data: notes, isLoading, error } = useCustomerChartNotes(customerId);

  // Group flat list into threads: top-level notes, each with their
  // addenda sorted by signed_at ascending (chronological within the
  // thread) so a reviewer reads the original first, then each
  // addendum in order.
  const threads = useMemo(() => groupIntoThreads(notes ?? []), [notes]);

  return (
    <div className="space-y-6 max-w-3xl">
      {canSign ? <NewNoteForm customerId={customerId} /> : null}

      <PrivacyBanner />

      {isLoading ? (
        <div className="rounded-md border bg-card p-6 text-sm text-muted-foreground">
          Loading chart…
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] p-4 text-sm text-destructive">
          Could not load chart notes.
        </div>
      ) : threads.length === 0 ? (
        <EmptyThread />
      ) : (
        <ul className="space-y-4">
          {threads.map((thread) => (
            <NoteThread
              key={thread.parent.id}
              parent={thread.parent}
              addenda={thread.addenda}
              myEmail={myEmail}
              canSign={canSign}
              canVoid={canVoid}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

interface NoteThreadModel {
  parent: ChartNote;
  addenda: ChartNote[];
}

function groupIntoThreads(notes: ChartNote[]): NoteThreadModel[] {
  // Top-level: parent_note_id is null. Sorted desc by signed_at
  // (newest activity at top); the API already returns them in this
  // order but we re-sort defensively in case future filters change
  // server ordering.
  const tops = notes
    .filter((n) => n.parent_note_id === null)
    .sort((a, b) => b.signed_at.localeCompare(a.signed_at));

  const addendaByParent = new Map<number, ChartNote[]>();
  for (const n of notes) {
    if (n.parent_note_id !== null) {
      const arr = addendaByParent.get(n.parent_note_id) ?? [];
      arr.push(n);
      addendaByParent.set(n.parent_note_id, arr);
    }
  }
  // Within a thread, addenda render chronologically (oldest first)
  // so the reviewer reads the conversation in order.
  for (const arr of addendaByParent.values()) {
    arr.sort((a, b) => a.signed_at.localeCompare(b.signed_at));
  }

  return tops.map((parent) => ({
    parent,
    addenda: addendaByParent.get(parent.id) ?? [],
  }));
}

// ── Privacy banner ──────────────────────────────────────────────────

function PrivacyBanner() {
  return (
    <div className="rounded-md border border-accent/30 bg-accent/[0.04] px-3 py-2.5 flex items-start gap-2 text-xs">
      <ShieldCheck className="size-3.5 shrink-0 text-accent mt-0.5" />
      <p className="text-foreground/90 leading-relaxed">
        Chart notes are <span className="font-medium">PHI</span>. Reads and
        writes are audit-logged. Notes lock for editing 60 minutes after
        signing — write carefully.
      </p>
    </div>
  );
}

// ── Empty state ─────────────────────────────────────────────────────

function EmptyThread() {
  return (
    <div className="rounded-lg border border-dashed bg-muted/20 p-8 text-center">
      <div className="inline-flex size-10 items-center justify-center rounded-full bg-card text-muted-foreground border mb-3">
        <ClipboardList className="size-4" />
      </div>
      <h3 className="font-serif text-base font-semibold tracking-tight">
        No chart notes yet
      </h3>
      <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
        Sign your first note above. Treatment observations, dose / lot / site
        details, and post-op care all live here.
      </p>
    </div>
  );
}

// ── New-note form ───────────────────────────────────────────────────

function NewNoteForm({ customerId }: { customerId: number }) {
  const create = useCreateChartNote();
  const [body, setBody] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = body.trim();
    if (!trimmed) {
      setError('Write something before signing.');
      return;
    }
    create.mutate(
      { customer_id: customerId, body: trimmed },
      {
        onSuccess: () => {
          toast.success('Chart note signed');
          setBody('');
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 403) {
            setError("You don't have permission to sign chart notes.");
          } else {
            setError('Could not sign note. Please try again.');
          }
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="rounded-lg border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Stethoscope className="size-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold text-foreground">New chart note</h3>
      </div>

      <Field>
        <FieldLabel className="sr-only">Chart note body</FieldLabel>
        <textarea
          rows={5}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Treatment performed, observations, dose / lot / site, post-op care…"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm leading-relaxed font-mono focus:outline-hidden focus:ring-2 focus:ring-ring/40"
        />
      </Field>

      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : null}

      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[11px] text-muted-foreground">
          You can edit your note for 60 minutes after signing. After that, it
          locks.
        </p>
        <Button
          type="submit"
          size="sm"
          disabled={create.isPending || !body.trim()}
        >
          <CheckCircle2 className="size-3.5" />
          {create.isPending ? 'Signing…' : 'Sign note'}
        </Button>
      </div>
    </form>
  );
}

// ── Note thread (parent + addenda) ──────────────────────────────────

function NoteThread({
  parent,
  addenda,
  myEmail,
  canSign,
  canVoid,
}: {
  parent: ChartNote;
  addenda: ChartNote[];
  myEmail: string;
  canSign: boolean;
  canVoid: boolean;
}) {
  const [addendumOpen, setAddendumOpen] = useState(false);

  // Show "Add addendum" button when:
  // - caller can sign
  // - parent is locked (within-window edits go through the parent's
  //   own edit button, not addenda)
  // - parent isn't voided (a voided note can't accept addenda)
  const canAddAddendum = canSign && parent.is_locked && !parent.is_voided;

  return (
    <li>
      <NoteCard
        note={parent}
        isMine={emailMatches(parent.author_email, myEmail)}
        canVoid={canVoid && !parent.is_voided && parent.is_locked}
      />

      {/* Addenda — indented + connected via a left bar */}
      {addenda.length > 0 ? (
        <ul className="ml-6 mt-2 space-y-2 border-l-2 border-border pl-4">
          {addenda.map((a) => (
            <li key={a.id}>
              <NoteCard
                note={a}
                isMine={emailMatches(a.author_email, myEmail)}
                canVoid={canVoid && !a.is_voided && a.is_locked}
                isAddendum
              />
            </li>
          ))}
        </ul>
      ) : null}

      {/* Add-addendum action lives below the thread so the parent
          card stays focused on its own state. */}
      {canAddAddendum ? (
        <div className="ml-6 mt-2">
          {addendumOpen ? (
            <AddendumForm
              parentId={parent.id}
              onCancel={() => setAddendumOpen(false)}
              onDone={() => setAddendumOpen(false)}
            />
          ) : (
            <button
              type="button"
              onClick={() => setAddendumOpen(true)}
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <CornerDownRight className="size-3" />
              Add addendum
            </button>
          )}
        </div>
      ) : null}
    </li>
  );
}

function emailMatches(a: string, b: string): boolean {
  return a.length > 0 && b.length > 0 && a.toLowerCase() === b.toLowerCase();
}

// ── Single-note card (used for parent + addenda) ────────────────────

function NoteCard({
  note,
  isMine,
  canVoid,
  isAddendum = false,
}: {
  note: ChartNote;
  isMine: boolean;
  canVoid: boolean;
  isAddendum?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [voidConfirmOpen, setVoidConfirmOpen] = useState(false);
  const minutesLeft = chartEditMinutesRemaining(note);
  const canEdit = isMine && !note.is_locked && !note.is_voided;

  return (
    <div
      className={cn(
        'rounded-lg border bg-card p-4 transition-colors',
        editing && 'border-accent/50 ring-1 ring-accent/20',
        note.is_voided && 'border-stone-300 bg-stone-50/60',
        isAddendum && 'bg-card/80',
      )}
    >
      {/* Voided banner — top-of-card, before everything else */}
      {note.is_voided ? (
        <div className="mb-3 rounded-md border border-stone-300 bg-stone-100 px-3 py-2 flex items-start gap-2 text-xs">
          <Ban className="size-3.5 shrink-0 text-stone-700 mt-0.5" />
          <div>
            <p className="font-medium text-stone-900">Voided</p>
            <p className="text-stone-700 mt-0.5">{note.voided_reason}</p>
            {note.voided_at ? (
              <p className="text-stone-500 mt-0.5">
                {formatDateTime(note.voided_at)}
                {note.voided_by_email
                  ? ` · by ${note.voided_by_first_name} ${note.voided_by_last_name}`.replace(
                      /^ · by\s+$/,
                      ` · by ${note.voided_by_email}`,
                    )
                  : ''}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            {isAddendum ? (
              <span className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-blue-50 text-blue-700">
                Addendum
              </span>
            ) : null}
            <span className="text-sm font-medium text-foreground">
              {chartAuthorName(note)}
            </span>
            {note.author_job_title ? (
              <span className="text-[11px] text-muted-foreground">
                · {note.author_job_title}
              </span>
            ) : null}
            {note.author_was_clinical ? (
              <span
                className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-emerald-50 text-emerald-700"
                title="Author held a clinical job title at signing"
              >
                <Stethoscope className="size-2.5" />
                Clinical
              </span>
            ) : null}
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5 tabular-nums">
            Signed {formatDateTime(note.signed_at)}
            {note.appointment_date && !isAddendum ? (
              <>
                {' · '}
                {note.appointment_service_name || 'Appointment'} on{' '}
                {formatDateOnly(note.appointment_date)}
              </>
            ) : null}
          </p>
        </div>
        {!note.is_voided ? (
          <LockBadge note={note} minutesLeft={minutesLeft} />
        ) : null}
      </div>

      {editing ? (
        <EditForm
          note={note}
          onCancel={() => setEditing(false)}
          onDone={() => setEditing(false)}
        />
      ) : (
        <>
          <div
            className={cn(
              'text-sm whitespace-pre-wrap font-mono leading-relaxed',
              note.is_voided ? 'text-stone-500 line-through' : 'text-foreground',
            )}
          >
            {note.body}
          </div>

          {/* Action row: edit (author, within window) + void (manager+, locked).
              Hidden entirely on voided notes (terminal state). */}
          {!note.is_voided && (canEdit || canVoid) ? (
            <div className="mt-3 flex items-center justify-between gap-2 flex-wrap">
              {canEdit ? (
                <p className="text-[11px] text-muted-foreground">
                  {minutesLeft > 0 ? `${minutesLeft} min remaining to edit` : 'Locking now'}
                </p>
              ) : (
                <span />
              )}
              <div className="flex items-center gap-2">
                {canEdit ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => setEditing(true)}
                  >
                    <Edit3 className="size-3" />
                    Edit
                  </Button>
                ) : null}
                {canVoid ? (
                  <button
                    type="button"
                    onClick={() => setVoidConfirmOpen(true)}
                    className="inline-flex items-center gap-1 h-7 px-2 text-xs text-muted-foreground hover:text-red-700 transition-colors"
                  >
                    <Ban className="size-3" />
                    Void
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {voidConfirmOpen ? (
            <VoidForm
              note={note}
              onCancel={() => setVoidConfirmOpen(false)}
              onDone={() => setVoidConfirmOpen(false)}
            />
          ) : null}
        </>
      )}
    </div>
  );
}

function LockBadge({
  note,
  minutesLeft,
}: {
  note: ChartNote;
  minutesLeft: number;
}) {
  if (note.is_locked) {
    return (
      <span
        className="inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-stone-100 text-stone-600"
        title="This note is locked. The 60-minute edit window has closed."
      >
        <Lock className="size-2.5" />
        Locked
      </span>
    );
  }
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-amber-50 text-amber-800"
      title={`${minutesLeft} minute${minutesLeft === 1 ? '' : 's'} until lock`}
    >
      <Clock className="size-2.5" />
      Editable
    </span>
  );
}

// ── Edit form (within window) ───────────────────────────────────────

function EditForm({
  note,
  onCancel,
  onDone,
}: {
  note: ChartNote;
  onCancel: () => void;
  onDone: () => void;
}) {
  const update = useUpdateChartNote(note.id);
  const [body, setBody] = useState(note.body);
  const [error, setError] = useState<string | null>(null);

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = body.trim();
    if (!trimmed) {
      setError('Body cannot be empty.');
      return;
    }
    if (trimmed === note.body) {
      onDone();
      return;
    }
    update.mutate(
      { body: trimmed },
      {
        onSuccess: () => {
          toast.success('Note updated');
          onDone();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 403) {
            const detail =
              typeof err.body === 'object' &&
              err.body &&
              typeof (err.body as { detail?: unknown }).detail === 'string'
                ? String((err.body as { detail: string }).detail)
                : "You can't edit this note.";
            setError(detail);
          } else {
            setError('Could not save changes. Please try again.');
          }
        },
      },
    );
  };

  return (
    <form onSubmit={save} className="space-y-3">
      <textarea
        rows={6}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm leading-relaxed font-mono focus:outline-hidden focus:ring-2 focus:ring-ring/40"
      />
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={update.isPending}>
          <Pencil className="size-3.5" />
          {update.isPending ? 'Saving…' : 'Save edit'}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onCancel}
          disabled={update.isPending}
        >
          <X className="size-3.5" />
          Cancel
        </Button>
      </div>
    </form>
  );
}

// ── Addendum form ───────────────────────────────────────────────────

function AddendumForm({
  parentId,
  onCancel,
  onDone,
}: {
  parentId: number;
  onCancel: () => void;
  onDone: () => void;
}) {
  const add = useAddAddendum(parentId);
  const [body, setBody] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = body.trim();
    if (!trimmed) {
      setError('Write something before signing the addendum.');
      return;
    }
    add.mutate(
      { body: trimmed },
      {
        onSuccess: () => {
          toast.success('Addendum signed');
          setBody('');
          onDone();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && err.body && typeof err.body === 'object') {
            const detail = (err.body as { detail?: unknown }).detail;
            setError(typeof detail === 'string' ? detail : 'Could not add the addendum.');
          } else if (err instanceof ApiError && err.status === 403) {
            setError("You don't have permission to add chart notes.");
          } else {
            setError('Could not add the addendum. Please try again.');
          }
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="rounded-lg border border-blue-200 bg-blue-50/40 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <MessageSquarePlus className="size-4 text-muted-foreground" />
        <h4 className="text-sm font-semibold text-foreground">New addendum</h4>
      </div>
      <textarea
        rows={4}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Correction or follow-up context — referenced to the original note above."
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm leading-relaxed font-mono focus:outline-hidden focus:ring-2 focus:ring-ring/40"
      />
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[11px] text-muted-foreground">
          Addenda also lock 60 minutes after signing.
        </p>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={add.isPending}
          >
            <X className="size-3.5" />
            Cancel
          </Button>
          <Button type="submit" size="sm" disabled={add.isPending || !body.trim()}>
            <CheckCircle2 className="size-3.5" />
            {add.isPending ? 'Signing…' : 'Sign addendum'}
          </Button>
        </div>
      </div>
    </form>
  );
}

// ── Void confirmation form ──────────────────────────────────────────

function VoidForm({
  note,
  onCancel,
  onDone,
}: {
  note: ChartNote;
  onCancel: () => void;
  onDone: () => void;
}) {
  const voidNote = useVoidChartNote(note.id);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = reason.trim();
    if (!trimmed) {
      setError('A reason is required.');
      return;
    }
    voidNote.mutate(
      { reason: trimmed },
      {
        onSuccess: () => {
          toast.success('Note voided');
          onDone();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && err.body && typeof err.body === 'object') {
            const detail = (err.body as { detail?: unknown }).detail;
            setError(typeof detail === 'string' ? detail : 'Could not void.');
          } else if (err instanceof ApiError && err.status === 403) {
            setError("You don't have permission to void chart notes.");
          } else {
            setError('Could not void. Please try again.');
          }
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="mt-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 space-y-3">
      <div className="text-sm font-medium text-red-900 inline-flex items-center gap-1.5">
        <Ban className="size-3.5" />
        Void this note?
      </div>
      <p className="text-xs text-red-800 leading-relaxed">
        Voiding is one-way. The note stays in the audit trail with this
        reason recorded. If a void was a mistake, you&rsquo;ll need to write
        a new note explaining and referencing this one.
      </p>
      <Field>
        <FieldLabel className="text-xs">Reason</FieldLabel>
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          placeholder="Wrong patient, signed in error, duplicate entry…"
          className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus:ring-ring/40"
        />
      </Field>
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="destructive"
          size="sm"
          disabled={voidNote.isPending || !reason.trim()}
        >
          <Ban className="size-3.5" />
          {voidNote.isPending ? 'Voiding…' : 'Yes, void'}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onCancel}
          disabled={voidNote.isPending}
        >
          <X className="size-3.5" />
          Cancel
        </Button>
      </div>
    </form>
  );
}

// ── Helpers ────────────────────────────────────────────────────────

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatDateOnly(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
