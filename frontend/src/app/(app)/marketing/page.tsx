/**
 * `/marketing` — Marketing landing / overview.
 *
 * Top: stat strip (counts of audiences, templates, campaigns, active
 * automations). Middle: four pillar tiles. Bottom: a "what you've
 * been working on" panel with recent audiences + draft / scheduled
 * campaigns + active automations side-by-side.
 */

'use client';

import {
  ArrowRight,
  Cake,
  ChevronRight,
  Clock,
  FileText,
  Heart,
  Lock,
  Mail,
  MessageSquare,
  Send,
  Shield,
  Sparkles,
  Users,
  Zap,
} from 'lucide-react';
import Link from 'next/link';

import { PageHeader } from '@/components/page-header';
import { useCurrentMembership } from '@/lib/auth';
import {
  type TriggerType,
  canAccessMarketing,
  useAudiences,
  useAutomations,
  useCampaigns,
  useTemplates,
} from '@/lib/marketing';
import { cn } from '@/lib/utils';

const TRIGGER_ICONS: Record<TriggerType, React.ComponentType<{ className?: string }>> = {
  birthday: Cake,
  no_visit_days: Clock,
  first_visit_anniversary: Heart,
};

export default function MarketingIndexPage() {
  const me = useCurrentMembership();
  const canAccess = canAccessMarketing(me?.role);

  if (!canAccess) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title="Marketing"
          description="Build segments, compose campaigns, send email and SMS to your customer base."
        />
        <NoAccessState />
      </div>
    );
  }

  return (
    <div className="px-8 py-8 space-y-8">
      <PageHeader
        title="Marketing"
        description="Segment your customer base, compose templates, send campaigns, run always-on automations."
      />

      <StatStrip />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <Tile
          href="/marketing/audiences"
          icon={Users}
          title="Audiences"
          description="Saved customer segments — birthday this month, no-visit-90-days, VIP tag, and so on."
          tone="blue"
        />
        <Tile
          href="/marketing/templates"
          icon={FileText}
          title="Templates"
          description="Reusable email and SMS bodies with personalization tokens. Reuse across campaigns and automations."
          tone="violet"
        />
        <Tile
          href="/marketing/campaigns"
          icon={Send}
          title="Campaigns"
          description="One-shot email + SMS sends. Pick an audience, pick a template, schedule the send."
          tone="amber"
        />
        <Tile
          href="/marketing/automations"
          icon={Zap}
          title="Automations"
          description="Always-on triggered sends. Birthdays, win-back, anniversaries — fire automatically when customers become eligible."
          tone="emerald"
        />
      </div>

      <ComplianceBanner />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <RecentAudiencesPanel />
        <RecentCampaignsPanel />
        <ActiveAutomationsPanel />
      </div>
    </div>
  );
}

// ── Stat strip ──────────────────────────────────────────────────────

function StatStrip() {
  const audiences = useAudiences();
  const templates = useTemplates();
  const campaigns = useCampaigns();
  const automations = useAutomations();

  const audienceCount = audiences.data?.length ?? 0;
  const templateCount = templates.data?.length ?? 0;
  const liveCampaigns =
    campaigns.data?.filter(
      (c) => c.status === 'scheduled' || c.status === 'sending',
    ).length ?? 0;
  const activeAutomations =
    automations.data?.filter((a) => a.is_active).length ?? 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <Stat
        label="Audiences"
        value={audienceCount}
        sublabel="saved segments"
        icon={Users}
      />
      <Stat
        label="Templates"
        value={templateCount}
        sublabel="email + SMS"
        icon={FileText}
      />
      <Stat
        label="Live campaigns"
        value={liveCampaigns}
        sublabel="scheduled or sending"
        icon={Send}
      />
      <Stat
        label="Active automations"
        value={activeAutomations}
        sublabel="firing on triggers"
        icon={Zap}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  sublabel,
  icon: Icon,
}: {
  label: string;
  value: number;
  sublabel: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4 flex items-center gap-4">
      <div className="inline-flex size-10 items-center justify-center rounded-md bg-muted text-muted-foreground shrink-0">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
          {label}
        </p>
        <p className="text-2xl font-semibold tabular-nums leading-tight">
          {value}
        </p>
        <p className="text-[11px] text-muted-foreground truncate">{sublabel}</p>
      </div>
    </div>
  );
}

// ── Pillar tiles ────────────────────────────────────────────────────

