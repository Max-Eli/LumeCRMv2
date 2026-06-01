/**
 * Blog post: How to choose a medspa CRM — the complete buyer's guide.
 *
 * Authoritative guide to evaluating CRM software for medical spas.
 * Covers criteria, questions to ask vendors, common mistakes, and
 * what's changed in 2025–2026 with AI features.
 *
 * Target queries:
 *   - "how to choose medspa CRM"
 *   - "medspa CRM buying guide"
 *   - "best medspa software 2026"
 *   - "medspa management software comparison"
 *   - "medspa EHR vs CRM"
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { BlogCallout, BlogPostLayout } from '@/components/blog-post-layout';
import { findPost } from '@/lib/blog';

const meta = findPost('medspa-crm-buying-guide')!;

export const metadata: Metadata = {
  title: meta.title,
  description: meta.summary,
  openGraph: {
    type: 'article',
    title: meta.title,
    description: meta.summary,
    publishedTime: meta.publishedAt,
  },
};

export default function Post() {
  return (
    <BlogPostLayout
      meta={meta}
      standfirst="Choosing the wrong CRM for a medical spa costs you twice: first in the purchase, then in the migration you'll eventually do anyway. This guide covers the criteria that actually matter, the questions no vendor wants to answer, and the features that have changed significantly in 2025–2026 with the emergence of AI tools."
    >
      <p>
        The medical spa software market has a structural problem:
        most platforms were built for a different business. Mindbody
        for yoga and wellness. Boulevard and Vagaro for hair salons.
        Zenoti for resort spa chains. Each one has grown into the
        medspa market through add-ons, partnerships, and feature
        requests — but the underlying data models and workflows were
        designed for a world without injectable consent, multi-drug
        treatment charting, provider-specific eligibility rules, and
        HIPAA's specific flavor of audit requirements.
      </p>

      <p>
        The result is a market where many medspas are running on
        software that is 60–70% right for their workflow, and
        covering the other 30–40% with paper, spreadsheets, and a
        second system they don't fully trust.
      </p>

      <p>
        This guide is for operators evaluating CRM software —
        whether that's an initial selection or a migration from an
        existing platform.
      </p>

      <h2>The distinction that matters most: CRM vs. EMR</h2>

      <p>
        A CRM (Customer Relationship Management system) handles the
        operational and business side: scheduling, payments, marketing,
        reporting, client communications. An EMR (Electronic Medical
        Record) handles the clinical side: diagnoses, treatments,
        provider notes, prescriptions, regulatory compliance.
      </p>

      <p>
        Most medspas need something in between — a system that handles
        the full booking-to-treatment-to-follow-up cycle, including
        both the business workflow and the clinical documentation.
        This is sometimes called a practice management system or a
        medspa-specific CRM.
      </p>

      <p>
        Be specific about what you need before evaluating software:
      </p>

      <ul>
        <li>
          <strong>Clinical charting depth:</strong> Do you need a
          full EMR with prescriptions, SOAP notes, and diagnosis
          codes? Or do you need treatment notes, provider
          observations, and before/after photo management? These
          require different systems.
        </li>
        <li>
          <strong>Regulatory environment:</strong> Are your providers
          writing prescriptions? Operating as a licensed medical
          practice? If yes, you may need a certified EHR rather than
          a practice management system.
        </li>
        <li>
          <strong>Practice complexity:</strong> A solo injector in
          one location has different needs than a three-location group
          with ten providers. Platform cost and overhead scales
          accordingly.
        </li>
      </ul>

      <h2>The twelve criteria that actually matter</h2>

      <h3>1. HIPAA compliance — architecture, not marketing</h3>

      <p>
        Every platform that serves medical practices will tell you
        they're HIPAA-compliant. The question is what that means
        structurally. Four things to verify:
      </p>

      <ul>
        <li>Is a Business Associate Agreement (BAA) included in the standard contract, or is it an add-on?</li>
        <li>Is tenant data isolated at the database level, or is it application-level filtering only?</li>
        <li>Is there an audit log on every PHI read that is append-only (not editable or deletable)?</li>
        <li>What infrastructure does the platform run on, and does that infrastructure carry its own BAA with the vendor?</li>
      </ul>

      <p>
        A HIPAA tier that costs extra is a red flag. Compliance
        infrastructure is either the foundation or it isn't. A
        platform that offers it optionally means the base product
        doesn't have it.
      </p>

      <h3>2. Clinical charting — what's included vs. what's extra</h3>

      <p>
        For medspas, clinical chart notes are not a premium feature.
        They are the core documentation requirement for the
        procedures you perform. A platform that gates chart notes
        to a higher tier is taxing the practices that most need
        the documentation.
      </p>

      <p>
        Ask specifically: Are clinical chart notes in the base plan?
        Can providers add free-text notes? Is there an edit window
        and addendum system (required for compliant charting)? Can
        chart notes be read by treatment record at a glance?
      </p>

      <h3>3. Consent forms — versioning and audit</h3>

      <p>
        Per-treatment consent versioning is a requirement in most
        aesthetic medicine practices. The consent the client signed
        for their Botox in 2023 is a snapshot of the form as it
        existed at the time of signing. If you update your consent
        template in 2024, that update must not retroactively change
        what the 2023 client saw. Any platform that updates consent
        form content in place — rather than versioning the template —
        is not compliant.
      </p>

      <p>
        Additionally, e-signature must capture: the client's name,
        the date and time, the IP address or device fingerprint,
        and the form content version. A screenshot of a signed PDF
        does not meet this bar.
      </p>

      <h3>4. Pricing structure — flat vs. per-seat</h3>

      <p>
        Per-seat pricing penalizes growth. Every provider you hire
        adds a line item to your monthly invoice. A medspa that
        goes from 3 providers to 6 — a normal staffing trajectory
        over two to three years — doubles its platform cost under
        a per-seat model. Flat per-workspace pricing, or per-location
        pricing with a reasonable staff seat bundle, is more
        appropriate for a growing practice.
      </p>

      <p>
        Also look for: setup fees, annual lock-ins, data export
        fees, and what happens to your data if you cancel. Paying
        $1,000 to retrieve your own patient records is not a
        hypothetical — some platforms charge it.
      </p>

      <h3>5. Booking and scheduling</h3>

      <p>
        The baseline is table stakes by now: provider columns,
        drag-to-reschedule, online booking page. The questions that
        separate good from mediocre:
      </p>

      <ul>
        <li>Does the public booking page enforce provider eligibility by service? (Can a client book a laser with a massage therapist?)</li>
        <li>Does the calendar support buffer time between appointments?</li>
        <li>Can the same provider appear in multiple locations?</li>
        <li>Does a deposit on booking sync to the invoice automatically?</li>
        <li>Does unsigned consent show up as a flag before the client arrives?</li>
      </ul>

      <h3>6. Payment processing and reconciliation</h3>

      <p>
        Integrated payment processing — where the card tap or swipe
        at checkout goes directly into the invoice without a
        separate terminal reconciliation — is now the standard.
        Platforms that require you to reconcile a separate POS
        against the scheduling system create daily close-out work.
      </p>

      <p>
        Know whether the platform marks up card processing, what
        the rate is versus market (typically 2.9% + 30¢), and
        whether you can bring your own merchant account at a
        certain tier.
      </p>

      <h3>7. AI SMS agent — the new category</h3>

      <p>
        As of 2025–2026, an AI SMS agent that books appointments
        via inbound text is a live, purchasable feature — not a
        roadmap item. Podium offers a standalone version at
        approximately $400–600/month. Some CRMs are building it
        natively with live schedule integration.
      </p>

      <p>
        If you're evaluating this, the key questions are: Does the
        agent access real-time schedule data, or does it hand off
        to a human for availability? Does it filter providers by
        service eligibility? What does the escalation path look
        like when the conversation exceeds the agent's scope? Is
        the LLM provider BAA-eligible?
      </p>

      <h3>8. Email and SMS marketing</h3>

      <p>
        A platform that requires you to export your client list to
        Mailchimp creates a stale-data problem: yesterday's new
        bookings aren't in the export yet, so your "don't market
        to recently booked clients" suppression is always behind.
        Built-in marketing tools that run against live CRM data
        eliminate that class of problem.
      </p>

      <p>
        Minimum features to look for: audience segmentation by
        service history, last-visit recency, package/membership
        status, and consent flags. Automation triggers on visit
        cadence (90-day lapsed, treatment-cycle reminder). Separate
        tracking of transactional vs. marketing consent.
      </p>

      <h3>9. Reporting</h3>

      <p>
        A medspa's reporting needs are specific: daily close-out
        by payment method, AR aging by provider and service,
        revenue by location, no-show rate trends, top-spending
        clients, and package redemption pace. Generic "sales
        dashboard" tools built for retail don't answer these
        questions cleanly.
      </p>

      <p>
        Ask for a demo of the specific reports you run today and
        confirm they exist before signing. CSV export should be
        included — gating data export to a premium tier or charging
        for it is a practice that will cost you later.
      </p>

      <h3>10. Multi-location support</h3>

      <p>
        If you have or plan to have more than one location: verify
        that the platform supports per-location calendars, per-location
        reporting filters, staff who span multiple locations,
        org-level rollup dashboards, and cross-location client
        records (one client record across all locations, not
        duplicated per site). Many platforms support the first four
        but not the fifth.
      </p>

      <h3>11. Migration support</h3>

      <p>
        Migrating off an existing platform is the most-underestimated
        part of a software switch. Client records, appointment
        history, package balances, consent forms, service catalog
        — all of this needs to come with you. Ask specifically
        what the vendor's migration process looks like, what data
        they can import from your current platform, what you lose
        in translation, and whether migration support is included
        in the contract.
      </p>

      <h3>12. Support and onboarding</h3>

      <p>
        For a medspa that runs on appointments and processes PHI,
        software downtime is not a minor inconvenience. Ask: what
        is the support channel (email, chat, phone)? What is the
        SLA for urgent issues? Is there a dedicated contact during
        onboarding, or is onboarding a Loom video series and a
        help center?
      </p>

      <h2>Questions to ask every vendor</h2>

      <BlogCallout label="The questions no vendor wants to answer clearly">
        <ol>
          <li>Is HIPAA compliance included in the base plan, or is there a separate HIPAA tier?</li>
          <li>Is a Business Associate Agreement in the standard contract, or do I need to request it separately?</li>
          <li>Are clinical chart notes included, or are they an add-on?</li>
          <li>How does consent form versioning work — can a template update change what a client signed last year?</li>
          <li>What does leaving look like — how do I export my complete client records, and what does it cost?</li>
          <li>What is the exact card processing rate, and do you markup the interchange?</li>
          <li>What is the onboarding timeline, and what does migration from [your current platform] include?</li>
          <li>What happens to my data if I cancel mid-year?</li>
        </ol>
      </BlogCallout>

      <h2>Common mistakes in the selection process</h2>

      <p>
        <strong>Evaluating on feature count rather than feature depth.</strong>{' '}
        A platform with 200 features, 30 of which matter to your
        workflow, is worse than a platform with 50 features that
        all work correctly for your workflow. Ask to demo the
        specific scenarios you run every day.
      </p>

      <p>
        <strong>Not asking about the migration.</strong> The cost
        of switching isn't the new platform's price — it's the
        migration labor and risk of data loss. Get specifics before
        signing.
      </p>

      <p>
        <strong>Choosing the cheapest per-seat option for a growing team.</strong>{' '}
        Do the math for your projected headcount in two years. A
        $15/user platform at 12 staff is $180/month. A flat
        $99/month platform at 12 staff is $99/month. The per-seat
        platform is cheaper at three users and more expensive by
        staff member six.
      </p>

      <p>
        <strong>Assuming HIPAA compliance from a marketing claim.</strong>{' '}
        "HIPAA-compliant" on a website does not mean the same thing
        as tenant isolation at the database, a signed BAA, and an
        append-only audit log. Ask for specifics.
      </p>

      <h2>What's changed in 2025–2026</h2>

      <p>
        Two developments have materially shifted the evaluation:
      </p>

      <p>
        <strong>AI SMS agents are production-ready.</strong> This
        is no longer a pilot feature or a roadmap item. Platforms
        with native AI SMS booking — where the agent has real-time
        access to schedules, provider eligibility, and client account
        data — represent a meaningful capability gap over platforms
        that don't have it. The math on missed evening and weekend
        bookings is significant enough that this has moved from
        "nice to have" to "worth paying for."
      </p>

      <p>
        <strong>Email and SMS marketing are converging with CRM.</strong>{' '}
        The pattern of "CRM for operations, Mailchimp for marketing"
        is being replaced by platforms that handle both with live
        data. This matters for segmentation precision and compliance:
        a marketing tool that doesn't know about Tuesday's new
        bookings until Friday's CSV export isn't running the right
        suppression lists.
      </p>

      <p>
        If you're evaluating now, both of those capabilities should
        be on your checklist.
      </p>

      <p>
        Lumè includes both in the Pro tier. If you'd like to see
        how the full platform maps to your specific workflow,{' '}
        <Link
          href="/demo"
          className="text-accent underline underline-offset-2 hover:text-foreground transition-colors"
        >
          request a demo
        </Link>
        . We configure the demo on your real service catalog.
      </p>
    </BlogPostLayout>
  );
}
