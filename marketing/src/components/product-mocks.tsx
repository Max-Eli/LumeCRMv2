/**
 * Inline product UI mockups for the marketing site.
 *
 * Each mock is a small HTML/CSS rendering of the actual CRM surface
 * — the calendar, a client chart, a consent form, an invoice, the
 * reports library, the location switcher. Built in code (not as
 * stock illustrations or PNG screenshots) so they:
 *
 *   - render crisp at any density
 *   - inherit the brand palette automatically
 *   - stay in sync with the real product if the brand evolves
 *   - keep the bundle small (no large image assets)
 *
 * They're decorative — the mocks aren't fully accurate to every
 * detail of the live CRM. They're accurate to the SHAPE of each
 * surface so the buyer's mental model maps cleanly when they sign
 * in for the first time.
 */

import { cn } from '@/lib/utils';

// ── Calendar ──────────────────────────────────────────────────────────

const CAL_HOURS = ['9 am', '10 am', '11 am', '12 pm', '1 pm', '2 pm'];
const CAL_PROVIDERS = ['Sarah', 'Jamie', 'Marco'];
const CAL_APPOINTMENTS = [
  { col: 0, row: 0, span: 2, label: 'Botox 30u', client: 'L. Davis', tone: 'rose' },
  { col: 0, row: 3, span: 1, label: 'Filler', client: 'M. Tran', tone: 'amber' },
  { col: 1, row: 1, span: 2, label: 'HydraFacial', client: 'S. Kim', tone: 'emerald' },
  { col: 1, row: 4, span: 1, label: 'Consult', client: 'New', tone: 'sky' },
  { col: 2, row: 0, span: 1, label: 'Laser', client: 'P. Rao', tone: 'rose' },
  { col: 2, row: 2, span: 3, label: 'Microneedling', client: 'A. Lee', tone: 'violet' },
];

const TONE_CLASSES: Record<string, string> = {
  rose: 'bg-rose-100 border-rose-300/60 text-rose-900',
  amber: 'bg-amber-100 border-amber-300/60 text-amber-900',
  emerald: 'bg-emerald-100 border-emerald-300/60 text-emerald-900',
  sky: 'bg-sky-100 border-sky-300/60 text-sky-900',
  violet: 'bg-violet-100 border-violet-300/60 text-violet-900',
};