const TONE_STYLES: Record<
  'blue' | 'violet' | 'amber' | 'emerald',
  { ring: string; icon: string }
> = {
  blue: { ring: 'hover:border-blue-300/60', icon: 'bg-blue-50 text-blue-700' },
  violet: { ring: 'hover:border-violet-300/60', icon: 'bg-violet-50 text-violet-700' },
  amber: { ring: 'hover:border-amber-300/60', icon: 'bg-amber-50 text-amber-700' },
  emerald: { ring: 'hover:border-emerald-300/60', icon: 'bg-emerald-50 text-emerald-700' },
};

function Tile({
  href,
  icon: Icon,
  title,
  description,
  tone,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  tone: keyof typeof TONE_STYLES;
}) {
  const style = TONE_STYLES[tone];
  return (
    <Link
      href={href}
      className={cn(
        'group rounded-lg border bg-card p-5 transition-all',
        'hover:shadow-sm',
        style.ring,
      )}
    >
      <div className="flex items-start justify-between mb-3">
        <div
          className={cn(
            'inline-flex size-10 items-center justify-center rounded-md',
            style.icon,
          )}
        >
          <Icon className="size-5" />
        </div>
        <ChevronRight className="size-4 text-muted-foreground/60 group-hover:text-foreground group-hover:translate-x-0.5 transition-all" />
      </div>
      <h3 className="font-serif text-lg font-semibold tracking-tight text-foreground">
        {title}
      </h3>
      <p className="text-xs text-muted-foreground leading-relaxed mt-1.5">
        {description}
      </p>
    </Link>
  );
}

// ── Compliance + access states ──────────────────────────────────────

function NoAccessState() {
  return (
    <div className="rounded-lg border border-dashed bg-muted/20 p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-card text-muted-foreground border mb-4">
        <Lock className="size-5" />
      </div>
      <h3 className="font-serif text-lg font-semibold tracking-tight">
        Marketing is owner / manager / marketing roles only
      </h3>
      <p className="text-sm text-muted-foreground mt-2 leading-relaxed max-w-md mx-auto">
        Your role doesn&rsquo;t include the
        <span className="font-mono mx-1 rounded bg-muted px-1 py-0.5 text-xs">VIEW_AUDIENCE_SEGMENTS</span>
        permission. Speak to your owner if you need access.
      </p>
    </div>
  );
}

function ComplianceBanner() {
  return (
    <div className="rounded-lg border border-accent/30 bg-accent/[0.04] px-5 py-4 flex items-start gap-3">
      <Shield className="size-5 shrink-0 text-accent mt-0.5" />
      <div className="text-sm leading-relaxed">
        <p className="font-medium text-foreground">Compliance built in.</p>
        <p className="text-muted-foreground mt-1">
          Marketing email + SMS only sends to customers who&rsquo;ve given
          explicit opt-in per channel. Suppression beats opt-in &mdash; once
          someone unsubscribes or replies STOP, they&rsquo;re permanently
          excluded. CAN-SPAM unsubscribe links and TCPA quiet-hours
          enforcement are automatic.
        </p>
      </div>
    </div>
  );
}

// ── Recent / live panels ────────────────────────────────────────────

function PanelHeader({
  title,
  href,
}: {
  title: string;
  href: string;
}) {
  return (
    <div className="flex items-baseline justify-between mb-3">
      <h2 className="text-sm font-medium uppercase tracking-wider text-foreground">
        {title}
      </h2>
      <Link
        href={href}
        className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
      >
        See all
        <ArrowRight className="size-3" />
      </Link>
    </div>
  );
}