export function CalendarMock() {
  return (
    <div className="absolute inset-0 flex flex-col">
      {/* Date strip */}
      <div className="flex items-center justify-between border-b border-foreground/10 px-5 py-3 text-[11px]">
        <div className="flex items-center gap-3">
          <span className="font-serif text-base font-medium">Thursday, May 15</span>
          <span className="text-foreground/40">·</span>
          <span className="text-foreground/55">Manhattan</span>
        </div>
        <span className="rounded-full bg-foreground/[0.04] px-2.5 py-1 font-mono text-[10px] text-foreground/55">
          Today
        </span>
      </div>

      {/* Provider header */}
      <div className="grid border-b border-foreground/10 text-[10px]" style={{ gridTemplateColumns: '40px repeat(3, 1fr)' }}>
        <div />
        {CAL_PROVIDERS.map((p) => (
          <div key={p} className="border-l border-foreground/10 px-3 py-2">
            <p className="font-medium text-foreground">{p}</p>
            <p className="text-foreground/45">Available</p>
          </div>
        ))}
      </div>

      {/* Time grid */}
      <div className="relative flex-1 overflow-hidden">
        <div className="absolute inset-0 grid" style={{ gridTemplateColumns: '40px repeat(3, 1fr)', gridTemplateRows: `repeat(${CAL_HOURS.length}, 1fr)` }}>
          {CAL_HOURS.map((h) => (
            <div key={h} className="border-b border-foreground/5 px-1.5 pt-0.5 text-[9px] text-foreground/45">{h}</div>
          ))}
          {CAL_HOURS.map((_, rowIdx) =>
            CAL_PROVIDERS.map((_, colIdx) => (
              <div
                key={`${rowIdx}-${colIdx}`}
                className="border-b border-l border-foreground/5"
                style={{ gridRow: rowIdx + 1, gridColumn: colIdx + 2 }}
              />
            )),
          )}
          {CAL_APPOINTMENTS.map((a, i) => (
            <div
              key={i}
              className={cn(
                'm-1 rounded-md border px-2 py-1 text-[10px] leading-tight overflow-hidden',
                TONE_CLASSES[a.tone],
              )}
              style={{
                gridRow: `${a.row + 1} / span ${a.span}`,
                gridColumn: a.col + 2,
              }}
            >
              <p className="font-medium truncate">{a.label}</p>
              <p className="opacity-75 truncate">{a.client}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Client chart ──────────────────────────────────────────────────────

export function ChartMock() {
  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="flex items-center gap-3 border-b border-foreground/10 px-5 py-3">
        <div className="flex size-10 items-center justify-center rounded-full bg-rose-100 font-medium text-rose-900">SC</div>
        <div className="min-w-0">
          <p className="font-serif text-base font-medium">Sarah Chen</p>
          <p className="text-[10px] text-foreground/55">Client since Mar 2024 · 12 visits · Member</p>
        </div>
        <span className="ml-auto rounded-full bg-emerald-100 px-2.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-emerald-900">
          Active
        </span>
      </div>

      <div className="flex border-b border-foreground/10 text-[11px]">
        {['Overview', 'Appointments', 'Charts', 'Forms', 'Invoices'].map((t, i) => (
          <span
            key={t}
            className={cn(
              'border-b-2 px-4 py-2',
              i === 0 ? 'border-accent text-foreground' : 'border-transparent text-foreground/55',
            )}
          >
            {t}
          </span>
        ))}
      </div>

      <div className="flex-1 grid grid-cols-2 gap-3 p-4 text-[11px]">
        <Field label="Phone" value="(555) 234-1180" />
        <Field label="Email" value="sarah.chen@…" />
        <Field label="Date of birth" value="Jan 14, 1989" />
        <Field label="Allergies" value="Penicillin" />
        <div className="col-span-2 mt-1 rounded-md border border-foreground/10 bg-foreground/[0.02] px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-foreground/55">Pending forms</p>
          <p className="mt-1 text-foreground">Botox consent · per-visit · expires today</p>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[9px] uppercase tracking-wide text-foreground/55">{label}</p>
      <p className="mt-0.5 text-foreground">{value}</p>
    </div>
  );
}

// ── Form / e-sign ─────────────────────────────────────────────────────

export function FormMock() {
  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="border-b border-foreground/10 px-5 py-3">
        <p className="font-serif text-base font-medium">Botox & Neurotoxin Consent</p>
        <p className="text-[10px] text-foreground/55">Version 4 · For: Sarah Chen · Tokenized link</p>
      </div>
      <div className="flex-1 space-y-3 px-5 py-4 text-[11px]">
        <Check checked label="I am not pregnant or nursing." />
        <Check checked label="I have not received Botox in the last 90 days." />
        <Check checked label="I understand the risks: bruising, headache, asymmetry." />
        <Check label="I consent to before / after photography." />
        <div className="mt-3 rounded-md border border-dashed border-foreground/20 px-4 py-3">
          <p className="text-[10px] uppercase tracking-wide text-foreground/55">Signature</p>
          <svg viewBox="0 0 200 30" className="mt-1 h-7 w-full">
            <path
              d="M2 22 C 20 4, 40 28, 60 18 S 100 6, 130 20 S 170 12, 198 18"
              fill="none"
              stroke="var(--foreground)"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </div>
      </div>
    </div>
  );
}

function Check({ checked = false, label }: { checked?: boolean; label: string }) {
  return (
    <div className="flex items-start gap-2">
      <span
        className={cn(
          'mt-0.5 inline-flex size-4 items-center justify-center rounded border',
          checked ? 'border-accent bg-accent text-background' : 'border-foreground/30 bg-background',
        )}
      >
        {checked ? <span className="text-[9px] leading-none">✓</span> : null}
      </span>
      <span className={cn(checked ? 'text-foreground' : 'text-foreground/65')}>{label}</span>
    </div>
  );
}

// ── Invoice ───────────────────────────────────────────────────────────

export function InvoiceMock() {
  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="flex items-center justify-between border-b border-foreground/10 px-5 py-3">
        <div>
          <p className="font-serif text-base font-medium">Invoice INV-2026-0214</p>
          <p className="text-[10px] text-foreground/55">L. Davis · Today, 11:40 am · Sarah Chen</p>
        </div>
        <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-amber-900">
          Open
        </span>
      </div>
      <div className="flex-1 px-5 py-4 text-[11px]">
        <table className="w-full">
          <thead>
            <tr className="border-b border-foreground/10 text-[9px] uppercase tracking-wide text-foreground/55">
              <th className="pb-1.5 text-left font-medium">Item</th>
              <th className="pb-1.5 text-right font-medium">Qty</th>
              <th className="pb-1.5 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-foreground/5">
            <tr><td className="py-2">Botox 30u</td><td className="py-2 text-right tabular-nums">1</td><td className="py-2 text-right tabular-nums">$540.00</td></tr>
            <tr><td className="py-2">HydraFacial add-on</td><td className="py-2 text-right tabular-nums">1</td><td className="py-2 text-right tabular-nums">$180.00</td></tr>
          </tbody>
        </table>
        <div className="mt-4 ml-auto w-48 space-y-1">
          <Row label="Subtotal" value="$720.00" />
          <Row label="Tax (8.875%)" value="$63.90" />
          <div className="my-1 h-px bg-foreground/10" />
          <Row label="Total" value="$783.90" bold />
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t border-foreground/10 px-5 py-3">
        <span className="rounded-full border border-foreground/20 px-3 py-1 text-[10px] text-foreground/65">Void</span>
        <span className="rounded-full bg-foreground px-3 py-1 text-[10px] font-medium text-background">Take payment</span>
      </div>
    </div>
  );
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span className="text-foreground/65">{label}</span>
      <span className={cn('tabular-nums', bold ? 'font-semibold text-foreground' : 'text-foreground')}>{value}</span>
    </div>
  );
}

// ── Reports ───────────────────────────────────────────────────────────

const REPORT_BARS = [22, 38, 30, 48, 56, 42, 62, 70, 58, 74, 80, 68, 88, 94, 78, 86, 100, 92, 96, 88];

export function ReportsMock() {
  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="flex items-center justify-between border-b border-foreground/10 px-5 py-3">
        <div>
          <p className="font-serif text-base font-medium">Sales — last 30 days</p>
          <p className="text-[10px] text-foreground/55">Apr 16 → May 15 · 4 paid invoices today</p>
        </div>
        <span className="rounded-full bg-foreground/[0.04] px-2.5 py-1 text-[10px] text-foreground/65">CSV</span>
      </div>
      <div className="grid grid-cols-3 gap-2 px-5 pt-3 text-[10px]">
        <Tile label="Gross" value="$48.6k" />
        <Tile label="Tax" value="$4.31k" />
        <Tile label="Avg invoice" value="$483" />
      </div>
      <div className="flex flex-1 items-end gap-[3px] px-5 pb-4 pt-3">
        {REPORT_BARS.map((h, i) => (
          <div
            key={i}
            className="flex-1 rounded-sm bg-accent/15"
            style={{ height: `${h}%` }}
          >
            <div
              className="rounded-sm bg-accent"
              style={{ height: `${Math.max(h - 30, 6)}%` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-foreground/10 px-2.5 py-1.5">
      <p className="text-[8px] uppercase tracking-wide text-foreground/55">{label}</p>
      <p className="mt-0.5 font-serif text-base font-medium tabular-nums">{value}</p>
    </div>
  );
}

// ── Locations ─────────────────────────────────────────────────────────

const LOCATIONS = [
  { name: 'Manhattan', subtitle: 'Flagship · 8 providers', revenue: '$28.4k', change: '+12%' },
  { name: 'Brooklyn', subtitle: '5 providers', revenue: '$14.1k', change: '+4%' },
  { name: 'Hudson Yards', subtitle: 'Opened Mar · 3 providers', revenue: '$6.1k', change: '+38%' },
];

export function LocationsMock() {
  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="flex items-center justify-between border-b border-foreground/10 px-5 py-3">
        <div>
          <p className="font-serif text-base font-medium">All locations · Rollup</p>
          <p className="text-[10px] text-foreground/55">3 sites · Last 30 days</p>
        </div>
      </div>
      <div className="flex-1 divide-y divide-foreground/10">
        {LOCATIONS.map((l) => (
          <div key={l.name} className="flex items-center justify-between px-5 py-3">
            <div className="flex items-center gap-3">
              <span className="inline-flex size-9 items-center justify-center rounded-full bg-foreground/[0.04] text-[10px] uppercase tracking-wide text-foreground/65">
                {l.name.split(' ').map((w) => w[0]).join('').slice(0, 2)}
              </span>
              <div>
                <p className="text-[12px] font-medium">{l.name}</p>
                <p className="text-[10px] text-foreground/55">{l.subtitle}</p>
              </div>
            </div>
            <div className="text-right">
              <p className="font-serif text-sm font-medium tabular-nums">{l.revenue}</p>
              <p className="text-[10px] text-emerald-700">{l.change}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Audit log ─────────────────────────────────────────────────────────

const AUDIT_ENTRIES = [
  {
    actor: 'sarah.kim',
    action: 'PHI_READ',
    resource: 'customer:c-4218',
    detail: 'Opened chart',
    ip: '192.0.2.14',
    timestamp: '14:22:09',
  },
  {
    actor: 'marco.diaz',
    action: 'FORM_SIGNED',
    resource: 'consent:botox-v3:c-4218',
    detail: 'Submitted',
    ip: '203.0.113.51',
    timestamp: '14:18:51',
  },
  {
    actor: 'sarah.kim',
    action: 'INVOICE_CLOSED',
    resource: 'invoice:inv-9824',
    detail: 'Closed · $612.00 · card',
    ip: '192.0.2.14',
    timestamp: '14:11:33',
  },
  {
    actor: 'system',
    action: 'REPORT_EXPORT',
    resource: 'report:sales-by-date',
    detail: 'CSV · phi_confirmed=true',
    ip: '—',
    timestamp: '14:05:02',
  },
  {
    actor: 'owner.lee',
    action: 'PERMISSION_GRANT',
    resource: 'role:bookkeeper · user:r-3120',
    detail: 'financial_reports.view',
    ip: '198.51.100.7',
    timestamp: '13:47:18',
  },
];

const ACTION_TONE: Record<string, string> = {
  PHI_READ: 'text-foreground/70',
  FORM_SIGNED: 'text-accent',
  INVOICE_CLOSED: 'text-foreground/70',
  REPORT_EXPORT: 'text-accent',
  PERMISSION_GRANT: 'text-foreground/70',
};

export function AuditLogMock() {
  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="flex items-center justify-between border-b border-foreground/10 px-5 py-3">
        <div>
          <p className="font-serif text-base font-medium">Audit log</p>
          <p className="text-[10px] text-foreground/55">Last 60 minutes · append-only</p>
        </div>
        <span className="rounded-full bg-foreground/[0.04] px-2.5 py-1 font-mono text-[10px] text-foreground/55">
          Live
        </span>
      </div>
      <div className="flex items-center gap-4 border-b border-foreground/10 bg-foreground/[0.02] px-5 py-2 text-[9px] uppercase tracking-wide text-foreground/45">
        <span className="w-16">Time</span>
        <span className="w-20">Actor</span>
        <span className="w-28">Action</span>
        <span className="flex-1">Resource</span>
        <span className="w-20">IP</span>
      </div>
      <div className="flex-1 divide-y divide-foreground/5 overflow-hidden">
        {AUDIT_ENTRIES.map((e, i) => (
          <div
            key={i}
            className="flex items-center gap-4 px-5 py-2 font-mono text-[10px] tabular-nums"
          >
            <span className="w-16 text-foreground/55">{e.timestamp}</span>
            <span className="w-20 truncate text-foreground/85">{e.actor}</span>
            <span className={cn('w-28 truncate font-medium', ACTION_TONE[e.action])}>
              {e.action}
            </span>
            <span className="flex-1 truncate text-foreground/65">
              <span className="text-foreground/40">{e.resource}</span>
              <span className="ml-2 text-foreground/55">{e.detail}</span>
            </span>
            <span className="w-20 truncate text-foreground/45">{e.ip}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