function RecentAudiencesPanel() {
  const { data: audiences, isLoading } = useAudiences();
  const recent = (audiences ?? []).slice(0, 5);
  return (
    <section>
      <PanelHeader title="Recent audiences" href="/marketing/audiences" />
      {isLoading ? (
        <PanelSkeleton />
      ) : recent.length === 0 ? (
        <PanelEmpty
          icon={Users}
          message="No audiences yet."
          ctaHref="/marketing/audiences/new"
          ctaLabel="Create one"
        />
      ) : (
        <ul className="rounded-lg border bg-card divide-y overflow-hidden">
          {recent.map((a) => (
            <li key={a.id}>
              <Link
                href={`/marketing/audiences/${a.id}`}
                className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40 transition-colors group"
              >
                <Users className="size-4 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{a.name}</p>
                  <p className="text-[11px] text-muted-foreground truncate">
                    {a.last_member_count} members
                  </p>
                </div>
                <ChevronRight className="size-3.5 text-muted-foreground/60 group-hover:text-foreground transition-colors shrink-0" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RecentCampaignsPanel() {
  const { data: campaigns, isLoading } = useCampaigns();
  const recent = (campaigns ?? [])
    .filter(
      (c) =>
        c.status === 'scheduled' ||
        c.status === 'sending' ||
        c.status === 'draft',
    )
    .slice(0, 5);
  return (
    <section>
      <PanelHeader title="Live + draft campaigns" href="/marketing/campaigns" />
      {isLoading ? (
        <PanelSkeleton />
      ) : recent.length === 0 ? (
        <PanelEmpty
          icon={Send}
          message="No campaigns in flight."
          ctaHref="/marketing/campaigns/new"
          ctaLabel="Create one"
        />
      ) : (
        <ul className="rounded-lg border bg-card divide-y overflow-hidden">
          {recent.map((c) => {
            const Icon = c.channel === 'email' ? Mail : MessageSquare;
            return (
              <li key={c.id}>
                <Link
                  href={`/marketing/campaigns/${c.id}`}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40 transition-colors group"
                >
                  <Icon className="size-4 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{c.name}</p>
                    <p className="text-[11px] text-muted-foreground capitalize truncate">
                      {c.status}
                      {c.scheduled_at ? (
                        <>
                          {' · '}
                          {new Date(c.scheduled_at).toLocaleDateString()}
                        </>
                      ) : null}
                    </p>
                  </div>
                  <ChevronRight className="size-3.5 text-muted-foreground/60 group-hover:text-foreground transition-colors shrink-0" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function ActiveAutomationsPanel() {
  const { data: automations, isLoading } = useAutomations();
  const active = (automations ?? []).filter((a) => a.is_active).slice(0, 5);
  return (
    <section>
      <PanelHeader title="Active automations" href="/marketing/automations" />
      {isLoading ? (
        <PanelSkeleton />
      ) : active.length === 0 ? (
        <PanelEmpty
          icon={Sparkles}
          message="No active automations."
          ctaHref="/marketing/automations/new"
          ctaLabel="Create one"
        />
      ) : (
        <ul className="rounded-lg border bg-card divide-y overflow-hidden">
          {active.map((a) => {
            const TriggerIcon = TRIGGER_ICONS[a.trigger_type];
            return (
              <li key={a.id}>
                <Link
                  href={`/marketing/automations/${a.id}`}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40 transition-colors group"
                >
                  <TriggerIcon className="size-4 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{a.name}</p>
                    <p className="text-[11px] text-muted-foreground truncate">
                      {a.last_run_at ? (
                        <>
                          Last fired{' '}
                          {new Date(a.last_run_at).toLocaleDateString()}
                        </>
                      ) : (
                        <span className="italic">Never fired</span>
                      )}
                    </p>
                  </div>
                  <ChevronRight className="size-3.5 text-muted-foreground/60 group-hover:text-foreground transition-colors shrink-0" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function PanelSkeleton() {
  return (
    <div className="rounded-lg border bg-card divide-y overflow-hidden">
      {[0, 1, 2].map((i) => (
        <div key={i} className="px-4 py-3 flex items-center gap-3">
          <div className="size-4 rounded bg-muted/60 animate-pulse" />
          <div className="flex-1 space-y-1.5">
            <div className="h-3 rounded bg-muted/60 animate-pulse w-2/3" />
            <div className="h-2.5 rounded bg-muted/60 animate-pulse w-1/3" />
          </div>
        </div>
      ))}
    </div>
  );
}

function PanelEmpty({
  icon: Icon,
  message,
  ctaHref,
  ctaLabel,
}: {
  icon: React.ComponentType<{ className?: string }>;
  message: string;
  ctaHref: string;
  ctaLabel: string;
}) {
  return (
    <div className="rounded-lg border border-dashed bg-muted/20 px-4 py-8 text-center">
      <div className="inline-flex size-9 items-center justify-center rounded-full bg-card text-muted-foreground border mb-2">
        <Icon className="size-4" />
      </div>
      <p className="text-sm text-muted-foreground">{message}</p>
      <Link
        href={ctaHref}
        className="text-xs font-medium text-foreground hover:underline inline-block mt-2"
      >
        {ctaLabel} &rarr;
      </Link>
    </div>
  );
}
